#!/usr/bin/env python3
"""Loopback-only Canon camera studio; captures stay in the configured local data directory."""
import json, os, shutil, signal, socket, subprocess, threading, time, uuid
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, unquote

from config import ROOT, CAPTURES, DATA_DIR, PORT, SOCKET, VIDEO_DEVICE
from runtime import CameraRuntime
camera_runtime = CameraRuntime()
lock = threading.RLock()
frame_condition = threading.Condition()
frame = b''
frame_time = 0
recording = None
record_file = None
record_started = 0
record_log = None
last_error = ''
preview_process = None
shutdown = threading.Event()

def camera_command(command):
    path = SOCKET
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(20)
            client.connect(path)
            client.sendall(json.dumps(command).encode()+b'\n')
            with client.makefile('rb') as reader:
                result = json.loads(reader.readline(131072))
        if not result.get('ok'):
            raise ValueError(result.get('error','Camera command failed.'))
        return result
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError('Camera controls are unavailable. Start the camera feed, then try again.') from e

def camera_on():
    return camera_runtime.active()

def preview_worker():
    global frame, frame_time, preview_process
    while not shutdown.is_set():
        if not camera_on():
            shutdown.wait(1)
            continue
        proc = subprocess.Popen(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'v4l2', '-i', VIDEO_DEVICE, '-vf', 'fps=25', '-q:v', '2', '-f', 'image2pipe', '-vcodec', 'mjpeg', 'pipe:1'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        preview_process = proc
        buf = b''
        try:
            while not shutdown.is_set():
                chunk = proc.stdout.read(16384)
                if not chunk:
                    break
                buf += chunk
                while True:
                    start, end = buf.find(b'\xff\xd8'), buf.find(b'\xff\xd9')
                    if start < 0 or end < start:
                        break
                    with frame_condition:
                        frame = buf[start:end+2]
                        frame_time = time.monotonic()
                        frame_condition.notify_all()
                    buf = buf[end+2:]
                if len(buf) > 8_000_000:
                    buf = b''
        finally:
            proc.terminate()
            proc.wait()
            preview_process = None
        shutdown.wait(1)

def files():
    return [dict(name=p.name, url='/captures/'+p.name, size=p.stat().st_size,
                 kind='video' if p.suffix == '.mp4' else 'image', created=p.stat().st_mtime)
            for p in sorted(CAPTURES.iterdir(), key=lambda p:p.stat().st_mtime, reverse=True)
            if p.suffix in ('.jpg', '.mp4') and p != record_file]

def finish_recording():
    global recording, record_file, record_log, last_error
    if recording is None:
        return
    if recording.poll() is None:
        recording.send_signal(signal.SIGINT)
        try:
            recording.wait(timeout=15)
        except subprocess.TimeoutExpired:
            recording.kill()
            recording.wait()
            last_error = 'Recording could not close normally; inspect the saved clip.'
    record_log.close()
    if recording.returncode not in (0, 255):
        last_error = 'Recording failed. Check the camera connection and microphone.'
    recording = record_file = record_log = None

def status():
    with lock:
        if recording is not None and recording.poll() is not None:
            finish_recording()
        active = camera_on()
        return dict(camera=active, preview=active and time.monotonic()-frame_time < 3,
                    recording=recording is not None, elapsed=time.monotonic()-record_started if recording else 0,
                    error=last_error, files=files(), audioAvailable=True)

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def json(self, data, code=200):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def valid_host(self):
        return self.headers.get('Host') in (f'127.0.0.1:{PORT}', f'localhost:{PORT}')

    def do_GET(self):
        if not self.valid_host():
            return self.json({'error':'Invalid host'}, 403)
        path = unquote(urlparse(self.path).path)
        if path == '/api/status':
            return self.json(status())
        if path == '/api/settings':
            try:
                return self.json(camera_command({'op':'settings'}))
            except ValueError as e:
                return self.json({'error':str(e)},400)
        if path == '/preview.mjpg':
            self.send_response(200)
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            previous = 0
            try:
                while not shutdown.is_set():
                    with frame_condition:
                        frame_condition.wait_for(lambda: frame_time != previous, timeout=2)
                        current, stamp = frame, frame_time
                    if not current or stamp == previous or time.monotonic()-stamp > 3:
                        continue
                    previous = stamp
                    self.wfile.write(b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: '+str(len(current)).encode()+b'\r\n\r\n'+current+b'\r\n')
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        target = ROOT / 'index.html' if path == '/' else CAPTURES / Path(path).name if path.startswith('/captures/') else None
        if target is None or not target.is_file() or (target.parent == CAPTURES and target.suffix not in ('.jpg','.mp4')):
            return self.json({'error':'Not found'}, 404)
        size = target.stat().st_size
        start, end = 0, size-1
        ranged = self.headers.get('Range')
        try:
            if ranged:
                a,b = ranged.removeprefix('bytes=').split('-')
                start = int(a) if a else max(0,size-int(b))
                end = min(int(b),size-1) if b and a else size-1
                if start > end or start < 0:
                    raise ValueError()
        except ValueError:
            return self.json({'error':'Invalid range'},416)
        self.send_response(206 if ranged else 200)
        self.send_header('Content-Type', {'.html':'text/html; charset=utf-8','.jpg':'image/jpeg','.mp4':'video/mp4'}[target.suffix])
        self.send_header('Accept-Ranges','bytes')
        self.send_header('Cache-Control','no-store')
        if ranged:
            self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
        self.send_header('Content-Length',str(end-start+1))
        self.end_headers()
        try:
            with target.open('rb') as f:
                f.seek(start)
                remaining = end-start+1
                while remaining > 0:
                    chunk = f.read(min(65536,remaining))
                    if not chunk: break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError,ConnectionResetError):
            pass

    def do_POST(self):
        global recording, record_file, record_started, record_log, last_error
        if not self.valid_host() or self.headers.get('X-Camera-Studio') != '1':
            return self.json({'error':'Invalid request'},403)
        origin = self.headers.get('Origin')
        if origin and origin not in (f'http://127.0.0.1:{PORT}',f'http://localhost:{PORT}'):
            return self.json({'error':'Invalid origin'},403)
        try:
            raw_length = self.headers.get('Content-Length', '0')
            if not raw_length.isascii() or not raw_length.isdecimal():
                raise ValueError('Content-Length must be an integer between 0 and 1024.')
            length = int(raw_length)
            if not 0 <= length <= 1024:
                raise ValueError('Request too large; maximum body size is 1024 bytes.')
            data = json.loads(self.rfile.read(length) or b'{}')
            if not isinstance(data, dict):
                raise ValueError('Expected a JSON object.')
            with lock:
                last_error = ''
                if self.path == '/api/shutdown':
                    finish_recording()
                    if preview_process: preview_process.terminate()
                    camera_runtime.stop()
                    self.json({'ok': True})
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                    return
                elif self.path == '/api/settings/set':
                    self.json(camera_command({'op':'set','name':data.get('name'),'value':data.get('value')}))
                    return
                elif self.path == '/api/focus':
                    self.json(camera_command({'op':'focus'}))
                    return
                elif self.path == '/api/focus/nudge':
                    self.json(camera_command({'op':'nudge','value':data.get('value')}))
                    return
                elif self.path == '/api/focus/auto':
                    self.json(camera_command({'op':'auto','enabled':data.get('enabled'), 'interval':data.get('interval',5)}))
                    return
                elif self.path == '/api/camera/start':
                    started = time.monotonic()
                    camera_runtime.start()
                    with frame_condition:
                        ready = frame_condition.wait_for(lambda: frame_time > started, timeout=9)
                    if not ready:
                        raise ValueError('The Canon is not sending frames. Switch it off, wait a few seconds, turn it back on, then select Start camera.')
                elif self.path == '/api/camera/stop':
                    if recording: raise ValueError('Stop recording before turning off the camera feed.')
                    if preview_process: preview_process.terminate()
                    camera_runtime.stop()
                elif self.path == '/api/snapshot':
                    with frame_condition:
                        if time.monotonic()-frame_time > 3: raise ValueError('Camera preview is not ready.')
                        content = frame
                    name = time.strftime('Photo-%Y%m%d-%H%M%S-')+uuid.uuid4().hex[:6]+'.jpg'
                    (CAPTURES/name).write_bytes(content)
                elif self.path == '/api/record/start':
                    if recording: raise ValueError('Already recording.')
                    if time.monotonic()-frame_time > 3: raise ValueError('Camera preview is not ready.')
                    record_file = CAPTURES/(time.strftime('Video-%Y%m%d-%H%M%S-')+uuid.uuid4().hex[:6]+'.mp4')
                    cmd = ['ffmpeg','-hide_banner','-loglevel','warning','-thread_queue_size','256','-use_wallclock_as_timestamps','1','-f','mpjpeg','-i',f'http://127.0.0.1:{PORT}/preview.mjpg']
                    if data.get('audio'):
                        cmd += ['-thread_queue_size','256','-f','pulse','-i','default']
                    cmd += ['-c:v','libx264','-preset','veryfast','-crf','20','-pix_fmt','yuv420p']
                    cmd += ['-c:a','aac','-b:a','160k'] if data.get('audio') else ['-an']
                    cmd += ['-movflags','+frag_keyframe+empty_moov',str(record_file)]
                    record_log = (DATA_DIR/'recording.log').open('w')
                    recording = subprocess.Popen(cmd,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=record_log)
                    record_started = time.monotonic()
                elif self.path == '/api/record/stop':
                    finish_recording()
                else:
                    return self.json({'error':'Not found'},404)
            self.json({'ok':True})
        except (ValueError, TypeError, subprocess.SubprocessError, OSError) as e:
            last_error = str(e)
            self.json({'error':str(e)},400)

if __name__ == '__main__':
    if not shutil.which('ffmpeg'):
        raise SystemExit('FFmpeg is missing. Install ffmpeg and make it available on PATH.')
    def terminate(signum, stack):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, terminate)
    CAPTURES.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=preview_worker,daemon=True).start()
    server = ThreadingHTTPServer(('127.0.0.1',PORT),Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        shutdown.set()
        with lock: finish_recording()
        if preview_process: preview_process.terminate()
        camera_runtime.close()
        server.server_close()
