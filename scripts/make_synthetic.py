#!/usr/bin/env python3
"""
Synthetic BioTag edge-case dataset generator.

Takes clean photos/scans of your BioTag stickers and pastes them onto real
background photos (packaging, tables, bins) while simulating the edge cases
Dr. Lee asked about:

  clean     - tag fully visible
  occluded  - partly blocked by another object, tape, another label, etc.
  stained   - coffee rings, grease, food smears, dirt
  damaged   - torn off, scratched, faded, crumpled, peeling corner

Outputs two datasets in one pass:
  <out>/det/  YOLO detection dataset (classes = tag condition)
  <out>/cls/  image-folder classification dataset of tag crops (classes = bin)

Folder layout expected:
  assets/stickers/<bin_name>/*.png|jpg   e.g. recycle/, compost/, landfill/
  assets/backgrounds/*.jpg               any photos without BioTags on them

Usage:
  python scripts/make_synthetic.py --n 4000
"""
import argparse
import random
from pathlib import Path

import cv2
import numpy as np

CONDITIONS = ["biotag_clean", "biotag_occluded", "biotag_stained", "biotag_damaged"]
IMG_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}


# --------------------------------------------------------------------------- io
def list_images(folder: Path):
    return sorted(p for p in folder.rglob("*") if p.suffix.lower() in IMG_EXT)


def load_rgba(path: Path) -> np.ndarray:
    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ValueError(f"Could not read {path}")
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if img.shape[2] == 3:
        a = np.full(img.shape[:2], 255, np.uint8)
        img = np.dstack([img, a])
    return img


def random_background(bgs, size):
    w, h = size
    if bgs:
        bg = cv2.imread(str(random.choice(bgs)))
        if bg is not None:
            bh, bw = bg.shape[:2]
            s = max(w / bw, h / bh) * random.uniform(1.0, 1.6)
            bg = cv2.resize(bg, (int(bw * s) + 1, int(bh * s) + 1))
            y = random.randint(0, bg.shape[0] - h)
            x = random.randint(0, bg.shape[1] - w)
            return bg[y:y + h, x:x + w].copy()
    # fallback: textured gradient
    base = np.random.randint(40, 220, 3)
    grad = np.linspace(0.6, 1.2, w)[None, :, None]
    bg = np.clip(base[None, None, :] * grad + np.random.normal(0, 18, (h, w, 3)), 0, 255)
    return cv2.GaussianBlur(bg.astype(np.uint8), (0, 0), 3)


# -------------------------------------------------------------- degradations
def blob_mask(h, w, n=None, scale=0.35):
    """Organic blob mask in [0,1]."""
    m = np.zeros((h, w), np.float32)
    n = n or random.randint(3, 8)
    cx, cy = random.uniform(0.2, 0.8) * w, random.uniform(0.2, 0.8) * h
    for _ in range(n):
        ax = int(random.uniform(0.05, scale) * w) + 1
        ay = int(random.uniform(0.05, scale) * h) + 1
        c = (int(cx + random.gauss(0, w * 0.12)), int(cy + random.gauss(0, h * 0.12)))
        cv2.ellipse(m, c, (ax, ay), random.uniform(0, 180), 0, 360, 1.0, -1)
    m = cv2.GaussianBlur(m, (0, 0), max(2, min(h, w) * 0.03))
    return np.clip(m * 1.4, 0, 1)


def apply_stain(rgba):
    h, w = rgba.shape[:2]
    kind = random.choice(["coffee", "coffee_ring", "grease", "food", "dirt"])
    out = rgba.astype(np.float32)
    for _ in range(random.randint(1, 3)):
        m = blob_mask(h, w)
        if kind == "coffee_ring":
            k = max(3, int(min(h, w) * 0.04)) | 1
            ring = m - cv2.erode(m, np.ones((k, k), np.uint8))
            m = np.clip(m * 0.35 + ring * 2.2, 0, 1)
        color = {
            "coffee": (40, 75, 115), "coffee_ring": (30, 60, 100),
            "grease": (120, 190, 215), "food": (50, 90, 200), "dirt": (60, 70, 80),
        }[kind if kind != "coffee_ring" else "coffee_ring"]
        color = np.array(color, np.float32) * random.uniform(0.7, 1.15)
        strength = random.uniform(0.35, 0.85)
        a = (m * strength)[..., None]
        if kind == "grease":  # translucent darkening rather than a color
            out[..., :3] = out[..., :3] * (1 - a * 0.45) + color * a * 0.25
        else:
            out[..., :3] = out[..., :3] * (1 - a) + color * a
    return np.clip(out, 0, 255).astype(np.uint8)


def apply_damage(rgba):
    h, w = rgba.shape[:2]
    out = rgba.copy()
    kinds = random.sample(["tear", "scratch", "fade", "crumple", "peel"], k=random.randint(1, 2))
    for kind in kinds:
        if kind == "tear":  # jagged cut, remove 10-40% of the tag
            side = random.choice(["l", "r", "t", "b"])
            frac = random.uniform(0.1, 0.4)
            pts = []
            steps = 12
            for i in range(steps + 1):
                t = i / steps
                j = random.uniform(-0.06, 0.06)
                if side in "lr":
                    x = (frac + j) * w if side == "l" else (1 - frac + j) * w
                    pts.append((x, t * h))
                else:
                    y = (frac + j) * h if side == "t" else (1 - frac + j) * h
                    pts.append((t * w, y))
            if side == "l":
                poly = [(0, 0)] + pts + [(0, h)]
            elif side == "r":
                poly = [(w, 0)] + pts + [(w, h)]
            elif side == "t":
                poly = [(0, 0)] + pts + [(w, 0)]
            else:
                poly = [(0, h)] + pts + [(w, h)]
            alpha = np.ascontiguousarray(out[..., 3])
            cv2.fillPoly(alpha, [np.array(poly, np.int32)], 0)
            out[..., 3] = alpha
            # white paper fibre along the tear edge
            cv2.polylines(out, [np.array(pts, np.int32)], False, (235, 235, 235, 255),
                          max(1, int(min(h, w) * 0.012)))
        elif kind == "scratch":
            for _ in range(random.randint(3, 12)):
                p1 = (random.randint(0, w), random.randint(0, h))
                p2 = (p1[0] + random.randint(-w // 2, w // 2), p1[1] + random.randint(-h // 2, h // 2))
                c = random.randint(170, 250)
                cv2.line(out, p1, p2, (c, c, c, 255), random.randint(1, max(1, w // 60)))
        elif kind == "fade":
            f = random.uniform(0.35, 0.75)
            rgb = out[..., :3].astype(np.float32)
            hsv = cv2.cvtColor(rgb.astype(np.uint8), cv2.COLOR_BGR2HSV).astype(np.float32)
            hsv[..., 1] *= f
            rgb = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR).astype(np.float32)
            out[..., :3] = np.clip(rgb * f + 255 * (1 - f) * random.uniform(0.6, 1.0), 0, 255).astype(np.uint8)
        elif kind == "crumple":
            amp = random.uniform(0.01, 0.035) * min(h, w)
            fx, fy = random.uniform(2, 6), random.uniform(2, 6)
            xs, ys = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
            mx = xs + amp * np.sin(2 * np.pi * ys / h * fy + random.random() * 6)
            my = ys + amp * np.sin(2 * np.pi * xs / w * fx + random.random() * 6)
            out = cv2.remap(out, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
            shade = 0.8 + 0.2 * np.sin(2 * np.pi * xs / w * fx) * np.sin(2 * np.pi * ys / h * fy)
            out[..., :3] = np.clip(out[..., :3] * shade[..., None], 0, 255).astype(np.uint8)
        elif kind == "peel":  # folded corner shows white backing
            s = int(random.uniform(0.15, 0.35) * min(h, w))
            corner = random.choice([(0, 0), (w, 0), (0, h), (w, h)])
            dx = s if corner[0] == 0 else -s
            dy = s if corner[1] == 0 else -s
            tri = np.array([corner, (corner[0] + dx, corner[1]), (corner[0], corner[1] + dy)], np.int32)
            cv2.fillPoly(out, [tri], (225, 225, 225, 255))
            cv2.polylines(out, [tri], True, (150, 150, 150, 255), 1)
    return out


def apply_occlusion(img, box, others, bgs):
    """Cover 20-60% of the tag box with something."""
    x1, y1, x2, y2 = box
    bw, bh = x2 - x1, y2 - y1
    if bw < 4 or bh < 4:
        return img
    kind = random.choice(["patch", "tape", "label", "shape"])
    cover = random.uniform(0.2, 0.6)
    # occluder rectangle that overlaps an edge of the tag
    ow, oh = int(bw * random.uniform(0.4, 1.1)), int(bh * random.uniform(0.4, 1.1))
    side = random.choice(["l", "r", "t", "b"])
    if side == "l":
        ox, oy = int(x1 - ow + bw * cover), random.randint(y1 - oh // 2, y2 - oh // 2)
    elif side == "r":
        ox, oy = int(x2 - bw * cover), random.randint(y1 - oh // 2, y2 - oh // 2)
    elif side == "t":
        ox, oy = random.randint(x1 - ow // 2, x2 - ow // 2), int(y1 - oh + bh * cover)
    else:
        ox, oy = random.randint(x1 - ow // 2, x2 - ow // 2), int(y2 - bh * cover)
    H, W = img.shape[:2]
    ox1, oy1, ox2, oy2 = max(0, ox), max(0, oy), min(W, ox + ow), min(H, oy + oh)
    if ox2 <= ox1 or oy2 <= oy1:
        return img
    region = img[oy1:oy2, ox1:ox2]
    rh, rw = region.shape[:2]
    if kind == "patch":  # random object texture from another photo
        tex = random_background(bgs, (rw, rh))
        mask = np.zeros((rh, rw), np.float32)
        pts = np.array([[random.randint(0, rw), random.randint(0, rh)] for _ in range(random.randint(5, 9))])
        cv2.fillPoly(mask, [cv2.convexHull(pts)], 1.0)
        mask = cv2.GaussianBlur(mask, (0, 0), 1.5)[..., None]
        region[:] = (region * (1 - mask) + tex * mask).astype(np.uint8)
    elif kind == "tape":  # translucent tape strip
        c = np.array(random.choice([(200, 220, 230), (220, 220, 220), (80, 160, 200)]), np.float32)
        a = random.uniform(0.35, 0.65)
        region[:] = np.clip(region * (1 - a) + c * a + random.uniform(0, 30), 0, 255).astype(np.uint8)
    elif kind == "label" and others:  # another (non-BioTag) label stuck on top
        o = random.choice(others)
        o = cv2.resize(o, (rw, rh))
        a = (o[..., 3:4] / 255.0)
        region[:] = (region * (1 - a) + o[..., :3] * a).astype(np.uint8)
    else:  # solid shape (food, fingers of a glove, packaging fold)
        color = tuple(int(v) for v in np.random.randint(20, 235, 3))
        mask = np.zeros((rh, rw), np.uint8)
        cv2.ellipse(mask, (rw // 2, rh // 2), (rw // 2, rh // 2), random.uniform(0, 180), 0, 360, 255, -1)
        region[mask > 0] = color
    return img


# ------------------------------------------------------------------- paste
def paste_sticker(canvas, rgba, max_frac):
    H, W = canvas.shape[:2]
    sh, sw = rgba.shape[:2]
    target = random.uniform(0.08, max_frac) * W
    s = target / max(sw, sh)
    rgba = cv2.resize(rgba, (max(8, int(sw * s)), max(8, int(sh * s))), interpolation=cv2.INTER_AREA)
    sh, sw = rgba.shape[:2]
    src = np.float32([[0, 0], [sw, 0], [sw, sh], [0, sh]])
    cx = random.uniform(sw * 0.6, W - sw * 0.6) if W > sw * 1.2 else W / 2
    cy = random.uniform(sh * 0.6, H - sh * 0.6) if H > sh * 1.2 else H / 2
    ang = np.deg2rad(random.uniform(-35, 35))
    R = np.array([[np.cos(ang), -np.sin(ang)], [np.sin(ang), np.cos(ang)]])
    dst = (src - [sw / 2, sh / 2]) @ R.T
    dst += np.random.uniform(-0.08, 0.08, dst.shape) * [sw, sh]  # perspective jitter
    dst = np.float32(dst + [cx, cy])
    M = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(rgba, M, (W, H), flags=cv2.INTER_LINEAR, borderValue=(0, 0, 0, 0))
    a = warped[..., 3:4].astype(np.float32) / 255.0
    canvas[:] = (canvas * (1 - a) + warped[..., :3] * a).astype(np.uint8)
    ys, xs = np.where(warped[..., 3] > 127)
    if len(xs) < 20:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def global_aug(img):
    if random.random() < 0.5:  # lighting
        img = cv2.convertScaleAbs(img, alpha=random.uniform(0.6, 1.35), beta=random.uniform(-35, 35))
    if random.random() < 0.3:  # glare spot
        H, W = img.shape[:2]
        g = np.zeros((H, W), np.float32)
        cv2.circle(g, (random.randint(0, W), random.randint(0, H)), random.randint(W // 12, W // 4), 1.0, -1)
        g = cv2.GaussianBlur(g, (0, 0), W / 15)[..., None] * random.uniform(0.3, 0.8)
        img = np.clip(img + g * 255, 0, 255).astype(np.uint8)
    if random.random() < 0.35:
        k = random.choice([3, 5, 7])
        img = cv2.GaussianBlur(img, (k, k), 0) if random.random() < 0.6 else motion_blur(img, k + 2)
    if random.random() < 0.3:
        img = np.clip(img + np.random.normal(0, random.uniform(4, 14), img.shape), 0, 255).astype(np.uint8)
    if random.random() < 0.4:
        q = random.randint(35, 85)
        img = cv2.imdecode(cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])[1], cv2.IMREAD_COLOR)
    return img


def motion_blur(img, k):
    kern = np.zeros((k, k), np.float32)
    kern[k // 2, :] = 1.0 / k
    M = cv2.getRotationMatrix2D((k / 2, k / 2), random.uniform(0, 180), 1)
    kern = cv2.warpAffine(kern, M, (k, k))
    return cv2.filter2D(img, -1, kern / max(kern.sum(), 1e-6))


# -------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stickers", default="assets/stickers")
    ap.add_argument("--backgrounds", default="assets/backgrounds")
    ap.add_argument("--distractors", default="assets/distractors",
                    help="optional: other labels/logos that are NOT BioTags (used as occluders and negatives)")
    ap.add_argument("--out", default="data")
    ap.add_argument("--n", type=int, default=4000, help="number of synthetic images")
    ap.add_argument("--size", type=int, default=640)
    ap.add_argument("--val", type=float, default=0.15)
    ap.add_argument("--max-frac", type=float, default=0.35, help="max tag width as fraction of image")
    ap.add_argument("--negatives", type=float, default=0.08, help="fraction of images with no BioTag")
    ap.add_argument("--probs", default="0.25,0.25,0.25,0.25", help="clean,occluded,stained,damaged")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    random.seed(args.seed)
    np.random.seed(args.seed)
    root = Path(args.stickers)
    bins = sorted(d.name for d in root.iterdir() if d.is_dir() and list_images(d))
    if not bins:
        raise SystemExit(f"No sticker folders found in {root}. Expected {root}/<bin_name>/*.png")
    stickers = {b: [load_rgba(p) for p in list_images(root / b)] for b in bins}
    bgs = list_images(Path(args.backgrounds)) if Path(args.backgrounds).exists() else []
    others = [load_rgba(p) for p in list_images(Path(args.distractors))] if Path(args.distractors).exists() else []
    probs = [float(x) for x in args.probs.split(",")]
    print(f"bins={bins}  stickers={sum(map(len, stickers.values()))}  backgrounds={len(bgs)}  distractors={len(others)}")
    if not bgs:
        print("WARNING: no background photos found; using generated textures. Add real photos for good results.")

    out = Path(args.out)
    for split in ("train", "val"):
        (out / "det" / "images" / split).mkdir(parents=True, exist_ok=True)
        (out / "det" / "labels" / split).mkdir(parents=True, exist_ok=True)
        for b in bins:
            (out / "cls" / split / b).mkdir(parents=True, exist_ok=True)

    counts = {c: 0 for c in CONDITIONS}
    for i in range(args.n):
        split = "val" if random.random() < args.val else "train"
        img = random_background(bgs, (args.size, args.size))
        labels, crops = [], []
        if random.random() >= args.negatives:
            for _ in range(1 if random.random() < 0.85 else 2):
                b = random.choice(bins)
                rgba = random.choice(stickers[b]).copy()
                cond = random.choices(range(4), weights=probs)[0]
                if cond == 2:
                    rgba = apply_stain(rgba)
                elif cond == 3:
                    rgba = apply_damage(rgba)
                box = paste_sticker(img, rgba, args.max_frac)
                if box is None:
                    continue
                if cond == 1:
                    img = apply_occlusion(img, box, others, bgs)
                labels.append((cond, box))
                crops.append((b, box))
                counts[CONDITIONS[cond]] += 1
        elif others and random.random() < 0.7:  # hard negative: a non-BioTag label
            paste_sticker(img, random.choice(others).copy(), args.max_frac)
        img = global_aug(img)

        stem = f"syn_{i:06d}"
        cv2.imwrite(str(out / "det" / "images" / split / f"{stem}.jpg"), img)
        H, W = img.shape[:2]
        with open(out / "det" / "labels" / split / f"{stem}.txt", "w") as f:
            for cond, (x1, y1, x2, y2) in labels:
                f.write(f"{cond} {(x1 + x2) / 2 / W:.6f} {(y1 + y2) / 2 / H:.6f} "
                        f"{(x2 - x1) / W:.6f} {(y2 - y1) / H:.6f}\n")
        for j, (b, (x1, y1, x2, y2)) in enumerate(crops):
            pad = int(0.08 * max(x2 - x1, y2 - y1))
            crop = img[max(0, y1 - pad):y2 + pad, max(0, x1 - pad):x2 + pad]
            if crop.size:
                cv2.imwrite(str(out / "cls" / split / b / f"{stem}_{j}.jpg"), crop)
        if (i + 1) % 500 == 0:
            print(f"  {i + 1}/{args.n}")

    yaml = out / "det" / "biotag_det.yaml"
    yaml.write_text(
        f"path: {(out / 'det').resolve()}\ntrain: images/train\nval: images/val\nnames:\n"
        + "".join(f"  {k}: {v}\n" for k, v in enumerate(CONDITIONS))
    )
    (out / "cls" / "bins.txt").write_text("\n".join(bins) + "\n")
    print(f"done. tag instances per condition: {counts}")
    print(f"detector data: {yaml}\nclassifier data: {out / 'cls'}")


if __name__ == "__main__":
    main()
