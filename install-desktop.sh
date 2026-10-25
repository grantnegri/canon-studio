#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
python3 - "$ROOT" <<'PY'
import os, sys
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))
from config import VIDEO_DEVICE, PORT, DATA_DIR, GPHOTO2_LIBRARY
settings = {
    'CANON_STUDIO_VIDEO_DEVICE': VIDEO_DEVICE,
    'CANON_STUDIO_PORT': str(PORT),
    'CANON_STUDIO_DATA_DIR': str(DATA_DIR),
    'CANON_STUDIO_GPHOTO2_LIBRARY': GPHOTO2_LIBRARY,
    'PATH': os.environ.get('PATH', os.defpath),
}
# Desktop Entry escaping has both an Exec quoting layer and string-value layer.
def quoted(value):
    value = str(value).replace('%', '%%')
    for character in ('\\', '"', '`', '$'):
        value = value.replace(character, '\\' + character)
    return '"' + value.replace('\\', '\\\\').replace('\n', '\\n').replace('\r', '\\r') + '"'
destination = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'applications/canon-studio.desktop'
destination.parent.mkdir(parents=True, exist_ok=True)
command = ' '.join(quoted(arg) for arg in ['/usr/bin/env', *[f'{key}={value}' for key, value in settings.items()], str(root / 'launch.sh')])
destination.write_text('[Desktop Entry]\nType=Application\nName=Canon Studio\nComment=Preview, record and control a Canon USB webcam\nExec=' + command + '\nIcon=camera-photo\nTerminal=false\nCategories=AudioVideo;Video;\n')
print(f'Installed {destination}')
PY
