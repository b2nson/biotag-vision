#!/usr/bin/env python3
"""
Train the BioTag detector (YOLO26). Finds the tag and labels its condition:
clean / occluded / stained / damaged.

Real photos: label them in Roboflow (YOLO format, same 4 class names in the
same order) and put them in data/real/images/{train,val} + data/real/labels/...
They are merged in automatically and matter more than synthetic images.

Examples:
  python scripts/train_detector.py                       # yolo26s, 100 epochs
  python scripts/train_detector.py --model yolo26n.pt    # faster on the Nano
  python scripts/train_detector.py --device cpu --epochs 1 --imgsz 320   # smoke test
"""
import argparse
import shutil
from pathlib import Path

from ultralytics import YOLO

CONDITIONS = ["biotag_clean", "biotag_occluded", "biotag_stained", "biotag_damaged"]


def build_yaml(data_root: Path, real_root: Path) -> Path:
    train = [str((data_root / "det/images/train").resolve())]
    val = [str((data_root / "det/images/val").resolve())]
    if (real_root / "images/train").exists():
        train.append(str((real_root / "images/train").resolve()))
        print(f"+ real photos: {real_root / 'images/train'}")
    if (real_root / "images/val").exists():
        val.append(str((real_root / "images/val").resolve()))
    y = data_root / "det" / "biotag_det_merged.yaml"
    y.write_text(
        "train:\n" + "".join(f"  - {p}\n" for p in train)
        + "val:\n" + "".join(f"  - {p}\n" for p in val)
        + "names:\n" + "".join(f"  {i}: {n}\n" for i, n in enumerate(CONDITIONS))
    )
    return y


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="yolo26s.pt", help="yolo26n.pt (fast) / yolo26s.pt (default) / yolo26m.pt")
    ap.add_argument("--data", default="data")
    ap.add_argument("--real", default="data/real")
    ap.add_argument("--epochs", type=int, default=100)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--batch", type=int, default=16, help="use 4-8 if training on the Orin Nano")
    ap.add_argument("--device", default=None, help="0 for GPU, cpu, or leave empty for auto")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    yaml = build_yaml(Path(args.data), Path(args.real))
    model = YOLO(args.model)
    model.train(
        data=str(yaml), epochs=args.epochs, imgsz=args.imgsz, batch=args.batch,
        device=args.device, workers=args.workers, project="runs", name="biotag_det", exist_ok=True,
        patience=25, close_mosaic=10,
        # extra robustness for real bins: rotation, perspective, lighting, partial blocking
        degrees=15, perspective=0.0005, hsv_h=0.02, hsv_s=0.6, hsv_v=0.5,
        fliplr=0.0,  # tags have text/codes; mirrored tags never occur in real life
    )
    best = Path(model.trainer.save_dir) / "weights" / "best.pt"
    Path("models").mkdir(exist_ok=True)
    shutil.copy(best, "models/biotag_det.pt")
    metrics = YOLO("models/biotag_det.pt").val(data=str(yaml), imgsz=args.imgsz, device=args.device, plots=False)
    print(f"saved models/biotag_det.pt   mAP50={metrics.box.map50:.3f}  mAP50-95={metrics.box.map:.3f}")


if __name__ == "__main__":
    main()
