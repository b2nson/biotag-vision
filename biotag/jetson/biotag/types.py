"""Shared data types."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np

BINS = {"R": "RECYCLE", "C": "COMPOST", "L": "LANDFILL"}


@dataclass
class Frame:
    """One camera frame. `depth` is metres (float32) or None."""
    image: np.ndarray
    timestamp: float
    depth: Optional[np.ndarray] = None


@dataclass
class Tag:
    """A successfully decoded BioTag."""
    item_id: str
    material: str
    bin: str
    raw: str


@dataclass
class TagRead:
    """Result of looking for a tag in one frame."""
    tag: Optional[Tag] = None
    damaged: bool = False          # a tag was located but could not be decoded
    points: Optional[np.ndarray] = None


@dataclass
class Detection:
    """One vision-model result, already mapped to a material code."""
    material: str
    confidence: float
    label: str = ""
    box: Optional[tuple] = None    # x1, y1, x2, y2


@dataclass
class Observation:
    """Everything learned from one frame."""
    tag_read: TagRead = field(default_factory=TagRead)
    detections: List[Detection] = field(default_factory=list)
    present: bool = False


@dataclass
class Decision:
    bin: str                       # R, C or L
    material: str                  # material code, e.g. PET
    material_name: str
    source: str                    # tag | vision | unsure
    confidence: float
    reason: str
    item_id: Optional[str] = None

    @property
    def bin_name(self) -> str:
        return BINS[self.bin]
