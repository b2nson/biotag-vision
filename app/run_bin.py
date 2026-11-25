#!/usr/bin/env python3
"""
BioTag smart-bin runtime for the Jetson Orin Nano

Pipeline per frame:
  camera -> YOLO26 detector (find tag + condition)
         -> try to decode the tag (QR / Data Matrix)     -> "TAG" decision
         -> else small classifier reads the tag crop     -> "AI" decision
         -> else / low confidence                        -> LANDFILL ("when in doubt, throw it out")
  -> show everything on the screen
  -> send one byte to the ESP32 ('R' recycle, 'C' compost, 'T' trash/landfill) to open the lid
  -> append the event to logs/scan_events.csv

Run (on the Jetson, after export_trt.py):
  python app/run_bin.py --det models/biotag_det.engine --cls models/biotag_cls.engine --fullscreen
  python app/run_bin.py ... --serial /dev/ttyUSB0            # drive the ESP32
  python app/run_bin.py ... --serial /dev/ttyUSB0 --trigger  # only decide when the ESP32 says the beam broke
Test on a laptop with the .pt files and a video/image instead of a camera:
  python app/run_bin.py --det models/biotag_det.pt --cls models/biotag_cls.pt --source test.mp4
Keys: q / Esc quit, r reset counters, f toggle fullscreen.
"""
import argparse
import csv
import time
from collections import Counter, deque
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO

CONDITIONS = ["clean", "occluded", "stained", "damaged"]
# BGR colours for the screen
BIN_COLORS = {"recycle": (200, 120, 30), "compost": (60, 160, 60), "landfill": (110, 110, 110)}
BIN_BYTES = {"recycle": b"R", "compost": b"C", "landfill": b"T"}


# ----------------------------------------------------------------- helpers
def open_source(src, width, height, fps):
    if src.isdigit():
        cap = cv2.VideoCapture(int(src), cv2.CAP_V4L2)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))  # Arducam USB: MJPG for full fps
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        cap.set(cv2.CAP_PROP_FPS, fps)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap, False
    p = Path(src)
    if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp"}:
        return cv2.imread(str(p)), True
    return cv2.VideoCapture(src), False


def decode_tag(crop, qr):
    """Try to read a printed code on the tag. Returns the text or None."""
    if crop.size == 0:
        return None
    h, w = crop.shape[:2]
    if max(h, w) < 300:  # small crops decode better when upscaled
        s = 300 / max(h, w)
        crop = cv2.resize(crop, (int(w * s), int(h * s)), interpolation=cv2.INTER_CUBIC)
    try:
        text, pts, _ = qr.detectAndDecode(crop)
        return text or None
    except cv2.error:
        return None


def bin_from_payload(payload, bins):
    """Map decoded tag text to a bin. Suggested tag format: BIOTAG:RECYCLE:<product_id>."""
    up = payload.upper()
    for b in bins:
        if b.upper() in up:
            return b
    for b in bins:  # single-letter form, e.g. BIOTAG:R:000123
        if f":{BIN_BYTES.get(b, b[:1].encode()).decode()}:" in up:
            return b
    return None


def bin_color(b):
    return BIN_COLORS.get(b, (180, 120, 200))


class Serial:
    def __init__(self, port, baud):
        self.s = None
        if port:
            import serial  # pyserial
            self.s = serial.Serial(port, baud, timeout=0)
            print(f"serial open: {port} @ {baud}")

    def send_bin(self, b, counts):
        if self.s:
            self.s.write(BIN_BYTES.get(b, b"T"))
            # stats line for the ESP32's TFT screen
            self.s.write(f"\nS,{counts.get('recycle', 0)},{counts.get('compost', 0)},{counts.get('landfill', 0)}\n".encode())

    def beam_broken(self):
        if not self.s:
            return False
        data = self.s.read(64)
        return b"B" in data


# ------------------------------------------------------------------ screen
def draw(frame, dets, state, counts, fps, canvas_size=(1280, 720)):
    W, H = canvas_size
    panel_w = 340
    vid_w = W - panel_w
    canvas = np.full((H, W, 3), 28, np.uint8)

    # video + boxes
    fh, fw = frame.shape[:2]
    s = min(vid_w / fw, H / fh)
    vw, vh = int(fw * s), int(fh * s)
    vid = cv2.resize(frame, (vw, vh))
    for d in dets:
        x1, y1, x2, y2 = [int(v * s) for v in d["box"]]
        col = bin_color(d.get("bin", "landfill"))
        cv2.rectangle(vid, (x1, y1), (x2, y2), col, 3)
        label = f"{d['cond']} {d['conf']:.2f}"
        if d.get("bin"):
            label += f" -> {d['bin'].upper()} ({d['src']} {d['bin_conf']:.2f})"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
        cv2.rectangle(vid, (x1, max(0, y1 - th - 8)), (x1 + tw + 6, y1), col, -1)
        cv2.putText(vid, label, (x1 + 3, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)
    oy, ox = (H - vh) // 2, (vid_w - vw) // 2
    canvas[oy:oy + vh, ox:ox + vw] = vid

    # side panel
    x0 = vid_w + 20
    cv2.putText(canvas, "BioTag Smart Bin", (x0, 45), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (240, 240, 240), 2)
    cur = state.get("banner_bin")
    box_col = bin_color(cur) if cur else (60, 60, 60)
    cv2.rectangle(canvas, (x0, 70), (W - 20, 230), box_col, -1)
    big = cur.upper() if cur else "READY"
    (tw, _), _ = cv2.getTextSize(big, cv2.FONT_HERSHEY_DUPLEX, 1.4, 3)
    cv2.putText(canvas, big, (x0 + (panel_w - 40 - tw) // 2, 150), cv2.FONT_HERSHEY_DUPLEX, 1.4, (255, 255, 255), 3)
    sub = state.get("banner_sub", "Place item under the camera")
    cv2.putText(canvas, sub, (x0 + 12, 205), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

    y = 275
    for line in state.get("info", []):
        cv2.putText(canvas, line, (x0, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (210, 210, 210), 1)
        y += 26

    y = H - 150
    cv2.putText(canvas, "Sorted this session", (x0, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (240, 240, 240), 1)
    for b in ("recycle", "compost", "landfill"):
        y += 32
        cv2.rectangle(canvas, (x0, y - 18), (x0 + 18, y), bin_color(b), -1)
        cv2.putText(canvas, f"{b.capitalize():<9} {counts.get(b, 0)}", (x0 + 30, y - 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (240, 240, 240), 2)
    cv2.putText(canvas, f"{fps:4.1f} FPS", (W - 110, H - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (150, 150, 150), 1)
    return canvas


# -------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--det", default="models/biotag_det.engine")
    ap.add_argument("--cls", default="models/biotag_cls.engine")
    ap.add_argument("--bins", default="models/bins.txt")
    ap.add_argument("--source", default="0", help="camera index, video file, or image")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=800)
    ap.add_argument("--fps", type=int, default=60)
    ap.add_argument("--det-imgsz", type=int, default=640)
    ap.add_argument("--cls-imgsz", type=int, default=224)
    ap.add_argument("--det-conf", type=float, default=0.40)
    ap.add_argument("--cls-conf", type=float, default=0.65, help="below this the AI read is 'unsure' -> landfill")
    ap.add_argument("--stable", type=int, default=5, help="frames a decision must hold before sorting")
    ap.add_argument("--no-decode", action="store_true", help="skip QR decoding, always use the classifier")
    ap.add_argument("--serial", default=None, help="ESP32 port, e.g. /dev/ttyUSB0 or /dev/ttyACM0")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--trigger", action="store_true", help="decide only after the ESP32 sends 'B' (beam broken)")
    ap.add_argument("--fullscreen", action="store_true")
    ap.add_argument("--no-display", action="store_true")
    ap.add_argument("--max-frames", type=int, default=0, help="stop after N frames (testing)")
    ap.add_argument("--log", default="logs/scan_events.csv")
    args = ap.parse_args()

    bins = Path(args.bins).read_text().split() if Path(args.bins).exists() else ["compost", "landfill", "recycle"]
    det = YOLO(args.det, task="detect")
    cls = YOLO(args.cls, task="classify")
    qr = cv2.QRCodeDetector()
    ser = Serial(args.serial, args.baud)

    Path(args.log).parent.mkdir(parents=True, exist_ok=True)
    new_log = not Path(args.log).exists()
    logf = open(args.log, "a", newline="")
    log = csv.writer(logf)
    if new_log:
        log.writerow(["timestamp", "bin", "source", "confidence", "tag_condition", "det_conf", "payload"])

    cap, still = open_source(args.source, args.width, args.height, args.fps)
    if not still and not cap.isOpened():
        raise SystemExit(f"Could not open source {args.source}")

    win = "BioTag"
    if not args.no_display:
        cv2.namedWindow(win, cv2.WINDOW_NORMAL)
        if args.fullscreen:
            cv2.setWindowProperty(win, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

    counts = Counter()
    history = deque(maxlen=args.stable)
    state = {}
    armed = True          # must see "no tag" before the next item is counted
    empty_frames = 0
    banner_until = 0.0
    trigger_until = 0.0
    trigger_votes = []
    t_prev, fps, n = time.time(), 0.0, 0

    while True:
        frame = cap.copy() if still else cap.read()[1]
        if frame is None:
            break
        n += 1

        # ---- detect
        r = det.predict(frame, imgsz=args.det_imgsz, conf=args.det_conf, verbose=False)[0]
        dets = []
        for b, c, k in zip(r.boxes.xyxy.cpu().numpy(), r.boxes.conf.cpu().numpy(), r.boxes.cls.cpu().numpy()):
            dets.append({"box": b.tolist(), "conf": float(c), "cond": CONDITIONS[int(k)] if int(k) < 4 else str(int(k))})
        dets.sort(key=lambda d: d["conf"], reverse=True)

        # ---- read the best tag
        decision = None
        if dets:
            d = dets[0]
            x1, y1, x2, y2 = map(int, d["box"])
            pad = int(0.08 * max(x2 - x1, y2 - y1))
            crop = frame[max(0, y1 - pad):y2 + pad, max(0, x1 - pad):x2 + pad]
            payload = None if args.no_decode else decode_tag(crop, qr)
            tag_bin = bin_from_payload(payload, bins) if payload else None
            if tag_bin:
                d.update(bin=tag_bin, src="TAG", bin_conf=1.0, payload=payload)
            else:
                p = cls.predict(crop, imgsz=args.cls_imgsz, verbose=False)[0].probs
                name = cls.names[int(p.top1)]
                conf = float(p.top1conf)
                if conf >= args.cls_conf:
                    d.update(bin=name, src="AI", bin_conf=conf, payload="")
                else:
                    d.update(bin="landfill", src="UNSURE", bin_conf=conf, payload="")
            decision = (d["bin"], d["src"], d["bin_conf"], d["cond"], d["conf"], d.get("payload", ""))

        # ---- decide when to actually sort
        now = time.time()
        commit = None
        if args.trigger:
            if ser.beam_broken():
                trigger_until, trigger_votes = now + 0.6, []
            if trigger_until:
                if decision:
                    trigger_votes.append(decision)
                if now >= trigger_until:
                    if trigger_votes:
                        top = Counter(v[0] for v in trigger_votes).most_common(1)[0][0]
                        commit = max((v for v in trigger_votes if v[0] == top), key=lambda v: v[2])
                    else:
                        commit = ("landfill", "NO_TAG", 0.0, "-", 0.0, "")
                    trigger_until = 0.0
        else:
            if decision:
                empty_frames = 0
                history.append(decision[0])
                if armed and len(history) == args.stable and len(set(history)) == 1:
                    commit, armed = decision, False
            else:
                empty_frames += 1
                history.clear()
                if empty_frames >= 8:
                    armed = True

        if commit:
            b, src, conf, cond, dconf, payload = commit
            counts[b] += 1
            ser.send_bin(b, counts)
            log.writerow([datetime.now().isoformat(timespec="seconds"), b, src, f"{conf:.3f}", cond, f"{dconf:.3f}", payload])
            logf.flush()
            state["banner_bin"] = b
            state["banner_sub"] = {"TAG": "Read from BioTag", "AI": "Read by AI (tag unreadable)",
                                   "UNSURE": "Unsure: when in doubt, landfill",
                                   "NO_TAG": "No tag found"}.get(src, src)
            banner_until = now + 2.0
            print(f"[sorted] {b:<9} via {src:<6} conf={conf:.2f} tag={cond}")
        elif now > banner_until:
            state.pop("banner_bin", None)
            state["banner_sub"] = "Place item under the camera"

        if decision:
            b, src, conf, cond, dconf, payload = decision
            state["info"] = [f"Tag found: {dconf:.0%}", f"Condition: {cond}", f"Read by: {src}",
                             f"Bin guess: {b} ({conf:.0%})"] + ([f"Code: {payload[:24]}"] if payload else [])
        else:
            state["info"] = ["No BioTag in view"]

        dt = time.time() - t_prev
        t_prev = time.time()
        fps = 0.9 * fps + 0.1 * (1.0 / max(dt, 1e-6)) if fps else 1.0 / max(dt, 1e-6)

        if not args.no_display:
            cv2.imshow(win, draw(frame, dets[:3], state, counts, fps))
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord("r"):
                counts.clear()
            if key == ord("f"):
                full = cv2.getWindowProperty(win, cv2.WND_PROP_FULLSCREEN) == cv2.WINDOW_FULLSCREEN
                cv2.setWindowProperty(win, cv2.WND_PROP_FULLSCREEN,
                                      cv2.WINDOW_NORMAL if full else cv2.WINDOW_FULLSCREEN)
        elif n % 30 == 0:
            print(f"{fps:5.1f} FPS  {state['info'][0]}")
        if args.max_frames and n >= args.max_frames:
            break

    if not args.no_display:
        cv2.destroyAllWindows()
    logf.close()
    print(f"session totals: {dict(counts)}")


if __name__ == "__main__":
    main()
