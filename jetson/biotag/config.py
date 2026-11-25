"""Configuration: defaults here, overridden by config.yaml."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Optional

DEFAULTS = {
    "camera": {
        "type": "csi",            # csi | zed | esp32cam | usb | mock
        "width": 1280,
        "height": 720,
        "fps": 30,
        "csi": {"sensor_id": 0, "flip_method": 0},
        "zed": {
            "use_sdk": True,      # False = plain UVC, left image only, no depth
            "device": 0,
            "depth": True,
        },
        "esp32cam": {"url": "http://192.168.4.1", "stream_port": 81},
        "usb": {"device": 0},
        "mock": {"path": "samples"},
    },
    "link": {
        "enabled": True,
        "port": "/dev/ttyTHS1",   # 40-pin header UART. USB cable: /dev/ttyUSB0
        "baud": 115200,
        "ack_timeout_s": 0.3,
        "retries": 3,
        "heartbeat_s": 2.0,
    },
    "tag": {
        "prefix": "BT1",
        "enhance": True,          # retry decode on enhanced images
    },
    "classifier": {
        "enabled": True,
        "model": "models/biotag.engine",   # .engine (TensorRT), .onnx or .pt
        "imgsz": 640,
        "min_conf": 0.25,         # below this a detection is ignored
        "label_map": {            # model class name -> material code
            "cardboard": "CARDBOARD",
            "paper": "PAPER",
            "glass": "GLASS",
            "metal": "ALU",
            "can": "ALU",
            "plastic": "PLASTIC",
            "bottle": "PET",
            "trash": "MIXED",
            "organic": "FOOD",
            "biodegradable": "FOOD",
            "food_stain": "CONTAM",
            "liquid": "CONTAM",
        },
    },
    "decision": {
        "tag_grace_s": 0.7,       # give the tag this long before trusting vision
        "window_s": 1.5,          # vision votes older than this are dropped
        "min_votes": 4,           # frames that must agree
        "min_share": 0.5,         # ...and the share of recent frames they must make up
        "accept_conf": 0.65,      # mean confidence needed to accept vision
        "unsure_after_s": 3.0,    # item present this long, still unknown -> landfill
        "absent_reset_s": 0.5,
        "contamination_reroutes": True,
    },
    "presence": {
        "roi": 0.6,               # central fraction of the frame that is checked
        "depth_min_m": 0.20,
        "depth_max_m": 0.80,
        "depth_fraction": 0.08,
        "diff_threshold": 12.0,
    },
    "lid": {
        "open_ms": 8000,          # lid closes after this if nothing is dropped in
        "cooldown_s": 1.5,
    },
    "materials": {
        "file": "materials.json",
        "local_overrides": {},    # e.g. {"PLA": "L"} if your hauler rejects PLA
    },
    "display": {"enabled": True, "fullscreen": False},
    "log": {"csv": "logs/decisions.csv"},
}


def _merge(base: dict, extra: dict) -> dict:
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict) and key not in (
            "label_map", "local_overrides"
        ):
            _merge(base[key], value)
        else:
            base[key] = value
    return base


def load(path: Optional[str] = None) -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    if path:
        import yaml

        with open(path, "r", encoding="utf-8") as fh:
            _merge(cfg, yaml.safe_load(fh) or {})
        cfg["_dir"] = str(Path(path).resolve().parent)
    else:
        cfg["_dir"] = str(Path.cwd())
    return cfg


def resolve(cfg: dict, relative: str) -> Path:
    """Resolve a path from the config relative to the config file."""
    p = Path(relative)
    return p if p.is_absolute() else Path(cfg["_dir"]) / p
