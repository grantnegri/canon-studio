#!/usr/bin/env bash
# Run on the Bazzite host, not inside a toolbox/distrobox.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
IMAGE=${CANON_STUDIO_IMAGE:-localhost/canon-studio:latest}
NAME=${CANON_STUDIO_CONTAINER:-canon-studio}
PORT=${CANON_STUDIO_PORT:-8784}
VIDEO=${CANON_STUDIO_VIDEO_DEVICE:-/dev/video0}
DATA=${CANON_STUDIO_DATA_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/canon-studio}
fail() { printf '%s\n' "$*" >&2; exit 1; }
command -v podman >/dev/null || fail 'Podman is required. Run this script on the Bazzite host.'
[[ $(id -u) != 0 ]] || fail 'Run as your desktop user, without sudo (rootless Podman).'
exists() { podman container exists "$NAME"; }
running() { exists && [[ $(podman inspect --format '{{.State.Running}}' "$NAME") == true ]]; }
managed() {
  [[ $(podman inspect --format '{{index .Config.Labels "io.github.canon-studio.managed"}}' "$NAME") == true ]] || fail "Container $NAME is not managed by this script. Choose CANON_STUDIO_CONTAINER."
}
check_native() {
  if command -v systemctl >/dev/null; then
    for unit in canon-studio.service canon-webcam.service; do
      if systemctl --user is-active --quiet "$unit"; then
        fail "Native $unit is running. Finish any recording, then stop native services with: systemctl --user stop canon-studio.service canon-webcam.service"
      fi
    done
  fi
}
find_usb() {
  local entry device vendor product bus number
  local -a matches=()
  for entry in /sys/bus/usb/devices/*; do
    [[ -r $entry/idVendor && -r $entry/idProduct && -r $entry/busnum && -r $entry/devnum ]] || continue
    read -r vendor < "$entry/idVendor"
    read -r product < "$entry/idProduct"
    [[ $vendor == 04a9 ]] || continue
    read -r bus < "$entry/busnum"
    read -r number < "$entry/devnum"
    printf -v device '/dev/bus/usb/%03d/%03d' "$((10#$bus))" "$((10#$number))"
    if [[ -n ${CANON_STUDIO_USB_DEVICE:-} ]]; then
      [[ $device == "$CANON_STUDIO_USB_DEVICE" ]] && matches+=("$device")
    elif [[ $product == 31ea ]]; then
      matches+=("$device")
    fi
  done
  ((${#matches[@]} == 1)) || fail 'Expected one powered-on Canon EOS 550D/T2i over USB. For another Canon or multiple cameras set CANON_STUDIO_USB_DEVICE=/dev/bus/usb/BBB/DDD.'
  USB=${matches[0]}
  [[ -c $USB && -r $USB && -w $USB ]] || fail "No read/write access to $USB. Connect and turn on the camera in your active desktop session."
}
check_video() {
  [[ -c $VIDEO && -r $VIDEO && -w $VIDEO ]] || fail "No read/write access to $VIDEO. Load host v4l2loopback and set CANON_STUDIO_VIDEO_DEVICE to its device."
  python3 - "$VIDEO" <<'PY'
import fcntl, os, sys
try:
    fd = os.open(sys.argv[1], os.O_RDWR | os.O_NONBLOCK)
    try:
        info = bytearray(104)
        fcntl.ioctl(fd, 0x80685600, info)  # VIDIOC_QUERYCAP
    finally:
        os.close(fd)
    driver = bytes(info[:16]).split(b'\0', 1)[0]
    if driver != b'v4l2 loopback':
        raise ValueError(f'{sys.argv[1]} uses {driver!r}, not v4l2loopback')
except (OSError, ValueError) as exc:
    raise SystemExit(f'{exc}. Create a host v4l2loopback device; a container cannot load the kernel module.')
PY
}
ready() {
  python3 - "$PORT" <<'PY'
import json, sys, time, urllib.request
url = f'http://127.0.0.1:{int(sys.argv[1])}/api/status'
for _ in range(40):
    try:
        with urllib.request.urlopen(url, timeout=1) as response:
            result = json.load(response)
        if 'camera' in result and 'preview' in result:
            break
    except (OSError, ValueError):
        pass
    time.sleep(.25)
else:
    raise SystemExit('Canon Studio did not become ready. Inspect ./podman.sh logs')
PY
}
start() {
  if exists; then managed; fi
  if running; then
    printf 'Canon Studio is already running.\n'
    return
  fi
  check_native
  command -v python3 >/dev/null || fail 'Host python3 is required for device and readiness checks.'
  [[ $PORT =~ ^[0-9]+$ ]] && ((10#$PORT >= 1 && 10#$PORT <= 65535)) || fail 'CANON_STUDIO_PORT must be between 1 and 65535.'
  podman image exists "$IMAGE" || fail 'Build the image first: ./podman.sh build'
  check_video
  find_usb
  # Refuse a port already in use before taking ownership of camera devices.
  python3 - "$PORT" <<'PY'
import socket, sys
with socket.socket() as sock:
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(('127.0.0.1', int(sys.argv[1])))
    except OSError as exc:
        raise SystemExit(f'Port {sys.argv[1]} is unavailable: {exc}')
PY
  mkdir -p -- "$DATA"
  DATA=$(cd -- "$DATA" && pwd)
  local -a args=(--detach --name "$NAME" --label io.github.canon-studio.managed=true
    --network=host --userns=keep-id --group-add keep-groups
    --cap-drop=ALL --security-opt=no-new-privileges --security-opt=label=disable
    --device "$VIDEO:$VIDEO:rwm" --device "$USB:$USB:rwm"
    --volume "$DATA:/data:rw" --env "CANON_STUDIO_PORT=$PORT"
    --env "CANON_STUDIO_VIDEO_DEVICE=$VIDEO" --stop-timeout=30)
  local pulse=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/pulse/native
  if [[ ${CANON_STUDIO_MICROPHONE:-auto} != off && -S $pulse ]]; then
    args+=(--volume "$pulse:/run/pulse/native:ro" --env PULSE_SERVER=unix:/run/pulse/native)
  fi
  if exists; then
    podman rm "$NAME" >/dev/null
  fi
  podman run "${args[@]}" "$IMAGE"
  ready
  printf 'Canon Studio: http://127.0.0.1:%s\nCaptures: %s/captures\n' "$PORT" "$DATA"
}
case ${1:-help} in
  build) podman build --file "$ROOT/Containerfile" --tag "$IMAGE" "$ROOT" ;;
  start) start ;;
  stop) if exists; then managed; podman stop --time 30 "$NAME"; else printf 'Canon Studio is stopped.\n'; fi ;;
  status) if exists; then podman inspect --format '{{.State.Status}}' "$NAME"; else printf 'not created\n'; fi ;;
  logs) podman logs --tail 100 "$NAME" ;;
  open) start; xdg-open "http://127.0.0.1:$PORT" ;;
  *) printf 'Usage: %s {build|start|stop|status|logs|open}\n' "$0"; [[ ${1:-help} == help ]] ;;
esac
