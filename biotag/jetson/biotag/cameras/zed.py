"""Stereolabs ZED 2 stereo camera (USB 3.0).

Two modes:
  use_sdk=True   ZED SDK + pyzed. Gives the left image AND a depth map, which
                 the presence detector uses to tell when an item is held up.
  use_sdk=False  Plain UVC. The ZED shows up as one wide side-by-side image;
                 the left half is used. No depth, no SDK needed.
"""
from __future__ import annotations

import time
from typing import Optional

import cv2
import numpy as np

from ..types import Frame
from .base import Camera, CameraError


class ZedCamera(Camera):
    name = "zed"

    def __init__(self, width=1280, height=720, fps=30, use_sdk=True, device=0, depth=True):
        self.width, self.height, self.fps = width, height, fps
        self.use_sdk, self.device, self.want_depth = use_sdk, device, depth
        self._zed = None
        self._sl = None
        self._cap: Optional[cv2.VideoCapture] = None

    # ---- open ------------------------------------------------------------
    def open(self) -> None:
        if self.use_sdk:
            try:
                import pyzed.sl as sl
            except ImportError as exc:
                raise CameraError(
                    "pyzed not found. Install the ZED SDK for your JetPack version "
                    "(stereolabs.com/developers/release) or set camera.zed.use_sdk: false"
                ) from exc
            self._open_sdk(sl)
        else:
            self._open_uvc()

    def _open_sdk(self, sl) -> None:
        self._sl = sl
        init = sl.InitParameters()
        res = {2208: "HD2K", 1920: "HD1080", 1280: "HD720", 672: "VGA"}.get(self.width, "HD720")
        init.camera_resolution = getattr(sl.RESOLUTION, res)
        init.camera_fps = self.fps
        init.coordinate_units = sl.UNIT.METER
        if self.want_depth:
            # mode names changed between SDK 3/4/5 - take the first that exists
            for mode in ("NEURAL_LIGHT", "PERFORMANCE", "NEURAL"):
                if hasattr(sl.DEPTH_MODE, mode):
                    init.depth_mode = getattr(sl.DEPTH_MODE, mode)
                    break
            init.depth_minimum_distance = 0.2
        else:
            init.depth_mode = sl.DEPTH_MODE.NONE
        self._zed = sl.Camera()
        status = self._zed.open(init)
        if status != sl.ERROR_CODE.SUCCESS:
            self._zed = None
            raise CameraError(f"ZED open failed: {status}. Use a USB 3.0 (blue) port and cable.")
        self._runtime = sl.RuntimeParameters()
        self._image, self._depth = sl.Mat(), sl.Mat()

    def _open_uvc(self) -> None:
        self._cap = cv2.VideoCapture(self.device, cv2.CAP_V4L2)
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width * 2)   # side-by-side
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self._cap.set(cv2.CAP_PROP_FPS, self.fps)
        if not self._cap.isOpened():
            raise CameraError(f"ZED (UVC) /dev/video{self.device} did not open.")

    # ---- read ------------------------------------------------------------
    def read(self) -> Optional[Frame]:
        if self._zed is not None:
            sl = self._sl
            if self._zed.grab(self._runtime) != sl.ERROR_CODE.SUCCESS:
                return None
            self._zed.retrieve_image(self._image, sl.VIEW.LEFT)
            image = cv2.cvtColor(self._image.get_data(), cv2.COLOR_BGRA2BGR)
            depth = None
            if self.want_depth:
                self._zed.retrieve_measure(self._depth, sl.MEASURE.DEPTH)
                depth = np.array(self._depth.get_data(), dtype=np.float32, copy=True)
            return Frame(image, time.monotonic(), depth)
        ok, wide = self._cap.read()
        if not ok:
            return None
        return Frame(np.ascontiguousarray(wide[:, : wide.shape[1] // 2]), time.monotonic())

    def close(self) -> None:
        if self._zed is not None:
            self._zed.close()
            self._zed = None
        if self._cap is not None:
            self._cap.release()
            self._cap = None
