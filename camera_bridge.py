#!/usr/bin/env python3
"""One libgphoto2 owner: MJPEG on stdout and private JSON-line control socket.

The socket never calls gphoto on its own thread. Commands expire before dispatch;
commands already inside a USB call cannot be cancelled and are reported as such.
ABI: upstream gphoto2-camera.h, gphoto2-widget.h and gphoto2-file.h.
"""
import ctypes as C
import ctypes.util
import json
import math
import os
from pathlib import Path
import queue
import signal
import socket
import socketserver
import sys
import threading
import time

SETTINGS = ('iso', 'aperture', 'shutterspeed', 'whitebalance',
            'exposurecompensation', 'autoexposuremode', 'afmethod',
            'focusmode', 'lensname', 'batterylevel')
ACTIONS = ('manualfocusdrive', 'autofocusdrive')
from config import SOCKET, GPHOTO2_LIBRARY
TYPES = {2: 'text', 3: 'range', 4: 'toggle', 5: 'radio', 6: 'menu', 8: 'date'}


class Camera:
    def __init__(self):
        self.lib = None
        for name in (GPHOTO2_LIBRARY, ctypes.util.find_library('gphoto2'), 'libgphoto2.so.6'):
            if name:
                try:
                    self.lib = C.CDLL(name)
                    break
                except OSError:
                    pass
        if not self.lib:
            raise RuntimeError('libgphoto2 is unavailable; run this bridge on the host.')
        p, i, s = C.c_void_p, C.c_int, C.c_char_p
        signatures = {
            'gp_context_new': (p, []), 'gp_context_unref': (None, [p]),
            'gp_camera_new': (i, [C.POINTER(p)]),
            'gp_camera_init': (i, [p, p]), 'gp_camera_exit': (i, [p, p]),
            'gp_camera_free': (i, [p]), 'gp_camera_get_config': (i, [p, C.POINTER(p), p]),
            'gp_camera_get_single_config': (i, [p, s, C.POINTER(p), p]),
            'gp_camera_set_single_config': (i, [p, s, p, p]),
            'gp_widget_free': (i, [p]), 'gp_widget_get_child_by_name': (i, [p, s, C.POINTER(p)]),
            'gp_widget_get_type': (i, [p, C.POINTER(i)]),
            'gp_widget_get_readonly': (i, [p, C.POINTER(i)]),
            'gp_widget_get_label': (i, [p, C.POINTER(s)]),
            'gp_widget_get_value': (i, [p, p]), 'gp_widget_set_value': (i, [p, p]),
            'gp_widget_count_choices': (i, [p]),
            'gp_widget_get_choice': (i, [p, i, C.POINTER(s)]),
            'gp_widget_get_range': (i, [p, C.POINTER(C.c_float), C.POINTER(C.c_float), C.POINTER(C.c_float)]),
            'gp_file_new': (i, [C.POINTER(p)]), 'gp_file_free': (i, [p]),
            'gp_camera_capture_preview': (i, [p, p, p]),
            'gp_file_get_data_and_size': (i, [p, C.POINTER(p), C.POINTER(C.c_ulong)]),
            'gp_result_as_string': (s, [i]),
        }
        for name, (restype, argtypes) in signatures.items():
            fn = getattr(self.lib, name)
            fn.restype, fn.argtypes = restype, argtypes
        self.context = self.lib.gp_context_new()
        self.camera = p()
        self.initialized = False
        try:
            self.check(self.lib.gp_camera_new(C.byref(self.camera)))
            self.check(self.lib.gp_camera_init(self.camera, self.context))
            self.initialized = True
        except Exception:
            self.close()
            raise

    def check(self, result):
        if result < 0:
            message = self.lib.gp_result_as_string(result)
            raise RuntimeError(f'{message.decode(errors="replace") if message else "Camera error"} ({result})')
        return result

    def metadata(self, widget):
        kind, readonly, label = C.c_int(), C.c_int(), C.c_char_p()
        self.check(self.lib.gp_widget_get_type(widget, C.byref(kind)))
        self.check(self.lib.gp_widget_get_readonly(widget, C.byref(readonly)))
        self.check(self.lib.gp_widget_get_label(widget, C.byref(label)))
        data = {'label': (label.value or b'').decode(errors='replace'),
                'type': TYPES.get(kind.value, 'unsupported'), 'readonly': bool(readonly.value),
                'choices': [], 'value': None}
        if kind.value in (2, 5, 6):
            value = C.c_char_p()
        elif kind.value in (4, 8):
            value = C.c_int()
        elif kind.value == 3:
            value = C.c_float()
        else:
            data['readonly'] = True
            return data
        self.check(self.lib.gp_widget_get_value(widget, C.byref(value)))
        data['value'] = (value.value or b'').decode(errors='replace') if kind.value in (2, 5, 6) else value.value
        if kind.value in (5, 6):
            count = self.check(self.lib.gp_widget_count_choices(widget))
            for n in range(count):
                choice = C.c_char_p()
                self.check(self.lib.gp_widget_get_choice(widget, n, C.byref(choice)))
                data['choices'].append((choice.value or b'').decode(errors='replace'))
        if kind.value == 3:
            lo, hi, step = C.c_float(), C.c_float(), C.c_float()
            self.check(self.lib.gp_widget_get_range(widget, C.byref(lo), C.byref(hi), C.byref(step)))
            data.update(min=lo.value, max=hi.value, step=step.value)
        return data

    def settings(self):
        root = C.c_void_p()
        self.check(self.lib.gp_camera_get_config(self.camera, C.byref(root), self.context))
        try:
            result = {}
            for name in SETTINGS + ACTIONS:
                child = C.c_void_p()
                if self.lib.gp_widget_get_child_by_name(root, name.encode(), C.byref(child)) >= 0:
                    result[name] = self.metadata(child)
            # libgphoto lists a generic EOS mode table, including modes this body
            # does not have. Offer the two webcam modes verified on this T2i.
            if 'autoexposuremode' in result:
                result['autoexposuremode']['choices'] = ['Movie', 'Manual']
            if 'afmethod' in result:
                result['afmethod']['choices'] = ['Live', 'LiveFace']
            # Movie auto-exposure may report stale numeric ranges after changing
            # modes. Do not offer those as usable manual exposure controls.
            if result.get('autoexposuremode', {}).get('value') == 'Movie':
                for name in ('iso', 'aperture', 'shutterspeed'):
                    if name in result:
                        result[name]['readonly'] = True
                        result[name]['choices'] = [str(result[name]['value'])]
            if 'focusmode' in result:
                result['focusmode']['readonly'] = True
            return result
        finally:
            self.lib.gp_widget_free(root)

    def set(self, name, value):
        widget = C.c_void_p()
        self.check(self.lib.gp_camera_get_single_config(self.camera, name.encode(), C.byref(widget), self.context))
        try:
            meta = self.metadata(widget)
            if meta['readonly']:
                raise ValueError(f'{meta["label"]} is read-only in the current camera mode.')
            kind = meta['type']
            if kind in ('radio', 'menu'):
                if not isinstance(value, str) or value not in meta['choices']:
                    raise ValueError('Choose one of the values currently offered by the camera.')
                raw = C.c_char_p(value.encode())
                arg = C.cast(raw, C.c_void_p)
            elif kind == 'toggle':
                if value not in (0, 1, False, True):
                    raise ValueError('Toggle value must be 0 or 1.')
                raw = C.c_int(int(value))
                arg = C.byref(raw)
            elif kind == 'range':
                number = float(value)
                if not math.isfinite(number) or not meta['min'] <= number <= meta['max']:
                    raise ValueError('Value is outside the camera range.')
                raw = C.c_float(number)
                arg = C.byref(raw)
            else:
                raise ValueError('This setting is informational and cannot be changed here.')
            self.check(self.lib.gp_widget_set_value(widget, arg))
            self.check(self.lib.gp_camera_set_single_config(self.camera, name.encode(), widget, self.context))
        finally:
            self.lib.gp_widget_free(widget)

    def preview(self):
        file = C.c_void_p()
        self.check(self.lib.gp_file_new(C.byref(file)))
        try:
            self.check(self.lib.gp_camera_capture_preview(self.camera, file, self.context))
            data, size = C.c_void_p(), C.c_ulong()
            self.check(self.lib.gp_file_get_data_and_size(file, C.byref(data), C.byref(size)))
            return C.string_at(data, size.value)
        finally:
            self.lib.gp_file_free(file)

    def close(self):
        if self.camera:
            if self.initialized:
                try:
                    self.set('autofocusdrive', 0)
                except Exception as exc:
                    print(f'Autofocus cleanup: {exc}', file=sys.stderr)
                try:
                    self.set('viewfinder', 0)
                except Exception as exc:
                    print(f'Viewfinder cleanup: {exc}', file=sys.stderr)
                self.lib.gp_camera_exit(self.camera, self.context)
            self.lib.gp_camera_free(self.camera)
            self.camera = None
        if self.context:
            self.lib.gp_context_unref(self.context)
            self.context = None


class Command:
    def __init__(self, payload):
        self.payload = payload
        self.deadline = time.monotonic() + 12
        self.lock = threading.Lock()
        self.done = threading.Event()
        self.started = False
        self.cancelled = False
        self.result = None

    def begin(self):
        with self.lock:
            if self.cancelled or time.monotonic() >= self.deadline:
                self.cancelled = True
                return False
            self.started = True
            return True

    def timeout(self):
        with self.lock:
            if not self.started:
                self.cancelled = True
                return {'ok': False, 'error': 'Camera busy; queued command cancelled.'}
            return {'ok': False, 'error': 'Camera command is still in progress; refresh settings before retrying.'}


class Bridge:
    def __init__(self, camera):
        self.camera = camera
        self.queue = queue.Queue(maxsize=16)
        self.stop = threading.Event()
        self.auto = {'enabled': False, 'interval': 5, 'error': None, 'focusing': False}
        self.focus_release_at = None
        self.next_focus = 0

    def release_focus(self, force=False):
        if not self.auto['focusing'] and not force:
            return
        # Canon AFDrive(0) invokes AfCancel and checks EOS events in libgphoto2.
        # Clear the timer before dispatch: a failed release must not retry each frame.
        self.focus_release_at = None
        try:
            self.camera.set('autofocusdrive', 0)
        except Exception as exc:
            self.auto.update(enabled=False, error=f'Could not release autofocus: {exc}')
            raise
        self.auto['focusing'] = False

    def focus(self):
        if self.auto['focusing']:
            raise ValueError('Autofocus is already running; wait for it to release or cancel it.')
        settings = self.camera.settings()
        mode = str(settings.get('focusmode', {}).get('value', '')).lower()
        if 'manual' in mode or mode == 'mf':
            raise ValueError('Lens is in manual focus. Switch the lens to AF; its physical AF/MF switch cannot be changed by USB.')
        method = str(settings.get('afmethod', {}).get('value', '')).lower()
        if 'quick' in method:
            raise ValueError('Choose Live or Face detection autofocus first; Quick AF interrupts the webcam preview.')
        self.camera.set('autofocusdrive', 1)
        self.auto['focusing'] = True
        self.focus_release_at = time.monotonic() + 2.0

    def execute(self, cmd):
        op = cmd.get('op')
        if op == 'settings':
            return {'ok': True, 'settings': self.camera.settings(), 'autoFocus': dict(self.auto)}
        if op == 'set':
            if cmd.get('name') not in SETTINGS:
                raise ValueError('Setting is not supported by Canon Studio.')
            meta = self.camera.settings().get(cmd['name'], {})
            if meta.get('readonly', True):
                raise ValueError('This setting is automatic or read-only. Select Manual exposure mode for ISO, aperture, and shutter controls.')
            if cmd.get('value') not in meta.get('choices', []):
                raise ValueError('Choose one of the settings offered for this camera mode.')
            self.release_focus()
            self.camera.set(cmd['name'], cmd.get('value'))
        elif op == 'focus':
            self.focus()
        elif op == 'cancel':
            self.auto['enabled'] = False
            self.release_focus(force=True)
        elif op == 'nudge':
            self.release_focus()
            self.camera.set('manualfocusdrive', cmd.get('value'))
        elif op == 'auto':
            enabled = cmd.get('enabled')
            if not isinstance(enabled, bool):
                raise ValueError('enabled must be true or false.')
            interval = float(cmd.get('interval', self.auto['interval']))
            if not math.isfinite(interval) or not 3 <= interval <= 60:
                raise ValueError('Auto-refocus interval must be between 3 and 60 seconds.')
            # One immediate attempt validates AF mode/support before enabling repeats.
            if enabled:
                try:
                    if not self.auto['focusing']:
                        self.focus()
                except Exception as exc:
                    self.auto.update(enabled=False, error=str(exc))
                    raise
            else:
                self.release_focus()
            self.auto.update(enabled=enabled, interval=interval, error=None)
            self.next_focus = time.monotonic() + interval
        else:
            raise ValueError('Unknown camera operation.')
        return {'ok': True, 'autoFocus': dict(self.auto)}

    def process(self):
        if self.focus_release_at is not None and time.monotonic() >= self.focus_release_at:
            try:
                self.release_focus()
            except Exception as exc:
                print(f'Autofocus release failed: {exc}', file=sys.stderr)
        for _ in range(2):
            try:
                cmd = self.queue.get_nowait()
            except queue.Empty:
                break
            if cmd.begin():
                try:
                    cmd.result = self.execute(cmd.payload)
                except Exception as exc:
                    cmd.result = {'ok': False, 'error': str(exc), 'autoFocus': dict(self.auto)}
            else:
                cmd.result = {'ok': False, 'error': 'Queued command expired and was cancelled.'}
            cmd.done.set()
        if self.auto['enabled'] and time.monotonic() >= self.next_focus:
            try:
                self.focus()
            except Exception as exc:
                self.auto.update(enabled=False, error=str(exc))
            self.next_focus = time.monotonic() + self.auto['interval']


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.request.settimeout(15)
        try:
            line = self.rfile.readline(4097)
            if len(line) > 4096 or not line.endswith(b'\n'):
                raise ValueError('Expected one JSON line, at most 4096 bytes.')
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError('Expected a JSON object.')
            command = Command(payload)
            self.server.bridge.queue.put_nowait(command)
            result = command.result if command.done.wait(12) else command.timeout()
        except Exception as exc:
            result = {'ok': False, 'error': str(exc) or 'Camera command queue is full.'}
        try:
            self.wfile.write(json.dumps(result).encode() + b'\n')
        except (OSError, TimeoutError):
            pass


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def main():
    path = Path(SOCKET)
    # A private runtime directory plus mode 0600 keeps control local to this user.
    if not path.parent.is_dir() or path.parent.stat().st_uid != os.getuid():
        raise RuntimeError('Private user runtime directory is unavailable.')
    if path.exists():
        with socket.socket(socket.AF_UNIX) as probe:
            probe.settimeout(1)
            try:
                probe.connect(SOCKET)
            except (ConnectionRefusedError, FileNotFoundError):
                path.unlink(missing_ok=True)
            else:
                raise RuntimeError('Another camera bridge is already running.')
    camera = Camera()
    bridge = Bridge(camera)
    server = None
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: bridge.stop.set())
    try:
        camera.set('viewfinder', 1)
        old_umask = os.umask(0o177)
        try:
            server = Server(SOCKET, Handler)
        finally:
            os.umask(old_umask)
        server.bridge = bridge
        threading.Thread(target=server.serve_forever, daemon=True).start()
        print(f'Canon camera bridge ready: {SOCKET}', file=sys.stderr)
        failures = 0
        while not bridge.stop.is_set():
            bridge.process()
            try:
                frame = camera.preview()
                failures = 0
            except RuntimeError as exc:
                failures += 1
                if failures >= 10:
                    raise
                print(f'Preview retry {failures}: {exc}', file=sys.stderr)
                bridge.stop.wait(0.1)
                continue
            sys.stdout.buffer.write(frame)
            sys.stdout.buffer.flush()
    finally:
        bridge.stop.set()
        if server:
            server.shutdown()
            server.server_close()
            path.unlink(missing_ok=True)
        try:
            bridge.release_focus()
        except Exception as exc:
            print(f'Autofocus cleanup: {exc}', file=sys.stderr)
        camera.close()


if __name__ == '__main__':
    try:
        main()
    except (BrokenPipeError, KeyboardInterrupt):
        pass
    except Exception as exc:
        print(f'Canon bridge stopped: {exc}', file=sys.stderr)
        sys.exit(1)
