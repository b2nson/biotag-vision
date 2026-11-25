# BioTag Smart Bin

A camera reads the BioTag sticker on an item, a screen shows the material and
which bin it belongs in (Recycle, Compost or Landfill), and the matching lid
opens. When the item has been dropped in, the lid closes.

If the sticker is damaged, covered or missing, a vision model identifies the
item itself. If neither works, the item goes to landfill ("when in doubt, throw
it out").

```
 Pi Camera (CSI) ─┐
 ZED 2 (USB 3.0) ─┼─► Jetson Orin Nano ──UART or USB──► ESP32 ──► 3 lid servos
 ESP32-CAM (Wi-Fi)┘    tag reader + YOLO                  ▲
                       decision logic, screen             └── 3 break-beam sensors
```

The Jetson does the vision and decides. The ESP32 does the real-time work
(servo motion, sensors, closing safely) so a slow frame never stalls a lid.

## Folder layout

`jetson/` (this folder) is the Jetson app. `camera/` holds the ESP32-CAM firmware and camera setup guide. `bin_controller/` holds the lid-controller firmware and wiring. Paths below are from the repo root unless they start with `jetson/`.

| Path | What it is |
|---|---|
| `jetson/biotag/` | Jetson application (Python) |
| `jetson/biotag/cameras/` | Drivers: `csi.py` (Pi Camera), `zed.py` (ZED 2), `esp32cam.py`, plus USB and mock |
| `jetson/biotag/esp32_link.py` | Jetson side of the Jetson-ESP32 connection |
| `jetson/tools/` | Tag generator, camera check, link check, ESP32 simulator, training, robustness test |
| `jetson/tests/` | 47 automated tests, no hardware needed |
| `bin_controller/` | ESP32 firmware: lids, sensors, protocol (PlatformIO), plus `wiring.md` |
| `camera/` | `esp32cam_stream/` firmware (MJPEG over Wi-Fi) and `README.md` camera setup |
| `jetson/docs/` | Jetson setup and the Jetson-ESP32 protocol |

## Try it in five minutes, with no hardware

On any Linux or macOS laptop:

```bash
cd jetson
pip install opencv-python numpy pyserial pyyaml "qrcode[pil]" pytest pyzbar
python3 -m pytest                      # everything should pass
python3 tools/esp32_sim.py             # terminal 1: prints a port like /dev/pts/5
python3 -m biotag.main --camera mock --port /dev/pts/5    # terminal 2
```

The mock camera plays the frames in `jetson/samples/`; you will see each tag
read, the lid command sent, and the simulated lid close.

## Build order on the real hardware

1. **Jetson setup** - `jetson/docs/setup_jetson.md`
2. **Flash the ESP32** - `cd bin_controller && pio run -t upload`
3. **Wire it** - `bin_controller/wiring.md`
4. **Check the link** - `python3 tools/check_link.py` (cycles each lid)
5. **Check a camera** - `python3 tools/check_camera.py csi` (or `zed`, `esp32cam`) - `camera/README.md`
6. **Print tags** - `python3 tools/generate_tags.py --demo`
7. **Run** - `python3 -m biotag.main` (camera is chosen in `config.yaml`)
8. **Add the vision fallback** - `tools/train.py`, then put the model at `jetson/models/biotag.engine`

## What has and has not been tested

This code was written without access to the hardware. Be clear about that when
you present it.

**Tested (automated, in `jetson/tests/`):**
- Tag encode/decode, including faded tags; rejection of non-BioTag QR codes
- Decision logic: tag priority, vision voting, contamination, unsure-to-landfill
- Serial link: handshake, retries after a lost frame, busy, timeouts, missing port
- The whole application loop with a mock camera and a simulated ESP32
- The real lid-controller firmware source, compiled for a PC with simulated
  time: protocol, deposit, timeout, one-lid-at-a-time, re-open when a hand is
  in the way

**Not tested - needs the real parts:**
- The firmware has not been compiled for an ESP32 (PlatformIO could not be
  downloaded where this was written). Expect to fix small build errors.
- The ESP32-CAM firmware has not been compiled or run at all.
- The Pi Camera, ZED 2 and ESP32-CAM drivers have never seen a real camera.
- Servo angles, pins and timings are starting values.

**Assumptions to confirm with the team:**
- The BioTag sticker is treated as a QR code containing `BT1:<id>:<material>:<bin>`.
  If Benson's BioTag uses a different code or app, change `parse_payload` and
  `TagReader._decode` in `jetson/biotag/tag_reader.py`; nothing else depends on it.
- No trained vision model is included. Until you train one the system runs
  tag-only and sends anything untagged to landfill after 3 seconds.

## Tag robustness (synthetic bench test)

`python3 tools/eval_tag_robustness.py --trials 30` damages a tag in software
and reports how often it still decodes, without and with image enhancement:

| Damage | 25% | 50% | 75% | 100% |
|---|---|---|---|---|
| Faded print | 100 / 100 | 100 / 100 | 100 / 100 | 100 / 100 |
| Blurred | 100 / 100 | 100 / 100 | 100 / 100 | 93 / 100 |
| Coffee-type stains | 93 / 100 | 50 / 100 | 23 / 97 | 3 / 87 |
| Opaque cover (strip up to half the tag) | 20 / 30 | 0 / 0 | 0 / 0 | 0 / 0 |
| Torn corner (up to 60% of the width) | 100 / 100 | 100 / 100 | 0 / 0 | 0 / 0 |

Percent decoded, plain / enhanced, with `pyzbar` installed. These are computer
generated images, so treat them as a guide to what to measure on real worn
stickers. The pattern is the useful part: fading, blur and stains are
recoverable; an opaque cover or a large tear is not, and that is exactly where
the vision fallback has to take over.
