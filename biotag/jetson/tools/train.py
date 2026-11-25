#!/usr/bin/env python3
"""Train the vision-fallback model and export it for the Jetson.

Train on a PC/laptop GPU or Colab (faster), then export ON THE JETSON, because
a TensorRT engine only runs on the kind of device that built it.

  # 1. train (any machine with a GPU)
  python3 tools/train.py train --data datasets/biotag/data.yaml --epochs 100

  # 2. copy runs/detect/biotag/weights/best.pt to the Jetson, then on the Jetson:
  python3 tools/train.py export --weights best.pt        # -> models/biotag.engine

Dataset: export from Roboflow in "YOLOv8/YOLO11" format. Start from TACO or
TrashNet and add 200-500 of your own photos of crushed, dirty, half-covered
and untagged items shot through the bin's own camera and lighting. Class names
must appear in classifier.label_map in config.yaml.
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def train(args) -> None:
    from ultralytics import YOLO

    model = YOLO(args.base)
    model.train(
        data=args.data, epochs=args.epochs, imgsz=args.imgsz, batch=args.batch, name="biotag",
        # augmentation aimed at damaged / obscured items
        degrees=25, translate=0.15, scale=0.5, shear=5, perspective=0.0005,
        hsv_h=0.02, hsv_s=0.7, hsv_v=0.5, fliplr=0.5, flipud=0.2,
        mosaic=1.0, mixup=0.1, erasing=0.4,
    )
    print(model.val())


def export(args) -> None:
    from ultralytics import YOLO

    model = YOLO(args.weights)
    out = model.export(format="engine", half=True, imgsz=args.imgsz, device=0)   # FP16 TensorRT
    dest = Path(args.out)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(out, dest)
    print(f"engine written to {dest}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("train")
    t.add_argument("--data", required=True)
    t.add_argument("--base", default="yolo11s.pt", help="yolo11n.pt is faster, yolo11s.pt more accurate")
    t.add_argument("--epochs", type=int, default=100)
    t.add_argument("--imgsz", type=int, default=640)
    t.add_argument("--batch", type=int, default=16)
    t.set_defaults(fn=train)
    e = sub.add_parser("export")
    e.add_argument("--weights", required=True)
    e.add_argument("--imgsz", type=int, default=640)
    e.add_argument("--out", default="models/biotag.engine")
    e.set_defaults(fn=export)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
