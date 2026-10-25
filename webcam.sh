#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
eval "$(python3 "$ROOT/config.py")"
unit=canon-webcam.service
check_device() {
    for dependency in ffmpeg v4l2-ctl; do
      if ! command -v "$dependency" >/dev/null; then
        echo "Missing dependency: $dependency. Install FFmpeg and v4l-utils." >&2
        exit 1
      fi
    done
    if [[ ! -w "$CANON_STUDIO_VIDEO_DEVICE" ]]; then
      echo "Virtual camera is missing or not writable: $CANON_STUDIO_VIDEO_DEVICE. Set up v4l2loopback first." >&2
      exit 1
    fi
    # Refuse physical cameras/capture cards even when the configured node is writable.
    driver_info=$(LC_ALL=C v4l2-ctl --device="$CANON_STUDIO_VIDEO_DEVICE" --info)
    if [[ ! "$driver_info" =~ Driver[[:space:]]+name[[:space:]]*:[[:space:]]*v4l2[[:space:]]+loopback ]]; then
      echo "Refusing to write to $CANON_STUDIO_VIDEO_DEVICE: its driver is not v4l2loopback." >&2
      exit 1
    fi
}
case "${1:-start}" in
  start)
    if systemctl --user is-active --quiet "$unit"; then
      echo 'Canon webcam is already running.'
      exit 0
    fi
    check_device
    if command -v fuser >/dev/null && fuser "$CANON_STUDIO_VIDEO_DEVICE" >/dev/null 2>&1; then
      echo 'The virtual camera is busy. Stop the other camera producer first.' >&2
      exit 1
    fi
    systemd-run --user --collect --unit=canon-webcam \
      --property=KillSignal=SIGINT --property=TimeoutStopSec=10 \
      --setenv="PATH=$PATH" --setenv="XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR" \
      --setenv="CANON_STUDIO_VIDEO_DEVICE=$CANON_STUDIO_VIDEO_DEVICE" \
      --setenv="CANON_STUDIO_PORT=$CANON_STUDIO_PORT" \
      --setenv="CANON_STUDIO_DATA_DIR=$CANON_STUDIO_DATA_DIR" \
      --setenv="CANON_STUDIO_GPHOTO2_LIBRARY=$CANON_STUDIO_GPHOTO2_LIBRARY" \
      --description='Canon Studio USB webcam' \
      "$(command -v bash)" "$ROOT/webcam.sh" stream
    echo "Starting Canon feed on $CANON_STUDIO_VIDEO_DEVICE."
    ;;
  stop)
    if systemctl --user is-active --quiet "$unit"; then systemctl --user stop "$unit"; fi
    ;;
  status) systemctl --user status "$unit" --no-pager ;;
  stream)
    check_device
    python3 "$ROOT/camera_bridge.py" |
      ffmpeg -hide_banner -loglevel warning -f mjpeg -framerate 25 -i pipe:0 \
        -an -c:v rawvideo -pix_fmt yuv420p -f v4l2 "$CANON_STUDIO_VIDEO_DEVICE"
    ;;
  *) echo "Usage: $0 [start|stop|status]" >&2; exit 2 ;;
esac
