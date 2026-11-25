"""On-screen UI: live camera view plus a large banner with the result."""
from __future__ import annotations

from typing import Optional

import cv2
import numpy as np

from .types import Decision, Observation

COLORS = {"R": (200, 110, 20), "C": (60, 150, 40), "L": (70, 70, 70)}   # BGR
FONT = cv2.FONT_HERSHEY_SIMPLEX
WINDOW = "BioTag"


def render(image: np.ndarray, state: str, decision: Optional[Decision],
           obs: Optional[Observation], link_ok: bool, vision_ok: bool) -> np.ndarray:
    canvas = image.copy()
    h, w = canvas.shape[:2]
    s = w / 1280.0

    if obs is not None:
        if obs.tag_read.points is not None:
            pts = np.asarray(obs.tag_read.points).reshape(-1, 2).astype(np.int32)
            color = (0, 200, 255) if obs.tag_read.damaged else (0, 255, 0)
            cv2.polylines(canvas, [pts], True, color, max(2, int(3 * s)))
        for d in obs.detections:
            if d.box:
                x1, y1, x2, y2 = d.box
                cv2.rectangle(canvas, (x1, y1), (x2, y2), (255, 200, 0), 2)
                cv2.putText(canvas, f"{d.label} {d.confidence:.2f}", (x1, max(20, y1 - 6)),
                            FONT, 0.6 * s, (255, 200, 0), 2)

    bar = int(150 * s)
    if decision is not None:
        cv2.rectangle(canvas, (0, h - bar), (w, h), COLORS[decision.bin], -1)
        cv2.putText(canvas, decision.bin_name, (int(30 * s), h - int(80 * s)),
                    FONT, 2.2 * s, (255, 255, 255), max(2, int(5 * s)))
        cv2.putText(canvas, decision.material_name, (int(30 * s), h - int(38 * s)),
                    FONT, 0.9 * s, (255, 255, 255), 2)
        cv2.putText(canvas, decision.reason, (int(30 * s), h - int(10 * s)),
                    FONT, 0.6 * s, (230, 230, 230), 1)
        hint = "Lid is open - drop it in" if state == "OPEN" else ""
        cv2.putText(canvas, hint, (int(w * 0.55), h - int(80 * s)), FONT, 0.9 * s, (255, 255, 255), 2)
    else:
        cv2.rectangle(canvas, (0, h - int(60 * s)), (w, h), (30, 30, 30), -1)
        msg = "Hold the item up to the camera"
        if obs is not None and obs.tag_read.damaged:
            msg = "Tag is damaged - checking the item itself..."
        elif obs is not None and (obs.present or obs.detections):
            msg = "Looking..."
        cv2.putText(canvas, msg, (int(30 * s), h - int(20 * s)), FONT, 0.9 * s, (255, 255, 255), 2)

    status = f"ESP32 {'OK' if link_ok else 'OFFLINE'} | vision {'ON' if vision_ok else 'OFF (tag only)'}"
    cv2.putText(canvas, status, (int(15 * s), int(30 * s)), FONT, 0.6 * s,
                (0, 255, 0) if link_ok else (0, 0, 255), 2)
    return canvas


class Screen:
    def __init__(self, enabled: bool = True, fullscreen: bool = False):
        self.enabled = enabled
        if enabled:
            cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
            if fullscreen:
                cv2.setWindowProperty(WINDOW, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

    def show(self, canvas: np.ndarray) -> bool:
        """Draw the frame. Returns False when the user presses q or Esc."""
        if not self.enabled:
            return True
        cv2.imshow(WINDOW, canvas)
        return (cv2.waitKey(1) & 0xFF) not in (ord("q"), 27)

    def close(self) -> None:
        if self.enabled:
            cv2.destroyAllWindows()
