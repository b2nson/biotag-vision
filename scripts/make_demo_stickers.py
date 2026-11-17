#!/usr/bin/env python3
"""
Makes placeholder BioTag stickers (QR code + colour band + bin word) so you can
test the whole pipeline before you have photos of the real stickers.
Replace assets/stickers/<bin>/ with photos/scans of the real BioTags later.

  python scripts/make_demo_stickers.py
"""
from pathlib import Path

import cv2
import numpy as np

BINS = {"recycle": (200, 120, 30), "compost": (60, 160, 60), "landfill": (90, 90, 90)}


def main(out="assets/stickers", variants=4):
    enc = cv2.QRCodeEncoder.create()
    for b, col in BINS.items():
        d = Path(out) / b
        d.mkdir(parents=True, exist_ok=True)
        for v in range(variants):
            qr = enc.encode(f"BIOTAG:{b.upper()}:{1000 + v:06d}")
            qr = cv2.resize(qr, (300, 300), interpolation=cv2.INTER_NEAREST)
            tag = np.full((420, 360, 3), 255, np.uint8)
            tag[:70] = col
            cv2.putText(tag, "BioTag", (18, 50), cv2.FONT_HERSHEY_DUPLEX, 1.3, (255, 255, 255), 2)
            tag[85:385, 30:330] = cv2.cvtColor(qr, cv2.COLOR_GRAY2BGR)
            cv2.putText(tag, b.upper(), (30, 412), cv2.FONT_HERSHEY_SIMPLEX, 0.8, col, 2)
            cv2.rectangle(tag, (0, 0), (359, 419), col, 6)
            cv2.imwrite(str(d / f"demo_{v}.png"), tag)
    print(f"wrote demo stickers to {out}/")


if __name__ == "__main__":
    main()
