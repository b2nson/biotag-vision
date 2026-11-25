# Cameras

All three cameras feed the same pipeline. Pick one in `jetson/config.yaml`
(`camera.type`) or on the command line (`--camera csi|zed|esp32cam`).

| | Pi Camera (CSI) | ZED 2 | ESP32-CAM |
|---|---|---|---|
| Connection | Ribbon cable to the Jetson | USB 3.0 | Wi-Fi |
| Driver | `jetson/biotag/cameras/csi.py` | `jetson/biotag/cameras/zed.py` | `jetson/biotag/cameras/esp32cam.py` |
| Depth | No | Yes | No |
| "Item present" detection | Background comparison | Distance from the depth map | Background comparison |
| Image quality for small tags | Good | Good | Lowest (JPEG, 800x600) |
| Delay | Lowest | Low | Highest, depends on Wi-Fi |
| Extra software | None | ZED SDK | Flash `camera/esp32cam_stream` |
| Best use | Main camera | When you want depth-based triggering | Cheap second view or wireless demo |

Suggested plan: build around the Pi Camera, show the ZED 2 as the depth-enabled
option, and use the ESP32-CAM to demonstrate a low-cost wireless alternative and
to compare read rates. `jetson/tools/check_camera.py <type>` prints the frame rate and
any tag it reads, which gives you numbers for that comparison.

## Pi Camera on the Jetson Orin Nano

- **Supported sensors:** Pi Camera v2 (IMX219) and Pi HQ Camera (IMX477). The
  Pi Camera v3 (IMX708) is not supported by NVIDIA's standard drivers; use a v2
  unless you want to install a third-party driver.
- **Cable:** the Orin Nano dev kit's camera connectors are the small 22-pin
  type. A Pi camera's standard 15-pin ribbon does not fit; you need a
  15-pin-to-22-pin camera cable (the same kind used for Pi Zero and Pi 5).
- Power off before plugging in. Then:

```bash
sudo /opt/nvidia/jetson-io/jetson-io.py   # Configure CSI connector -> pick IMX219 (or IMX477) -> save, reboot
ls /dev/video*                            # the sensor should be listed
python3 jetson/tools/check_camera.py csi
```

- The driver uses GStreamer (`nvarguscamerasrc`). OpenCV must be the JetPack
  build. If you ran `pip install opencv-python` on the Jetson, uninstall it:
  that version has no GStreamer and the camera will not open.
- `camera.csi.sensor_id` selects CAM0 or CAM1; `flip_method: 2` rotates 180 degrees.

## ZED 2

- Plug into a USB 3.0 port with a USB 3.0 cable.
- Install the ZED SDK build that matches your JetPack version from
  stereolabs.com, then its Python API (the installer offers this; otherwise
  run the SDK's `get_python_api.py`).
- `python3 jetson/tools/check_camera.py zed` prints the frame rate and the distance at
  the centre of the image.
- The depth map is what makes this camera useful here: an item counts as
  "present" when enough of the centre of the view is between
  `presence.depth_min_m` and `presence.depth_max_m` (0.2 m and 0.8 m by
  default). Mount the camera so the background is further away than
  `depth_max_m`, and note that the ZED 2 cannot measure very close objects, so
  items should be held roughly 0.3 m or more away.
- No SDK? Set `camera.zed.use_sdk: false`. The ZED then works as an ordinary
  USB camera (left image only, no depth).

## ESP32-CAM (AI-Thinker)

1. `cd camera/esp32cam_stream`, copy `include/secrets.example.h` to
   `include/secrets.h` and edit it.
2. Flash with an FTDI adapter or an ESP32-CAM-MB board: `pio run -t upload`.
3. Choose a Wi-Fi mode in `secrets.h`:
   - `CAM_AP_MODE 1` (default): the camera creates its own network. Join it
     from the Jetson; the camera is at `http://192.168.4.1`. No router needed,
     which suits a demo room, but the Jetson's Wi-Fi is then not on the internet.
   - `CAM_AP_MODE 0`: the camera joins your network and prints its address on
     the serial monitor. Put that address in `camera.esp32cam.url`.
4. `python3 jetson/tools/check_camera.py esp32cam`

Things to know:
- Open `http://<address>/` in a browser to check it, then close the tab: the
  camera serves one video viewer at a time.
- Power it from a solid 5 V supply. Brown-outs (random resets, striped images)
  are the most common ESP32-CAM problem.
- `http://<address>/led?on=1` switches the on-board LED, usable as a fill light.

## Lighting and mounting (applies to all three)

- Enclose the scan area and light it evenly with diffused white LEDs. Glare on
  shiny packaging is the main cause of unreadable tags.
- Use a plain, matte, fixed background. The Pi Camera and ESP32-CAM detect an
  item by comparing against that background.
- A tag should be at least about 150 pixels wide in the image to read reliably.
  Check with `jetson/tools/check_camera.py` at the distance people will actually hold items.
