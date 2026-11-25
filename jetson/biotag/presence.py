"""Is something being held in front of the camera?

With a depth camera (ZED 2) this is a range check. Without depth it is a
comparison against a slowly-updated background image, so mount the camera
looking at a fixed, plain backdrop.
"""
from __future__ import annotations

from typing import Optional

import cv2
import numpy as np

from .types import Frame


class PresenceDetector:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self._bg: Optional[np.ndarray] = None

    def rebase(self) -> None:
        """Forget the background (call after each cycle so lighting drift cannot stick)."""
        self._bg = None

    def _roi(self, arr: np.ndarray) -> np.ndarray:
        h, w = arr.shape[:2]
        f = self.cfg["roi"]
        dy, dx = int(h * (1 - f) / 2), int(w * (1 - f) / 2)
        return arr[dy:h - dy, dx:w - dx]

    def update(self, frame: Frame) -> bool:
        c = self.cfg
        if frame.depth is not None:
            d = self._roi(frame.depth)
            valid = np.isfinite(d) & (d > c["depth_min_m"]) & (d < c["depth_max_m"])
            return float(valid.mean()) > c["depth_fraction"]

        small = cv2.resize(self._roi(frame.image), (160, 90), interpolation=cv2.INTER_AREA)
        gray = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (5, 5), 0).astype(np.float32)
        if self._bg is None:
            self._bg = gray
            return False
        present = float(np.abs(gray - self._bg).mean()) > c["diff_threshold"]
        if not present:
            cv2.accumulateWeighted(gray, self._bg, 0.05)
        return present
