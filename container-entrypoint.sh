#!/usr/bin/env bash
set -euo pipefail
umask 077
mkdir -p -- "$XDG_RUNTIME_DIR" "$CANON_STUDIO_DATA_DIR/captures"
chmod 700 -- "$XDG_RUNTIME_DIR"
exec "$@"
