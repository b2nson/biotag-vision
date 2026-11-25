#!/usr/bin/env python3
"""Check the Jetson <-> ESP32 connection and cycle each lid.

    python3 tools/check_link.py                     # /dev/ttyTHS1 (header UART)
    python3 tools/check_link.py --port /dev/ttyUSB0 # USB cable
    python3 tools/check_link.py --no-lids           # ping only, nothing moves
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from biotag.esp32_link import Esp32Link  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/ttyTHS1")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--no-lids", action="store_true")
    ap.add_argument("--open-ms", type=int, default=3000)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    link = Esp32Link(args.port, args.baud, heartbeat_s=0.5).start()
    try:
        if not link.wait_connected(5):
            print(f"FAIL: no PONG from ESP32 on {args.port}.\n"
                  "  - TX/RX crossed? Jetson pin 8 -> ESP32 GPIO16, pin 10 <- GPIO17, GND-GND\n"
                  "  - permission? sudo usermod -aG dialout $USER  (then log out and in)\n"
                  "  - port busy? sudo systemctl disable --now nvgetty\n"
                  "  - firmware flashed and ESP32 powered?")
            return 1
        print("PASS: ESP32 is answering")
        print("lid status (R, C, L):", link.status())
        if args.no_lids:
            return 0
        for bin_id in "RCL":
            print(f"opening {bin_id} ...", end=" ", flush=True)
            if not link.open_lid(bin_id, args.open_ms):
                print("FAIL: no ACK")
                return 1
            deadline = time.monotonic() + args.open_ms / 1000 + 8
            closed = None
            while time.monotonic() < deadline and closed is None:
                for ev in link.poll_events():
                    print(",".join(ev[1:]), end=" ", flush=True)
                    if ev[:3] == ["EVT", "CLOSED", bin_id]:
                        closed = ev
                time.sleep(0.05)
            print("ok" if closed else "FAIL: never reported CLOSED")
            if not closed:
                return 1
        print("PASS: all three lids cycled")
        return 0
    finally:
        link.close_lid("A")
        link.stop()


if __name__ == "__main__":
    sys.exit(main())
