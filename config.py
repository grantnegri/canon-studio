"""Shared runtime configuration; importing this module has no side effects."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VIDEO_DEVICE = os.environ.get('CANON_STUDIO_VIDEO_DEVICE', '/dev/video0')
PORT = int(os.environ.get('CANON_STUDIO_PORT', '8784'))
if not 1 <= PORT <= 65535:
    raise ValueError('CANON_STUDIO_PORT must be between 1 and 65535')
DATA_DIR = Path(os.environ.get('CANON_STUDIO_DATA_DIR',
    str(Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'canon-studio'))).expanduser().resolve()
CAPTURES = DATA_DIR / 'captures'
RUNTIME_DIR = Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}'))
SOCKET = str(RUNTIME_DIR / 'canon-studio-control.sock')
GPHOTO2_LIBRARY = os.environ.get('CANON_STUDIO_GPHOTO2_LIBRARY', '')

if __name__ == '__main__':
    import shlex
    for name, value in {
        'CANON_STUDIO_VIDEO_DEVICE': VIDEO_DEVICE,
        'CANON_STUDIO_PORT': str(PORT),
        'CANON_STUDIO_DATA_DIR': str(DATA_DIR),
        'XDG_RUNTIME_DIR': str(RUNTIME_DIR),
        'CANON_STUDIO_GPHOTO2_LIBRARY': GPHOTO2_LIBRARY,
    }.items():
        print(f'export {name}={shlex.quote(value)}')
