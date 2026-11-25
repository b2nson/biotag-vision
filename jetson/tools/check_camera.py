#!/usr/bin/env python3
"""Check one camera on its own and report frame rate and tag reads.

    python3 tools/check_camera.py csi
    python3 tools/check_camera.py zed
    python3 tools/check_camera.py esp32cam --save shot.jpg --headless
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from biotag import config as config_mod  # noqa: E402
from biotag.cameras import create_camera  # noqa: E402
from biotag.tag_reader import TagReader  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("camera", choices=["csi", "zed", "esp32cam", "usb", "mock"])
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--seconds", type=float, default=0, help="stop after N seconds (0 = until q)")
    ap.add_argument("--save", help="write one frame to this file and exit")
    ap.add_argument("--headless", action="store_true")
    args = ap.parse_args()

    cfg = config_mod.load(args.config if Path(args.config).exists() else None)
    cfg["camera"]["type"] = args.camera
    reader = TagReader()
    frames, t0, last = 0, time.monotonic(), None
    with create_camera(cfg, cfg["_dir"]) as cam:
        while True:
            frame = cam.read()
            if frame is None:
                time.sleep(0.005)
                continue
            if last is not None and frame.timestamp == last:
                time.sleep(0.002)          # same frame again (ESP32-CAM is slower than us)
                continue
            last = frame.timestamp
            frames += 1
            if args.save:
                cv2.imwrite(args.save, frame.image)
                print(f"saved {args.save} {frame.image.shape[1]}x{frame.image.shape[0]}")
                return
            read = reader.read(frame.image)
            elapsed = time.monotonic() - t0
            if frames % 30 == 0:
                depth = ""
                if frame.depth is not None:
                    h, w = frame.depth.shape[:2]
                    centre = frame.depth[h // 2, w // 2]
                    depth = f"  centre depth {centre:.2f} m" if np.isfinite(centre) else "  centre depth n/a"
                tag = read.tag.raw if read.tag else ("(damaged tag)" if read.damaged else "-")
                print(f"{frames / elapsed:5.1f} fps  tag: {tag}{depth}")
            if not args.headless:
                cv2.imshow("camera test (q quits)", frame.image)
                if (cv2.waitKey(1) & 0xFF) == ord("q"):
                    break
            if args.seconds and elapsed > args.seconds:
                break
    print(f"{frames} frames in {time.monotonic() - t0:.1f} s")


if __name__ == "__main__":
    main()
