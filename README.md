# Canon Studio

A local Linux webcam studio for the Canon EOS Rebel T2i / EOS 550D. Preview a USB live-view feed, save webcam photos, record video, and adjust camera settings in your browser.

Built with Python's standard library, libgphoto2, FFmpeg, and v4l2loopback. No Python packages or cloud account are required. This is an independent project, not affiliated with Canon.

Use **Quit Canon Studio** in the UI to save any active recording, release the camera, and stop the service/container. Reopen it from the application menu to start again. **Stop camera** only stops the camera feed.

## Features

- Live preview and a virtual webcam for calling and streaming apps.
- JPEG snapshots, MP4 recording, optional microphone audio, and a local capture gallery.
- Preview mirror and composition grid.
- Autofocus on demand, near/far focus steps, and adjustable periodic refocusing.
- Camera-reported white balance, exposure compensation, ISO, aperture, and shutter controls; Manual exposure mode unlocks supported manual settings.

The original setup was tested on Bazzite with an EOS 550D / Rebel T2i and Canon 18–55 mm lens, producing a clean 1056 × 704 USB preview. Other bodies and lenses are unverified. Snapshots come from the webcam feed, not the camera's full-resolution still sensor output.

## Requirements

For native installation, run on a Linux desktop with Python 3, a working systemd user session, libgphoto2, FFmpeg, and a writable v4l2loopback device. For Bazzite, the rootless Podman setup below supplies the camera and media dependencies in a container. Recording requires FFmpeg's `libx264` encoder; microphone recording also requires its PulseAudio input support (including PipeWire's PulseAudio compatibility service).

For Ubuntu/Debian, the usual dependencies are:

```bash
sudo apt install python3 libgphoto2-6 gphoto2 ffmpeg v4l-utils v4l2loopback-dkms linux-headers-$(uname -r)
```

The kernel module must match your running kernel; Secure Boot may require module signing. See the [Ubuntu v4l2loopback package](https://packages.ubuntu.com/v4l2loopback-dkms) and [upstream module instructions](https://github.com/v4l2loopback/v4l2loopback).

On Fedora, the camera library is packaged as [libgphoto2](https://packages.fedoraproject.org/pkgs/libgphoto2/libgphoto2/). Install FFmpeg with `libx264` support and v4l2loopback through your distribution's supported method. Fedora's [ffmpeg-free package](https://packages.fedoraproject.org/pkgs/ffmpeg/ffmpeg-free/) alone may not provide the required encoder. Bazzite and other immutable distributions can have these components already installed; check before changing the host. A container's installed packages do not establish host USB or kernel-module access.

## Start

Clone the source:

```bash
git clone https://github.com/grantnegri/canon-studio.git
cd canon-studio
```

1. Connect the camera by **USB data cable**, turn it on, remove the lens cap, and set the lens switch to **AF** for software focus controls. HDMI is unnecessary. Close other camera applications and release any file-manager camera mount.
2. Identify your virtual camera with `v4l2-ctl --list-devices`. Use an existing v4l2loopback device if available. Do not select a physical webcam or capture card as the output device.
3. If no loopback device exists and the module is installed, choose an unused video number. For example, after confirming `/dev/video10` is unused:

   ```bash
   sudo modprobe v4l2loopback video_nr=10 card_label="Canon Studio" exclusive_caps=1
   ```

   If the module is already loaded, this command does not reconfigure its devices; use its existing loopback device instead. Do not unload a module serving another application.
4. From this checkout, run:

   ```bash
   export CANON_STUDIO_VIDEO_DEVICE=/dev/video10
   bash launch.sh
   ```

5. Open [Canon Studio](http://127.0.0.1:8784), click **Start camera**, and select the virtual camera in your calling app. Choose a microphone separately.

Run the app as your normal desktop user, never with `sudo`. That user needs USB camera access and read/write access to the selected video device; use your distribution's udev/session permissions if access is denied.

To add an application-menu entry, use the same environment settings and run:

```bash
bash install-desktop.sh
```

The command-line webcam controls are also available:

```bash
bash webcam.sh start
bash webcam.sh status
bash webcam.sh stop
```

## Bazzite: rootless Podman

Run these commands on the **Bazzite host**, as your desktop user, from the source checkout. Podman and host Python 3 are required. The container supplies libgphoto2 and FFmpeg, including recording support; it does not require systemd inside the container.

A writable **host v4l2loopback device is still required**: containers cannot supply or load the running host kernel's module. Use the device discovery and module-loading guidance above. Connect and power on the USB camera, then substitute your confirmed loopback device:

```bash
export CANON_STUDIO_VIDEO_DEVICE=/dev/video10
./podman.sh build
./podman.sh open
```

Click **Start camera** in the UI. `open` starts the container and opens the browser; `start` starts it without opening a browser. The script validates that the selected video device uses v4l2loopback and discovers the connected EOS 550D / T2i by USB identity. Native `canon-studio.service` or `canon-webcam.service` sessions must be stopped first, after finishing any recording:

```bash
systemctl --user stop canon-studio.service canon-webcam.service
```

Manage the container and optionally install an application-menu entry with the same environment settings:

```bash
./podman.sh status
./podman.sh logs
./podman.sh stop
./install-container-desktop.sh
```

Captures persist in the configured host data directory across container replacement. After unplugging, reconnecting, or power-cycling the camera, run `./podman.sh stop` followed by `./podman.sh start` to rediscover its USB address. Rebuild with `./podman.sh build` after updating the checkout, then stop/start to use the new image.

Only the selected video and USB device nodes are passed through. The rootless container preserves your user ID and supplementary device-access groups (Podman's `crun` runtime supports `keep-groups`), drops capabilities, and uses no privileged mode. Host networking lets the server remain bound to `127.0.0.1`; the UI stays at [localhost:8784](http://127.0.0.1:8784). SELinux container labeling is disabled for this container to allow access to the selected devices and optional audio socket; ordinary host user permissions still apply.

Microphone recording uses the desktop's PulseAudio/PipeWire socket when available. Set `CANON_STUDIO_MICROPHONE=off` to omit audio socket access; the preview, photos, and silent recording still work. Select microphone recording in the UI only when audio is available.

Additional container settings:

| Variable | Default | Purpose |
| --- | --- | --- |
| `CANON_STUDIO_USB_DEVICE` | Auto-discover EOS 550D / T2i | Explicit `/dev/bus/usb/BBB/DDD` for another Canon body or multiple cameras; the script verifies Canon USB identity. Other bodies remain unverified, and this address changes after reconnecting. |
| `CANON_STUDIO_MICROPHONE` | `auto` | Use an available desktop audio socket; `off` disables passthrough. |
| `CANON_STUDIO_IMAGE` | `localhost/canon-studio:latest` | Locally built image name. |
| `CANON_STUDIO_CONTAINER` | `canon-studio` | Container name. |

The desktop installer preserves these settings and the common settings below. Build the image before launching from the application menu. The image is built locally; no publishing or registry account is needed.

## Configuration and files

Set environment variables before launching or installing the desktop entry:

| Variable | Default | Purpose |
| --- | --- | --- |
| `CANON_STUDIO_VIDEO_DEVICE` | `/dev/video0` | Existing v4l2loopback output; override unless video0 is confirmed to be a loopback device. |
| `CANON_STUDIO_PORT` | `8784` | Local web interface port. |
| `CANON_STUDIO_DATA_DIR` | `$XDG_DATA_HOME/canon-studio`, or `~/.local/share/canon-studio` | Captures and application logs. |

Photos and recordings are stored in the data directory's `captures/` folder, outside the source checkout. Keep these files private unless you intend to share them.

The web interface is bound to loopback for local use. It is not a remotely authenticated service; do not expose it through a reverse proxy, port forwarding, or a public tunnel.

## Camera behavior and troubleshooting

- **Focus:** periodic refocus sends discrete autofocus requests. It is not continuous subject tracking and can visibly hunt. Use Live or Live Face autofocus; Quick AF interrupts live view. Lens AF/MF selection, power, and optical zoom still require physical controls.
- **Unavailable settings:** controls depend on the body, lens, and exposure mode. Try Manual exposure mode for ISO, shutter, and aperture. Some changes can briefly interrupt the preview.
- **Busy or missing camera:** close other camera tools, release any camera mount, and check the USB data cable and power. Avoid running a separate gphoto2 control process while streaming; the bridge owns the USB session and serializes commands.
- **Timeout after reconnecting:** stop the camera in the UI, power-cycle it, and start again. Review the data-directory logs if the problem persists.
- **No webcam in another app:** start the feed first, then reopen that app's camera picker. Confirm that its device selection matches `CANON_STUDIO_VIDEO_DEVICE`.
- **Recording fails:** check that `ffmpeg -encoders` lists `libx264`. For audio, check the desktop's default microphone and FFmpeg PulseAudio support.

## Development

The browser UI is in `index.html`, HTTP and capture handling in `server.py`, and serialized libgphoto2 access in `camera_bridge.py`. The bridge uses Python `ctypes`; the camera library and media tools are installed separately under their own licenses.

```bash
python3 -m unittest discover -s tests -v
```

Tests cover software behavior; actual camera compatibility needs a hardware check. See [CONTRIBUTING.md](CONTRIBUTING.md) for reporting results and proposing changes.

## License

[MIT](LICENSE). Dependencies retain their respective licenses.
