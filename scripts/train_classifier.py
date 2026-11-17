#!/usr/bin/env python3
"""
Train the small BioTag reader network (YOLO26 classification).

Input: a crop of the tag from the detector. Output: which bin the tag means
(recycle / compost / landfill, or whatever folders you put in assets/stickers).
This is what still works when the code on a stained, torn or half-covered tag
can no longer be decoded.

Examples:
  python scripts/train_classifier.py
  python scripts/train_classifier.py --model yolo26s-cls.pt --epochs 80
"""
import argparse
import shutil
from pathlib import Path

from ultralytics import YOLO


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="yolo26n-cls.pt", help="yolo26n-cls.pt (small) or yolo26s-cls.pt (medium)")
    ap.add_argument("--data", default="data/cls")
    ap.add_argument("--epochs", type=int, default=60)
    ap.add_argument("--imgsz", type=int, default=224)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--device", default=None)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    model = YOLO(args.model)
    model.train(
        data=str(Path(args.data).resolve()), epochs=args.epochs, imgsz=args.imgsz, batch=args.batch,
        device=args.device, workers=args.workers, project="runs", name="biotag_cls", exist_ok=True,
        patience=15, fliplr=0.0, degrees=20, hsv_v=0.5, erasing=0.4,  # random erasing = extra occlusion practice
    )
    Path("models").mkdir(exist_ok=True)
    shutil.copy(Path(model.trainer.save_dir) / "weights" / "best.pt", "models/biotag_cls.pt")
    shutil.copy(Path(args.data) / "bins.txt", "models/bins.txt")
    m = YOLO("models/biotag_cls.pt").val(data=str(Path(args.data).resolve()), imgsz=args.imgsz,
                                          device=args.device, plots=False)
    print(f"saved models/biotag_cls.pt   top1={m.top1:.3f}")


if __name__ == "__main__":
    main()
