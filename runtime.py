"""Camera process ownership for native systemd and standalone containers."""
import os
import signal
import subprocess
import threading

from config import DATA_DIR, ROOT


class CameraRuntime:
    def __init__(self, mode=None, root=ROOT, data_dir=DATA_DIR):
        self.mode = mode or os.environ.get('CANON_STUDIO_RUNTIME', 'systemd')
        if self.mode not in ('systemd', 'container'):
            raise ValueError('CANON_STUDIO_RUNTIME must be systemd or container')
        self.script = root / 'webcam.sh'
        self.data_dir = data_dir
        self.process = None
        self.log = None
        self.lock = threading.RLock()

    def active(self):
        if self.mode == 'systemd':
            return subprocess.run(['systemctl', '--user', 'is-active', '--quiet',
                                   'canon-webcam.service']).returncode == 0
        with self.lock:
            return self.process is not None and self.process.poll() is None

    def start(self):
        if self.mode == 'systemd':
            subprocess.run(['bash', str(self.script), 'start'], check=True,
                           capture_output=True, timeout=15)
            return
        with self.lock:
            if self.active():
                return
            self.stop()
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self.log = (self.data_dir / 'camera.log').open('a')
            try:
                self.process = subprocess.Popen(
                    ['bash', str(self.script), 'stream'], stdin=subprocess.DEVNULL,
                    stdout=self.log, stderr=self.log, start_new_session=True)
            except Exception:
                self.log.close()
                self.log = None
                raise

    def stop(self):
        if self.mode == 'systemd':
            subprocess.run(['bash', str(self.script), 'stop'], check=True,
                           capture_output=True, timeout=15)
            return
        with self.lock:
            proc = self.process
            try:
                if proc is not None and proc.poll() is None:
                    try:
                        os.killpg(proc.pid, signal.SIGINT)
                    except ProcessLookupError:
                        pass
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        try:
                            os.killpg(proc.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        proc.wait()
            finally:
                self.process = None
                if self.log is not None:
                    self.log.close()
                    self.log = None

    def close(self):
        # Native systemd owns its feed independently of the UI server.
        if self.mode == 'container':
            self.stop()
