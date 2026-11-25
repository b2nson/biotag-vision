"""ESP32-CAM over Wi-Fi (firmware/esp32cam_stream).

Reads the MJPEG stream at http://<ip>:81/stream in a background thread and
always hands back the newest frame, so a slow consumer never builds up lag.
Reconnects by itself if Wi-Fi drops.
"""
from __future__ import annotations

import logging
import threading
import time
import urllib.request
from typing import Optional
from urllib.parse import urlparse

import cv2
import numpy as np

from ..types import Frame
from .base import Camera, CameraError

log = logging.getLogger("biotag.esp32cam")
SOI, EOI = b"\xff\xd8", b"\xff\xd9"


class Esp32Camera(Camera):
    name = "esp32cam"

    def __init__(self, url="http://192.168.4.1", stream_port=81, open_timeout_s=8.0):
        parsed = urlparse(url if "://" in url else "http://" + url)
        self.base = f"{parsed.scheme}://{parsed.hostname}"
        self.stream_url = f"{parsed.scheme}://{parsed.hostname}:{stream_port}/stream"
        self.open_timeout_s = open_timeout_s
        self._latest: Optional[Frame] = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def open(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="esp32cam", daemon=True)
        self._thread.start()
        deadline = time.monotonic() + self.open_timeout_s
        while time.monotonic() < deadline:
            if self._latest is not None:
                return
            time.sleep(0.05)
        self.close()
        raise CameraError(
            f"no frames from {self.stream_url}. Check the ESP32-CAM IP (printed on its serial "
            "port at boot), that the Jetson is on the same Wi-Fi, and that nothing else "
            "(a browser tab) is holding the stream open."
        )

    def set_led(self, on: bool) -> None:
        """Switch the ESP32-CAM's on-board flash LED."""
        try:
            urllib.request.urlopen(f"{self.base}/led?on={int(on)}", timeout=2).read()
        except Exception as exc:
            log.warning("LED request failed: %s", exc)

    def read(self) -> Optional[Frame]:
        with self._lock:
            frame = self._latest
        if frame is not None and time.monotonic() - frame.timestamp > 2.0:
            return None                      # stale: stream has stalled
        return frame

    def close(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        self._latest = None

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                with urllib.request.urlopen(self.stream_url, timeout=5) as stream:
                    buf = b""
                    while not self._stop.is_set():
                        chunk = stream.read(4096)
                        if not chunk:
                            break
                        buf += chunk
                        while True:
                            start = buf.find(SOI)
                            end = buf.find(EOI, start + 2) if start >= 0 else -1
                            if end < 0:
                                if len(buf) > 2_000_000:
                                    buf = b""
                                break
                            jpg, buf = buf[start:end + 2], buf[end + 2:]
                            image = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
                            if image is not None:
                                with self._lock:
                                    self._latest = Frame(image, time.monotonic())
            except Exception as exc:
                log.warning("stream error: %s - reconnecting", exc)
            self._stop.wait(1.0)
