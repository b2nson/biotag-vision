"""BioTag bin application.

    python3 -m biotag.main --config config.yaml
    python3 -m biotag.main --camera zed
    python3 -m biotag.main --camera mock --no-link --headless     (desk test)

States:  IDLE -> (decision) -> OPEN -> (ESP32 reports lid closed) -> COOLDOWN -> IDLE
"""
from __future__ import annotations

import argparse
import csv
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import config as config_mod
from .cameras import Camera, create_camera
from .classifier import load_classifier
from .decision import DecisionEngine
from .display import Screen, render
from .esp32_link import Esp32Link, NullLink
from .materials import Materials
from .presence import PresenceDetector
from .tag_reader import TagReader
from .types import Decision, Observation

log = logging.getLogger("biotag")


class App:
    def __init__(self, cfg: dict, camera: Camera, link, classifier=None, screen: Optional[Screen] = None):
        self.cfg, self.camera, self.link, self.classifier = cfg, camera, link, classifier
        self.screen = screen
        materials_file = config_mod.resolve(cfg, cfg["materials"]["file"])
        self.materials = Materials(materials_file if materials_file.exists() else None,
                                   cfg["materials"]["local_overrides"])
        self.reader = TagReader(cfg["tag"]["prefix"], cfg["tag"]["enhance"])
        self.engine = DecisionEngine(cfg["decision"], self.materials)
        self.presence = PresenceDetector(cfg["presence"])
        self.state = "IDLE"
        self.decision: Optional[Decision] = None
        self.history = []
        self._t_state = 0.0
        self._obs: Optional[Observation] = None
        self._last_ts: Optional[float] = None
        self._last_item: Optional[str] = None

    # ------------------------------------------------------------------
    def step(self) -> bool:
        """Process one frame. Returns False when the user asks to quit."""
        frame = self.camera.read()
        if frame is None or frame.timestamp == self._last_ts:
            time.sleep(0.005)             # nothing new (ESP32-CAM is slower than this loop)
            return True
        self._last_ts = frame.timestamp
        now = time.monotonic()

        for event in self.link.poll_events():
            log.info("ESP32 event: %s", ",".join(event))
            if event[:2] == ["EVT", "CLOSED"] and self.state == "OPEN":
                self._enter("COOLDOWN", now)
            elif event[:2] == ["EVT", "BOOT"] and self.state == "OPEN":
                log.warning("ESP32 rebooted while a lid was open")
                self._enter("COOLDOWN", now)

        if self.state == "IDLE":
            tag_read = self.reader.read(frame.image)
            if tag_read.tag is None:
                self._last_item = None
            elif tag_read.tag.item_id == self._last_item:
                return self._show(frame)   # same sticker still in view: don't reopen
            detections = []
            if tag_read.tag is None and self.classifier is not None:
                detections = self.classifier.detect(frame.image)
            self._obs = Observation(tag_read, detections, self.presence.update(frame))
            decision = self.engine.update(self._obs, now)
            if decision is not None:
                self._act(decision, now)
        elif self.state == "OPEN":
            limit = self.cfg["lid"]["open_ms"] / 1000.0 + 5.0
            if now - self._t_state > limit:          # ESP32 never reported back
                log.warning("no CLOSED event - forcing lids shut")
                self.link.close_lid("A")
                self._enter("COOLDOWN", now)
        elif self.state == "COOLDOWN":
            if now - self._t_state > self.cfg["lid"]["cooldown_s"]:
                self.engine.reset()
                self.presence.rebase()
                self.decision, self._obs = None, None
                self._enter("IDLE", now)

        return self._show(frame)

    def _show(self, frame) -> bool:
        if self.screen is not None:
            canvas = render(frame.image, self.state, self.decision,
                            self._obs if self.state == "IDLE" else None,
                            self.link.connected, self.classifier is not None)
            return self.screen.show(canvas)
        return True

    # ------------------------------------------------------------------
    def _enter(self, state: str, now: float) -> None:
        self.state, self._t_state = state, now

    def _act(self, decision: Decision, now: float) -> None:
        self.decision = decision
        self._last_item = decision.item_id
        self.history.append(decision)
        log.info("%s <- %s (%s, %.2f) %s", decision.bin_name, decision.material,
                 decision.source, decision.confidence, decision.reason)
        self._log_csv(decision)
        if self.link.open_lid(decision.bin, self.cfg["lid"]["open_ms"]):
            self._enter("OPEN", now)
        else:
            log.error("ESP32 did not acknowledge OPEN - lid stays closed")
            self._enter("COOLDOWN", now)

    def _log_csv(self, d: Decision) -> None:
        target = self.cfg["log"].get("csv")
        if not target:
            return
        path = config_mod.resolve(self.cfg, target)
        path.parent.mkdir(parents=True, exist_ok=True)
        new = not path.exists()
        with open(path, "a", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            if new:
                writer.writerow(["time", "bin", "material", "source", "confidence", "item_id", "reason"])
            writer.writerow([datetime.now().isoformat(timespec="seconds"), d.bin, d.material,
                             d.source, f"{d.confidence:.2f}", d.item_id or "", d.reason])

    def run(self) -> None:
        try:
            while self.step():
                pass
        except KeyboardInterrupt:
            pass
        finally:
            self.link.close_lid("A")


def main() -> None:
    ap = argparse.ArgumentParser(description="BioTag smart bin")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--camera", help="override camera.type: csi | zed | esp32cam | usb | mock")
    ap.add_argument("--port", help="override link.port, e.g. /dev/ttyUSB0")
    ap.add_argument("--no-link", action="store_true", help="run without an ESP32")
    ap.add_argument("--headless", action="store_true", help="no display window")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    cfg = config_mod.load(args.config if Path(args.config).exists() else None)
    if args.camera:
        cfg["camera"]["type"] = args.camera
    if args.port:
        cfg["link"]["port"] = args.port

    lk = cfg["link"]
    if args.no_link or not lk["enabled"]:
        link = NullLink()
    else:
        link = Esp32Link(lk["port"], lk["baud"], lk["ack_timeout_s"], lk["retries"], lk["heartbeat_s"]).start()
        if not link.wait_connected(5.0):
            log.warning("ESP32 not answering on %s yet - will keep trying", lk["port"])

    classifier = load_classifier(cfg, config_mod.resolve(cfg, cfg["classifier"]["model"]))
    camera = create_camera(cfg, cfg["_dir"])
    screen = None if (args.headless or not cfg["display"]["enabled"]) else \
        Screen(True, cfg["display"]["fullscreen"])

    with camera:
        log.info("camera '%s' ready", camera.name)
        App(cfg, camera, link, classifier, screen).run()
    link.stop()
    if screen:
        screen.close()


if __name__ == "__main__":
    main()
