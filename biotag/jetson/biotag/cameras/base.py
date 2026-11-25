"""Camera interface. Every driver returns BGR frames through the same API."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from ..types import Frame


class CameraError(RuntimeError):
    pass


class Camera(ABC):
    name = "camera"

    @abstractmethod
    def open(self) -> None:
        """Start the camera. Raise CameraError with a useful hint on failure."""

    @abstractmethod
    def read(self) -> Optional[Frame]:
        """Return the newest frame, or None if none is available yet."""

    @abstractmethod
    def close(self) -> None:
        ...

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *exc):
        self.close()
