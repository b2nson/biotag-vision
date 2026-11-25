"""USB webcam and a mock camera for development without hardware."""
from __future__ import annotations

import time
from pathlib import Path
from typing import List, Optional, Sequence

import cv2
import numpy as np

from ..types import Frame
from .base import Camera, CameraError


class UsbCamera(Camera):
    name = "usb"

    def __init__(self, width=1280, height=720, fps=30, device=0):
        self.width, self.height, self.fps, self.device = width, height, fps, device
        self._cap: Optional[cv2.VideoCapture] = None

    def open(self) -> None:
        self._cap = cv2.VideoCapture(self.device)
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self._cap.set(cv2.CAP_PROP_FPS, self.fps)
        if not self._cap.isOpened():
            raise CameraError(f"USB camera {self.device} did not open (try `ls /dev/video*`).")

    def read(self) -> Optional[Frame]:
        ok, image = self._cap.read()
        return Frame(image, time.monotonic()) if ok else None

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None


class MockCamera(Camera):
    """Cycles through image files in a folder, or through arrays given directly."""
    name = "mock"

    def __init__(self, path: Optional[str] = None, images: Optional[Sequence[np.ndarray]] = None,
                 hold_frames: int = 30):
        self.path, self.hold_frames = path, hold_frames
        self._images: List[np.ndarray] = list(images) if images is not None else []
        self._n = 0

    def open(self) -> None:
        if not self._images and self.path and Path(self.path).is_dir():
            for f in sorted(Path(self.path).iterdir()):
                if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".bmp"):
                    img = cv2.imread(str(f))
                    if img is not None:
                        self._images.append(img)
        if not self._images:
            raise CameraError(f"mock camera: no images in '{self.path}'")

    def set_images(self, images: Sequence[np.ndarray]) -> None:
        self._images, self._n = list(images), 0

    def read(self) -> Optional[Frame]:
        image = self._images[(self._n // self.hold_frames) % len(self._images)]
        self._n += 1
        return Frame(image.copy(), time.monotonic())

    def close(self) -> None:
        pass
