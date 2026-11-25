"""Vision fallback: identify the item itself when the tag is unreadable or absent.

Wraps an Ultralytics YOLO model. On the Jetson use a TensorRT `.engine`
exported with tools/train.py; `.onnx` and `.pt` also load (slower).
Both detection and classification models work.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

import numpy as np

from .types import Detection

log = logging.getLogger("biotag.classifier")


class Classifier:
    def __init__(self, model_path: Path, label_map: dict, imgsz: int = 640, min_conf: float = 0.25):
        from ultralytics import YOLO

        self.model = YOLO(str(model_path))
        self.label_map = {k.lower(): v.upper() for k, v in label_map.items()}
        self.imgsz, self.min_conf = imgsz, min_conf
        self._warned = set()

    def _material(self, label: str) -> Optional[str]:
        material = self.label_map.get(label.lower())
        if material is None and label not in self._warned:
            self._warned.add(label)
            log.warning("model class '%s' is not in classifier.label_map - ignored", label)
        return material

    def detect(self, image: np.ndarray) -> List[Detection]:
        result = self.model.predict(image, imgsz=self.imgsz, conf=self.min_conf, verbose=False)[0]
        names = result.names
        out: List[Detection] = []
        if getattr(result, "probs", None) is not None:          # classification model
            conf = float(result.probs.top1conf)
            label = names[int(result.probs.top1)]
            material = self._material(label)
            if material and conf >= self.min_conf:
                out.append(Detection(material, conf, label))
            return out
        for box in result.boxes:                                 # detection model
            label = names[int(box.cls)]
            material = self._material(label)
            if material:
                x1, y1, x2, y2 = (int(v) for v in box.xyxy[0].tolist())
                out.append(Detection(material, float(box.conf), label, (x1, y1, x2, y2)))
        out.sort(key=lambda d: d.confidence, reverse=True)
        return out


def load_classifier(cfg: dict, model_path: Path) -> Optional[Classifier]:
    """Return a classifier, or None (tag-only mode) if it cannot be loaded."""
    c = cfg["classifier"]
    if not c["enabled"]:
        return None
    if not model_path.exists():
        log.warning("model %s not found - running TAG-ONLY (no vision fallback)", model_path)
        return None
    try:
        return Classifier(model_path, c["label_map"], c["imgsz"], c["min_conf"])
    except Exception as exc:
        log.warning("could not load vision model (%s) - running TAG-ONLY", exc)
        return None
