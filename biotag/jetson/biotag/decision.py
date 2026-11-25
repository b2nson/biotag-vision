"""Decide which lid to open. Pure logic, no hardware - see tests/test_decision.py.

Priority:
  1. A decoded tag wins immediately (QR codes carry their own error check).
  2. Otherwise the vision model must agree with itself over several frames,
     in at least `min_share` of recent frames, and only after the tag has had `tag_grace_s` to come into view.
  3. If something is in front of the camera for `unsure_after_s` and is still
     unidentified, it goes to landfill ("when in doubt, throw it out").
  4. Food / liquid contamination seen on a recyclable reroutes it to landfill.
"""
from __future__ import annotations

from collections import deque
from typing import Deque, Optional, Tuple

from .materials import Materials
from .types import Decision, Observation

CONTAM = "CONTAM"


class DecisionEngine:
    def __init__(self, cfg: dict, materials: Materials):
        self.cfg = cfg
        self.materials = materials
        self._votes: Deque[Tuple[float, str, float]] = deque()
        self._frames: Deque[float] = deque()
        self.reset()

    def reset(self) -> None:
        self._votes.clear()
        self._first_seen: Optional[float] = None
        self._last_seen: Optional[float] = None
        self._contam_at: Optional[float] = None
        self._tag_damaged = False

    # ------------------------------------------------------------------
    def update(self, obs: Observation, now: float) -> Optional[Decision]:
        c = self.cfg
        self._frames.append(now)
        while self._frames and now - self._frames[0] > c["window_s"]:
            self._frames.popleft()
        strong = [d for d in obs.detections if d.confidence >= c["accept_conf"]]
        if any(d.material == CONTAM for d in strong):
            self._contam_at = now

        # 1. tag
        tag = obs.tag_read.tag
        if tag is not None:
            material = tag.material if self.materials.known(tag.material) else "UNKNOWN"
            bin_id = self.materials.bin_for(tag.material, tag.bin)
            return self._finish(bin_id, material if material != "UNKNOWN" else tag.material,
                                "tag", 1.0, "BioTag read", now, tag.item_id)

        # presence bookkeeping
        something = obs.present or obs.tag_read.damaged or bool(obs.detections)
        if not something:
            if self._last_seen is not None and now - self._last_seen > c["absent_reset_s"]:
                self.reset()
            return None
        if self._first_seen is None:
            self._first_seen = now
        self._last_seen = now
        self._tag_damaged = self._tag_damaged or obs.tag_read.damaged

        # 2. vision voting (contamination is tracked separately, not voted on)
        items = [d for d in obs.detections if d.material != CONTAM]
        if items:
            best = max(items, key=lambda d: d.confidence)
            self._votes.append((now, best.material, best.confidence))
        while self._votes and now - self._votes[0][0] > c["window_s"]:
            self._votes.popleft()

        waited = now - self._first_seen
        if waited >= c["tag_grace_s"] and self._votes:
            tally = {}
            for _, material, conf in self._votes:
                tally.setdefault(material, []).append(conf)
            material, confs = max(tally.items(), key=lambda kv: (len(kv[1]), sum(kv[1])))
            mean = sum(confs) / len(confs)
            steady = len(confs) >= c["min_share"] * len(self._frames)   # not just a flicker
            if len(confs) >= c["min_votes"] and steady and mean >= c["accept_conf"]:
                why = "Tag damaged - identified by camera" if self._tag_damaged \
                    else "No tag - identified by camera"
                return self._finish(self.materials.bin_for(material), material,
                                    "vision", mean, why, now)

        # 3. unsure
        if waited >= c["unsure_after_s"]:
            why = "Tag unreadable, item not recognised" if self._tag_damaged \
                else "Item not recognised"
            return Decision("L", "UNKNOWN", self.materials.name("UNKNOWN"), "unsure", 0.0, why)
        return None

    # ------------------------------------------------------------------
    def _finish(self, bin_id, material, source, conf, reason, now, item_id=None) -> Decision:
        c = self.cfg
        contaminated = self._contam_at is not None and now - self._contam_at <= c["window_s"]
        if c["contamination_reroutes"] and contaminated and bin_id == "R":
            bin_id = "L"
            reason += " - food/liquid residue, cannot be recycled"
        return Decision(bin_id, material, self.materials.name(material), source, conf, reason, item_id)
