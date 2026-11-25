"""Raspberry Pi Camera on the Jetson's MIPI-CSI connector.

Supported sensors on the Orin Nano: IMX219 (Pi Camera v2) and IMX477 (Pi HQ
Camera). The Pi Camera v3 (IMX708) has no stock NVIDIA driver. See
docs/cameras.md for the ribbon cable and jetson-io steps.

Frames come through GStreamer (nvarguscamerasrc), so OpenCV must be built with
GStreamer - the JetPack OpenCV is; `pip install opencv-python` is NOT.
"""
from __future__ import annotations

import time
from typing import Optional

import cv2

from ..types import Frame
from .base import Camera, CameraError


def gstreamer_pipeline(sensor_id=0, width=1280, height=720, fps=30, flip_method=0) -> str:
    return (
        f"nvarguscamerasrc sensor-id={sensor_id} ! "
        f"video/x-raw(memory:NVMM), width=(int){width}, height=(int){height}, "
        f"framerate=(fraction){fps}/1 ! "
        f"nvvidconv flip-method={flip_method} ! "
        f"video/x-raw, format=(string)BGRx ! videoconvert ! "
        f"video/x-raw, format=(string)BGR ! "
        f"appsink drop=true max-buffers=1 sync=false"
    )


class CsiCamera(Camera):
    name = "csi"

    def __init__(self, width=1280, height=720, fps=30, sensor_id=0, flip_method=0):
        self.pipeline = gstreamer_pipeline(sensor_id, width, height, fps, flip_method)
        self._cap: Optional[cv2.VideoCapture] = None

    def open(self) -> None:
        self._cap = cv2.VideoCapture(self.pipeline, cv2.CAP_GSTREAMER)
        if not self._cap.isOpened():
            raise CameraError(
                "CSI camera did not open. Check: (1) ribbon cable orientation and that the "
                "sensor is enabled with `sudo /opt/nvidia/jetson-io/jetson-io.py`, "
                "(2) `ls /dev/video*` shows the sensor, (3) OpenCV has GStreamer: "
                "python3 -c \"import cv2; print(cv2.getBuildInformation())\" | grep GStreamer"
            )

    def read(self) -> Optional[Frame]:
        ok, image = self._cap.read()
        return Frame(image, time.monotonic()) if ok else None

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
