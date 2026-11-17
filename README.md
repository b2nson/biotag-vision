# BioTag Vision: YOLO26 + tag reader on the Jetson Orin Nano

Finds BioTag stickers on trash, works out which bin they belong in even when the
tag is **covered, stained or damaged**, shows the result on a screen, and tells
the ESP32 which lid to open.

```
camera ─► YOLO26 detector ─► tag found? condition = clean / occluded / stained / damaged
                 │
                 ├─► decode the printed code (QR)        ─► bin    "TAG"   (exact)
                 ├─► else small classifier reads the crop ─► bin    "AI"    (conf ≥ 0.65)
                 └─► else                                  ─► LANDFILL "UNSURE" (WM: when in doubt, throw it out)
                                   │
                    screen  ◄──────┼──────►  ESP32: 'R' / 'C' / 'T'  ─► servo opens lid
                                   └──────►  logs/scan_events.csv (feeds the database / LCD stats)
```

Two networks:

| Model | Job | Default | Size |
|---|---|---|---|
| Detector `biotag_det` | Find the tag, label its condition | `yolo26s.pt` (use `yolo26n.pt` if you need more FPS, `yolo26m.pt` for accuracy) | small |
| Reader `biotag_cls` | Read the tag crop → recycle / compost / landfill | `yolo26n-cls.pt` (`yolo26s-cls.pt` for medium) | small |

## Folder layout

```
assets/stickers/<bin>/   photos or scans of each BioTag design, one folder per bin (folder name = bin name)
assets/backgrounds/      photos of packaging, tables, bins, hands-free scenes WITHOUT BioTags
assets/distractors/      (optional) other labels/logos that are NOT BioTags: recycling symbols, brand labels
data/                    generated datasets (created by the scripts)
data/real/               your hand-labeled real photos (YOLO format), merged in automatically
models/                  trained weights (.pt) and Jetson engines (.engine)
app/run_bin.py           the runtime that drives the screen and the ESP32
esp32/bin_controller/    reference ESP32 sketch for the serial protocol
```

## 1. Set up the Jetson Orin Nano (once)

1. Flash JetPack following NVIDIA's Orin Nano quick start (JetPack 7.2 now installs from a USB ISO; JetPack 6.x also works).
2. Set the power mode to **MAXN SUPER** (power menu, top right) and run `sudo jetson_clocks`.
3. Install Ultralytics. Easiest is the official Docker image, which already has CUDA, TensorRT and PyTorch:
   ```bash
   t=ultralytics/ultralytics:latest-jetson-jetpack6     # check docs.ultralytics.com/guides/nvidia-jetson for the JetPack 7 tag
   sudo docker pull $t
   sudo docker run -it --ipc=host --runtime=nvidia --device /dev/video0 --device /dev/ttyUSB0 \
        -e DISPLAY=$DISPLAY -v /tmp/.X11-unix:/tmp/.X11-unix -v ~/biotag-vision:/biotag $t
   pip install pyserial
   ```
   (Do **not** `pip install torch` from PyPI on the Jetson; it has no GPU support there.)
4. Plug in the Arducam USB camera and a monitor (DisplayPort on the dev kit).

## 2. Make the training data

```bash
pip install -r requirements.txt                  # on the training PC
python scripts/make_demo_stickers.py             # placeholder tags, ONLY until you have real ones
python scripts/make_synthetic.py --n 4000        # -> data/det (detector) and data/cls (reader)
```

What it simulates: coffee/coffee rings, grease, food and dirt stains; tears,
scratches, fading, crumpling and peeling corners; tape, another label or an
object covering 20–60% of the tag; plus blur, glare, low light and JPEG noise.

To get good results:
- Replace the demo stickers with **5–10 clean photos of each real BioTag design** in `assets/stickers/<bin>/` (crop tight, PNG with transparency is best).
- Put **200+ background photos** in `assets/backgrounds/` (take them with the Arducam at the bin, plus TACO / TrashNet images).
- Synthetic data gets you started. **Real photos are what make it work in the bin**: take 200–500 photos of real tagged items in each condition (actually spill coffee on them, tear them, cover them), label them in Roboflow with the same four class names *in the same order*, export YOLO format into `data/real/`. Keep ~50 real photos per condition aside as the test set you report in the demo.

## 3. Train

Train on a PC with an NVIDIA GPU or Google Colab (fastest). The Orin Nano can also train small models; use `--batch 4`–`8` and expect it to be slow.

```bash
python scripts/train_detector.py                 # yolo26s, 100 epochs -> models/biotag_det.pt
python scripts/train_classifier.py               # yolo26n-cls, 60 epochs -> models/biotag_cls.pt + models/bins.txt
```

Look at `runs/.../confusion_matrix.png` and the per-class mAP lines: the
**occluded / stained / damaged** rows are the edge cases Dr. Lee asked about.

## 4. Convert to TensorRT (on the Jetson)

Copy `models/` to the Jetson, then:
```bash
python scripts/export_trt.py                     # FP16 engines: models/biotag_det.engine, models/biotag_cls.engine
```
Engines only run on the Jetson/TensorRT version that built them, so always export on the Nano itself.

## 5. Run it on the screen

```bash
python app/run_bin.py --fullscreen                                   # camera 0, screen only
python app/run_bin.py --fullscreen --serial /dev/ttyUSB0             # + open lids via ESP32
python app/run_bin.py --fullscreen --serial /dev/ttyUSB0 --trigger   # decide only when the break-beam fires
```
Keys: `q` quit, `r` reset counters, `f` fullscreen. Every sort is appended to `logs/scan_events.csv`.

Useful knobs: `--cls-conf` (raise it to send more unsure items to landfill), `--stable` (frames a decision must hold), `--det-conf`, `--no-decode` (test the AI path alone).

## Tag code format

`app/run_bin.py` reads QR codes and looks for the bin name in the text, e.g. `BIOTAG:RECYCLE:000123` or `BIOTAG:R:000123`. If the real BioTag uses a different code or none, the reader network still works; adjust `bin_from_payload()` for your format.

## ESP32 serial protocol

| Direction | Message | Meaning |
|---|---|---|
| Jetson → ESP32 | `R` / `C` / `T` | open recycle / compost / trash lid |
| Jetson → ESP32 | `S,<r>,<c>,<l>\n` | running counts for the TFT |
| ESP32 → Jetson | `B\n` | break-beam interrupted (item dropped in) |

## Licence note
Ultralytics YOLO is AGPL-3.0: fine for a class project and open-source code. Commercialising BioTag later would need an Ultralytics enterprise licence or a different model.
