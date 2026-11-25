"""BioTag sticker reader.

ASSUMPTION: the BioTag sticker is a QR code whose text is

    BT1:<item_id>:<material>:<bin>        e.g.  BT1:000123:PET:R

If your real BioTag uses a different symbology or payload, only `parse_payload`
and `TagReader._decode` need to change; the rest of the system uses `Tag`.

Damaged-tag handling: the raw frame is tried first, then enhanced versions
(contrast-equalised, upscaled, thresholded, sharpened). If a QR outline is
found but nothing decodes, `damaged=True` is reported so the vision model can
take over and the screen can say why.
"""
from __future__ import annotations

from typing import Iterator, Optional, Tuple

import cv2
import numpy as np

from .types import Tag, TagRead

try:  # optional, noticeably better on blurred / low-contrast codes
    from pyzbar import pyzbar as _zbar
except Exception:  # pragma: no cover - library or libzbar missing
    _zbar = None


def make_payload(item_id: str, material: str, bin_id: str, prefix: str = "BT1") -> str:
    return f"{prefix}:{item_id}:{material.upper()}:{bin_id.upper()}"


def parse_payload(text: str, prefix: str = "BT1") -> Optional[Tag]:
    parts = text.strip().split(":")
    if len(parts) != 4 or parts[0] != prefix:
        return None
    _, item_id, material, bin_id = parts
    bin_id = bin_id.upper()
    if bin_id not in ("R", "C", "L") or not material or not item_id:
        return None
    return Tag(item_id=item_id, material=material.upper(), bin=bin_id, raw=text.strip())


class TagReader:
    def __init__(self, prefix: str = "BT1", enhance: bool = True):
        self.prefix = prefix
        self.enhance = enhance
        self._qr = cv2.QRCodeDetector()
        self._clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))

    def read(self, image: np.ndarray) -> TagRead:
        located = None
        for variant in self._variants(image):
            text, points = self._decode(variant)
            if points is not None and located is None:
                located = points
            if text:
                tag = parse_payload(text, self.prefix)
                if tag:
                    return TagRead(tag=tag, damaged=False, points=points)
        return TagRead(tag=None, damaged=located is not None, points=located)

    # ------------------------------------------------------------------
    def _variants(self, image: np.ndarray) -> Iterator[np.ndarray]:
        yield image
        if not self.enhance:
            return
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
        eq = self._clahe.apply(gray)
        yield eq                                                   # faded print
        h, w = gray.shape[:2]
        if max(h, w) < 1600:
            yield cv2.resize(eq, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)  # small tag
        blur = cv2.GaussianBlur(eq, (0, 0), 3)
        yield cv2.addWeighted(eq, 1.8, blur, -0.8, 0)              # soft focus
        yield cv2.adaptiveThreshold(eq, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                    cv2.THRESH_BINARY, 51, 10)     # stains, uneven light

    def _decode(self, img: np.ndarray) -> Tuple[str, Optional[np.ndarray]]:
        try:
            text, points, _ = self._qr.detectAndDecode(img)
        except cv2.error:
            text, points = "", None
        if text:
            return text, points
        if _zbar is not None:
            for sym in _zbar.decode(img):
                try:
                    return sym.data.decode("utf-8"), np.array(sym.polygon, dtype=np.float32)
                except UnicodeDecodeError:
                    continue
        return "", points
