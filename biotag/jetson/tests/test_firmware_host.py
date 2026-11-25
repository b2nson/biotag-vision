"""Compile the real lid-controller firmware for the PC and check that it speaks
the same protocol as biotag/protocol.py. Skipped if g++ is not installed."""
import shutil
import subprocess
from pathlib import Path

import pytest

from biotag import protocol

FW = Path(__file__).resolve().parents[2] / "firmware" / "bin_controller"
pytestmark = pytest.mark.skipif(shutil.which("g++") is None, reason="g++ not installed")


@pytest.fixture(scope="module")
def binary(tmp_path_factory):
    out = tmp_path_factory.mktemp("fw") / "bin_controller_host"
    subprocess.run(["g++", "-std=c++17", "-Wall", "-I", str(FW / "host_test"),
                    str(FW / "host_test" / "harness.cpp"), "-o", str(out)], check=True)
    return out


def frame(*fields):
    return "S " + protocol.encode(*fields).decode().strip()


def run(binary, script):
    """Returns [(ms, fields)] for frames, plus ANGLES rows as (ms, ['ANGLES', ...])."""
    res = subprocess.run([str(binary)], input="\n".join(script) + "\n",
                         capture_output=True, text=True, check=True)
    out = []
    for line in res.stdout.splitlines():
        ms, rest = line.split(" ", 1)
        if rest.startswith("ANGLES"):
            out.append((int(ms), rest.split()))
        else:
            fields = protocol.decode(rest)
            assert fields is not None, f"firmware sent a frame Python rejects: {rest!r}"
            out.append((int(ms), fields))
    return out


def fields_of(out):
    return [f for _, f in out]


def test_boot_and_ping(binary):
    out = fields_of(run(binary, [frame("PING", 42)]))
    assert out[0][:2] == ["EVT", "BOOT"]
    assert out[1] == ["PONG", "42"]


def test_open_deposit_close(binary):
    out = run(binary, [
        frame("OPEN", "R", 8000), "T 1500", "A",        # lid fully open
        "B R 1", "T 300", "B R 0",                      # item passes the beam
        "T 1000", "A",                                  # still open: waiting CLOSE_DELAY
        "T 2500", "A", frame("STATUS"),
    ])
    f = fields_of(out)
    assert ["ACK", "OPEN", "R"] in f
    assert ["EVT", "DEPOSIT", "R"] in f
    assert ["EVT", "CLOSED", "R", "DEPOSIT"] in f
    angles = [x for x in f if x[0] == "ANGLES"]
    assert angles[0] == ["ANGLES", "95", "0", "0"]
    assert angles[1] == ["ANGLES", "95", "0", "0"]
    assert angles[2] == ["ANGLES", "0", "0", "0"]
    assert f[-1] == ["STAT", "0", "0", "0"]


def test_timeout_when_nothing_dropped(binary):
    out = run(binary, [frame("OPEN", "C", 2000), "T 1000", frame("STATUS"), "T 3000"])
    f = fields_of(out)
    assert ["STAT", "0", "1", "0"] in f
    closed = [(ms, x) for ms, x in out if x[:2] == ["EVT", "CLOSED"]]
    assert closed[0][1] == ["EVT", "CLOSED", "C", "TIMEOUT"]
    assert 3000 < closed[0][0] < 3600               # 2 s open + about 1.1 s of travel


def test_only_one_lid_at_a_time(binary):
    f = fields_of(run(binary, [frame("OPEN", "R", 8000), "T 200", frame("OPEN", "L", 8000),
                               frame("CLOSE", "A"), "T 3000", frame("OPEN", "L", 1000)]))
    assert ["NAK", "BUSY"] in f
    assert ["ACK", "CLOSE", "A"] in f
    assert ["EVT", "CLOSED", "R", "CMD"] in f
    assert f[-1] == ["ACK", "OPEN", "L"]


def test_hand_in_opening_reopens_lid(binary):
    out = run(binary, [
        frame("OPEN", "L", 1000), "T 1700",             # timed out, now closing
        "A", "B L 1", "T 1500", "A",                    # hand blocks beam: lid backs off
        "B L 0", "T 3000", "A",
    ])
    f = fields_of(out)
    angles = [int(x[3]) for x in f if x[0] == "ANGLES"]
    assert 0 < angles[0] < 95                           # caught mid-close
    assert angles[1] == 95                              # re-opened
    assert angles[2] == 0                               # closed once clear
    assert [x for x in f if x[:2] == ["EVT", "CLOSED"]] == [["EVT", "CLOSED", "L", "TIMEOUT"]]


def test_bad_frames_rejected(binary):
    f = fields_of(run(binary, ["S $OPEN,R,8000*00", "S random noise", frame("OPEN", "X", 1),
                               frame("DANCE"), "T 2000", frame("STATUS")]))
    assert ["NAK", "CSUM"] in f
    assert ["NAK", "ARG"] in f
    assert ["NAK", "UNKNOWN"] in f
    assert f[-1] == ["STAT", "0", "0", "0"]             # nothing moved
