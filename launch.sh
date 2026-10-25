#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
eval "$(python3 "$ROOT/config.py")"
mkdir -p -- "$CANON_STUDIO_DATA_DIR/captures"
if ! systemctl --user is-active --quiet canon-studio.service; then
  systemd-run --user --collect --unit=canon-studio \
    --setenv="PATH=$PATH" --setenv="XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR" \
    --setenv="CANON_STUDIO_VIDEO_DEVICE=$CANON_STUDIO_VIDEO_DEVICE" \
    --setenv="CANON_STUDIO_PORT=$CANON_STUDIO_PORT" \
    --setenv="CANON_STUDIO_DATA_DIR=$CANON_STUDIO_DATA_DIR" \
    --setenv="CANON_STUDIO_GPHOTO2_LIBRARY=$CANON_STUDIO_GPHOTO2_LIBRARY" \
    --description='Canon Studio' "$(command -v python3)" "$ROOT/server.py"
fi
python3 - <<'PY'
import json, os, time, urllib.request
url = 'http://127.0.0.1:' + os.environ['CANON_STUDIO_PORT'] + '/api/status'
for _ in range(30):
    try:
        with urllib.request.urlopen(url, timeout=1) as response:
            data = json.load(response)
        if 'camera' in data and 'preview' in data:
            break
    except (OSError, ValueError):
        pass
    time.sleep(0.3)
else:
    raise SystemExit('Canon Studio did not become ready. Inspect: journalctl --user -u canon-studio.service')
PY
exec xdg-open "http://127.0.0.1:$CANON_STUDIO_PORT"
