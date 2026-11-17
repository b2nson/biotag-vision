#!/usr/bin/env python3
"""
Convert the trained models to TensorRT engines. RUN THIS ON THE JETSON:
an engine only works on the GPU and TensorRT version that built it.

  python scripts/export_trt.py            # FP16 (recommended)
  python scripts/export_trt.py --int8     # faster, needs calibration images, check accuracy after
"""
import argparse

from ultralytics import YOLO


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--det", default="models/biotag_det.pt")
    ap.add_argument("--cls", default="models/biotag_cls.pt")
    ap.add_argument("--det-imgsz", type=int, default=640)
    ap.add_argument("--cls-imgsz", type=int, default=224)
    ap.add_argument("--int8", action="store_true")
    args = ap.parse_args()

    kw = dict(format="engine", device=0, half=not args.int8, int8=args.int8, workspace=2)
    det = YOLO(args.det).export(imgsz=args.det_imgsz,
                                data="data/det/biotag_det_merged.yaml" if args.int8 else None, **kw)
    cls = YOLO(args.cls).export(imgsz=args.cls_imgsz, data="data/cls" if args.int8 else None, **kw)
    print(f"engines:\n  {det}\n  {cls}")


if __name__ == "__main__":
    main()
