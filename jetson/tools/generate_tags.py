#!/usr/bin/env python3
"""Make printable BioTag stickers (QR codes with the highest error correction).

    python3 tools/generate_tags.py --material PET --bin R --count 5
    python3 tools/generate_tags.py --demo          # one tag per material in materials.json

Level-H error correction lets a code survive roughly 30% damage, which is the
first line of defence against worn or stained stickers.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import qrcode
from PIL import Image, ImageDraw, ImageFont
from qrcode.constants import ERROR_CORRECT_H

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from biotag.tag_reader import make_payload  # noqa: E402

BIN_NAMES = {"R": "RECYCLE", "C": "COMPOST", "L": "LANDFILL"}


def make_tag(item_id: str, material: str, bin_id: str, box_size: int = 12) -> Image.Image:
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_H, box_size=box_size, border=4)
    qr.add_data(make_payload(item_id, material, bin_id))
    qr.make(fit=True)
    code = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    w, h = code.size
    sticker = Image.new("RGB", (w, h + 40), "white")
    sticker.paste(code, (0, 0))
    draw = ImageDraw.Draw(sticker)
    text = f"BioTag  {material}  {BIN_NAMES[bin_id]}  #{item_id}"
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 18)
    except OSError:
        font = ImageFont.load_default()
    draw.text((w // 2, h + 18), text, fill="black", anchor="mm", font=font)
    return sticker


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--material", default="PET")
    ap.add_argument("--bin", default="R", choices=["R", "C", "L"])
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--start", type=int, default=1, help="first item number")
    ap.add_argument("--out", default="tags")
    ap.add_argument("--demo", action="store_true", help="one tag for every known material")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    jobs = []
    if args.demo:
        db = json.loads((Path(__file__).resolve().parents[1] / "biotag" / "materials.json").read_text())
        for n, (code, info) in enumerate(db.items(), start=1):
            if code not in ("UNKNOWN", "CONTAM"):
                jobs.append((f"{n:06d}", code, info["bin"]))
    else:
        jobs = [(f"{args.start + i:06d}", args.material.upper(), args.bin) for i in range(args.count)]
    for item_id, material, bin_id in jobs:
        path = out / f"biotag_{material}_{item_id}.png"
        make_tag(item_id, material, bin_id).save(path)
        print(path)


if __name__ == "__main__":
    main()
