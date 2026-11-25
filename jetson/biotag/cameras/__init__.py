"""Camera drivers. `create_camera(cfg)` picks one from config.yaml."""
from __future__ import annotations

from .base import Camera, CameraError

__all__ = ["Camera", "CameraError", "create_camera"]


def create_camera(cfg: dict, base_dir: str = ".") -> Camera:
    c = cfg["camera"]
    kind = c["type"].lower()
    size = dict(width=c["width"], height=c["height"], fps=c["fps"])
    if kind in ("csi", "picam", "pi"):
        from .csi import CsiCamera
        return CsiCamera(**size, **c["csi"])
    if kind == "zed":
        from .zed import ZedCamera
        return ZedCamera(**size, **c["zed"])
    if kind in ("esp32cam", "esp32"):
        from .esp32cam import Esp32Camera
        return Esp32Camera(**c["esp32cam"])
    if kind == "usb":
        from .simple import UsbCamera
        return UsbCamera(**size, **c["usb"])
    if kind == "mock":
        import os
        from .simple import MockCamera
        path = c["mock"]["path"]
        return MockCamera(path if os.path.isabs(path) else os.path.join(base_dir, path))
    raise CameraError(f"unknown camera.type '{kind}' (use csi, zed, esp32cam, usb or mock)")
