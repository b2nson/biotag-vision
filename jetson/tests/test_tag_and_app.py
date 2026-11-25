"""Tag decoding on synthetic images, the serial link against a simulated ESP32,
and the whole application loop with a mock camera."""
import copy
import sys
import time

import cv2
import numpy as np
import pytest

from biotag.cameras.simple import MockCamera
from biotag.config import DEFAULTS
from biotag.esp32_link import Esp32Link
from biotag.main import App
from biotag.tag_reader import TagReader, make_payload, parse_payload
from tools.generate_tags import make_tag

needs_pty = pytest.mark.skipif(sys.platform == "win32", reason="needs a pseudo-terminal")


def frame_with_tag(material="PET", bin_id="R", size=300):
    tag = cv2.cvtColor(np.array(make_tag("000042", material, bin_id)), cv2.COLOR_RGB2BGR)
    tag = cv2.resize(tag, (size, int(size * tag.shape[0] / tag.shape[1])))
    frame = np.full((720, 1280, 3), 150, np.uint8)
    frame[200:200 + tag.shape[0], 500:500 + tag.shape[1]] = tag
    return frame


def empty_frame():
    return np.full((720, 1280, 3), 150, np.uint8)


# ---- tag ------------------------------------------------------------------
def test_payload_round_trip():
    tag = parse_payload(make_payload("000042", "pet", "r"))
    assert (tag.item_id, tag.material, tag.bin) == ("000042", "PET", "R")


@pytest.mark.parametrize("text", ["", "hello", "BT1:1:PET", "BT1:1:PET:X", "XX1:1:PET:R",
                                  "https://example.com", "BT1::PET:R"])
def test_payload_rejects_other_codes(text):
    assert parse_payload(text) is None


def test_reads_clean_tag():
    read = TagReader().read(frame_with_tag("ALU", "R"))
    assert read.tag.material == "ALU" and read.tag.item_id == "000042" and not read.damaged


def test_no_tag_in_empty_frame():
    read = TagReader().read(empty_frame())
    assert read.tag is None and not read.damaged


def test_reads_faded_tag_with_enhancement():
    frame = frame_with_tag().astype(np.float32)
    faded = np.clip(255 - (255 - frame) * 0.2, 0, 255).astype(np.uint8)   # 80% of the ink gone
    assert TagReader(enhance=True).read(faded).tag is not None


def test_destroyed_tag_is_not_decoded():
    frame = frame_with_tag()
    frame[200:520, 500:700] = 60            # two thirds of the code covered
    assert TagReader().read(frame).tag is None


# ---- link -----------------------------------------------------------------
@pytest.fixture
def sim():
    from tools.esp32_sim import Esp32Sim

    s = Esp32Sim(deposit_after_s=0.2, close_delay_s=0.1).start()
    yield s
    s.stop()


def wait_event(link, prefix, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for ev in link.poll_events():
            if ev[:len(prefix)] == prefix:
                return ev
        time.sleep(0.01)
    return None


@needs_pty
def test_link_ping_open_deposit_close(sim):
    link = Esp32Link(sim.port, heartbeat_s=0.2).start()
    try:
        assert link.wait_connected(3)
        assert link.status() == ["0", "0", "0"]
        assert link.open_lid("C", 5000)
        assert link.status() == ["0", "1", "0"]
        assert wait_event(link, ["EVT", "CLOSED", "C"]) == ["EVT", "CLOSED", "C", "DEPOSIT"]
        assert ["OPEN", "C", "5000"] in sim.received
    finally:
        link.stop()


@needs_pty
def test_link_retries_after_lost_frame(sim):
    sim.drop_first_n = 1
    link = Esp32Link(sim.port, heartbeat_s=0.2, ack_timeout_s=0.2).start()
    try:
        assert link.wait_connected(3)
        assert link.open_lid("R", 5000)             # first attempt is swallowed
    finally:
        link.stop()


@needs_pty
def test_link_reports_busy(sim):
    sim.deposit_after_s = None
    link = Esp32Link(sim.port, heartbeat_s=0.2).start()
    try:
        assert link.wait_connected(3)
        assert link.open_lid("R", 5000)
        assert not link.open_lid("L", 5000)         # only one lid at a time
        assert link.close_lid("A")
        assert wait_event(link, ["EVT", "CLOSED", "R"])[3] == "CMD"
    finally:
        link.stop()


@needs_pty
def test_link_timeout_when_nothing_dropped(sim):
    sim.deposit_after_s = None
    link = Esp32Link(sim.port, heartbeat_s=0.2).start()
    try:
        assert link.wait_connected(3)
        assert link.open_lid("L", 300)
        assert wait_event(link, ["EVT", "CLOSED", "L"])[3] == "TIMEOUT"
    finally:
        link.stop()


def test_link_survives_missing_port():
    link = Esp32Link("/dev/does-not-exist", heartbeat_s=0.1, ack_timeout_s=0.05, retries=1).start()
    try:
        assert not link.wait_connected(0.3)
        assert not link.open_lid("R", 1000)
    finally:
        link.stop()


# ---- whole application ----------------------------------------------------
def make_app(sim, tmp_path, images):
    cfg = copy.deepcopy(DEFAULTS)
    cfg["_dir"] = str(tmp_path)
    cfg["lid"]["cooldown_s"] = 0.2
    cfg["decision"]["unsure_after_s"] = 0.6
    link = Esp32Link(sim.port, heartbeat_s=0.2).start()
    assert link.wait_connected(3)
    cam = MockCamera(images=images, hold_frames=10_000)
    cam.open()
    return App(cfg, cam, link), cam, link


def step_until(app, condition, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.step()
        if condition():
            return True
    return False


@needs_pty
def test_app_full_cycle_with_tag(sim, tmp_path):
    app, cam, link = make_app(sim, tmp_path, [frame_with_tag("PLA", "C")])
    try:
        assert step_until(app, lambda: app.state == "OPEN")
        assert app.decision.bin == "C" and app.decision.source == "tag"
        assert sim.received[-1][:2] == ["OPEN", "C"]
        cam.set_images([empty_frame()])                       # item dropped in
        assert step_until(app, lambda: app.state == "IDLE")   # lid closed, cooled down
        assert (tmp_path / "logs" / "decisions.csv").read_text().count("PLA") == 1
        for _ in range(30):                                   # empty scene: stays idle
            app.step()
        assert app.state == "IDLE" and len(app.history) == 1
    finally:
        link.stop()


@needs_pty
def test_app_unknown_item_goes_to_landfill(sim, tmp_path):
    app, cam, link = make_app(sim, tmp_path, [empty_frame()])
    try:
        for _ in range(5):
            app.step()                                        # learn the background
        blob = empty_frame()
        cv2.circle(blob, (640, 360), 180, (20, 40, 200), -1)  # untagged object, no model loaded
        cam.set_images([blob])
        assert step_until(app, lambda: app.state == "OPEN")
        assert (app.decision.bin, app.decision.source) == ("L", "unsure")
        assert sim.received[-1][:2] == ["OPEN", "L"]
    finally:
        link.stop()


def test_printed_sticker_payloads_are_accepted():
    from biotag.tag_reader import parse_payload
    t = parse_payload("BIOTAG:COMPOST:001000")
    assert (t.bin, t.item_id, t.material) == ("C", "001000", "COMPOST")
    assert parse_payload("BIOTAG:RECYCLE:001000").bin == "R"
    assert parse_payload("BIOTAG:LANDFILL:001000").bin == "L"
    assert parse_payload("BIOTAG:NOPE:001000") is None
