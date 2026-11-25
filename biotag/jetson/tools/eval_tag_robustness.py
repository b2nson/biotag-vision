#!/usr/bin/env python3
"""Measure how much damage a BioTag survives before the reader gives up.

Synthetically fades, blurs, stains, covers and tears a tag at increasing
severity and reports the decode rate, with and without image enhancement.
This is a bench estimate, not a substitute for testing real worn stickers.

    python3 tools/eval_tag_robustness.py --trials 30
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from biotag.tag_reader import TagReader  # noqa: E402
from tools.generate_tags import make_tag  # noqa: E402


def scene(rng: np.random.Generator):
    """A 1280x720 frame with a tag at a random position, size and tilt."""
    tag = cv2.cvtColor(np.array(make_tag("000001", "PET", "R")), cv2.COLOR_RGB2BGR)
    side = int(rng.integers(220, 380))
    tag = cv2.resize(tag, (side, int(side * tag.shape[0] / tag.shape[1])))
    h, w = tag.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), float(rng.uniform(-20, 20)), 1.0)
    tag = cv2.warpAffine(tag, m, (w, h), borderValue=(255, 255, 255))
    frame = np.full((720, 1280, 3), 150, np.uint8)
    y, x = int(rng.integers(20, 720 - h - 20)), int(rng.integers(20, 1280 - w - 20))
    frame[y:y + h, x:x + w] = tag
    return frame, (x, y, w, h)


def fade(img, box, s, rng):          # worn / sun-bleached print
    out = img.astype(np.float32)
    return np.clip(255 - (255 - out) * (1 - 0.92 * s), 0, 255).astype(np.uint8)


def blur(img, box, s, rng):          # out of focus / motion
    k = 1 + 2 * int(1 + 9 * s)
    return cv2.GaussianBlur(img, (k, k), 0)


def stain(img, box, s, rng):         # coffee: translucent brown blobs
    x, y, w, h = box
    out = img.copy()
    layer = img.copy()
    if s == 0:
        return out
    for _ in range(1 + int(6 * s)):
        c = (int(x + rng.uniform(0, w)), int(y + rng.uniform(0, h)))
        cv2.circle(layer, c, int(w * rng.uniform(0.08, 0.22)), (40, 70, 110), -1)
    a = 0.35 + 0.45 * s
    return cv2.addWeighted(layer, a, out, 1 - a, 0)


def cover(img, box, s, rng):         # opaque: food, a thumb, another item
    x, y, w, h = box
    out = img.copy()
    cw = int(w * 0.5 * s)
    if cw == 0:
        return out
    cx = int(x + rng.uniform(0, w - cw))
    cv2.rectangle(out, (cx, y), (cx + cw, y + h), (60, 60, 60), -1)
    return out


def tear(img, box, s, rng):          # a corner missing
    x, y, w, h = box
    out = img.copy()
    t = int(w * 0.6 * s)
    if t == 0:
        return out
    pts = np.array([[x, y], [x + t, y], [x, y + t]], np.int32)
    cv2.fillPoly(out, [pts], (150, 150, 150))
    return out


DAMAGE = {"faded": fade, "blurred": blur, "stained": stain, "covered": cover, "torn": tear}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=20)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()

    readers = {"plain": TagReader(enhance=False), "enhanced": TagReader(enhance=True)}
    levels = [0.0, 0.25, 0.5, 0.75, 1.0]
    from biotag import tag_reader
    print(f"decoder: OpenCV QRCodeDetector{' + pyzbar' if tag_reader._zbar else ' (pyzbar not installed)'}")
    print(f"decode rate over {args.trials} trials  (plain / enhanced)\n")
    print(f"{'damage':<10}" + "".join(f"{f'sev {s:.2f}':>16}" for s in levels))
    for name, fn in DAMAGE.items():
        row = f"{name:<10}"
        for s in levels:
            rng = np.random.default_rng(args.seed)
            hits = {k: 0 for k in readers}
            for _ in range(args.trials):
                frame, box = scene(rng)
                damaged = fn(frame, box, s, rng)
                for k, reader in readers.items():
                    hits[k] += reader.read(damaged).tag is not None
            row += f"{hits['plain'] / args.trials:>8.0%} /{hits['enhanced'] / args.trials:>5.0%} "
        print(row)


if __name__ == "__main__":
    main()
