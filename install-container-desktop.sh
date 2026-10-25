#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
python3 - "$ROOT" <<'PY'
import os, sys
from pathlib import Path
root = Path(sys.argv[1])
settings = {
    'CANON_STUDIO_IMAGE': os.environ.get('CANON_STUDIO_IMAGE', 'localhost/canon-studio:latest'),
    'CANON_STUDIO_CONTAINER': os.environ.get('CANON_STUDIO_CONTAINER', 'canon-studio'),
    'CANON_STUDIO_PORT': os.environ.get('CANON_STUDIO_PORT', '8784'),
    'CANON_STUDIO_VIDEO_DEVICE': os.environ.get('CANON_STUDIO_VIDEO_DEVICE', '/dev/video0'),
    'CANON_STUDIO_DATA_DIR': os.environ.get('CANON_STUDIO_DATA_DIR', str(Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'canon-studio')),
    'CANON_STUDIO_MICROPHONE': os.environ.get('CANON_STUDIO_MICROPHONE', 'auto'),
    'PATH': os.environ.get('PATH', os.defpath),
}
# USB bus addresses change after reconnecting; only preserve an explicit override.
if os.environ.get('CANON_STUDIO_USB_DEVICE'):
    settings['CANON_STUDIO_USB_DEVICE'] = os.environ['CANON_STUDIO_USB_DEVICE']
def quoted(value):
    value = str(value).replace('%', '%%')
    for character in ('\\', '"', '`', '$'):
        value = value.replace(character, '\\' + character)
    return '"' + value.replace('\\', '\\\\').replace('\n', '\\n').replace('\r', '\\r') + '"'
destination = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'applications/canon-studio-container.desktop'
destination.parent.mkdir(parents=True, exist_ok=True)
command = ' '.join(quoted(arg) for arg in ['/usr/bin/env', *[f'{key}={value}' for key, value in settings.items()], str(root / 'podman.sh'), 'open'])
destination.write_text('[Desktop Entry]\nType=Application\nName=Canon Studio (Container)\nComment=Preview, record and control a Canon USB webcam with Podman\nExec=' + command + '\nIcon=camera-photo\nTerminal=false\nCategories=AudioVideo;Video;\n')
print(f'Installed {destination}')
PY
