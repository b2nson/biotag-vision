# Jetson Orin Nano setup

Assumes JetPack 6 is already flashed (SD card or the NVMe SSD) and the board
boots to a desktop.

## 1. System packages

```bash
sudo apt update
sudo apt install -y python3-pip python3-opencv libzbar0 v4l-utils
sudo usermod -aG dialout $USER     # serial port access; log out and back in
```

Use the system OpenCV (`python3-opencv` / the JetPack build). Do **not**
`pip install opencv-python` on the Jetson: it removes GStreamer support and the
Pi Camera stops working. Check with:

```bash
python3 -c "import cv2; print(cv2.getBuildInformation())" | grep GStreamer   # must say YES
```

## 2. Python packages

```bash
cd biotag/jetson
pip3 install numpy pyserial pyyaml "qrcode[pil]" pytest pyzbar
python3 -m pytest          # should pass on the Jetson too
```

## 3. Vision model (can wait until tag reading works)

The fallback model needs PyTorch with GPU support and Ultralytics. Install the
PyTorch build made for your JetPack version (NVIDIA publishes Jetson wheels;
the Ultralytics "NVIDIA Jetson" guide lists the exact commands), then
`pip3 install ultralytics`. A plain `pip install torch` gives a CPU-only build.

Train elsewhere, export on the Jetson:

```bash
python3 tools/train.py export --weights best.pt     # writes models/biotag.engine
```

Without a model file the application still runs, tag-only, and says so at
start-up and on screen.

## 4. Run

```bash
python3 -m biotag.main                 # uses config.yaml
python3 -m biotag.main --camera zed    # override the camera
python3 -m biotag.main --port /dev/ttyUSB0
```

Press `q` in the window to quit. Every decision is appended to
`logs/decisions.csv`, which is useful data for your report.

## 5. Start automatically at boot (optional)

Edit the paths and user name in `jetson/biotag.service`, then:

```bash
sudo cp biotag.service /etc/systemd/system/
sudo systemctl enable --now biotag
journalctl -u biotag -f                # live log
```

## Performance tips

- Select the highest power mode (MAXN SUPER on the Orin Nano Super) from the
  power menu in the top bar, or list the modes with `sudo nvpmodel -q --verbose`
  and set one with `sudo nvpmodel -m <id>`. `sudo jetson_clocks` pins the
  clocks high.
- Fit the fan and make sure the enclosure has airflow.
