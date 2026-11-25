#!/usr/bin/env python3
"""Software stand-in for the ESP32 lid controller (Linux/macOS).

Creates a pseudo serial port and behaves like bin_controller, so the
Jetson software can be developed and tested with no hardware:

    python3 tools/esp32_sim.py            # prints a port such as /dev/pts/5
    python3 -m biotag.main --port /dev/pts/5 --camera mock
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from biotag import protocol  # noqa: E402


class Esp32Sim:
    def __init__(self, deposit_after_s: Optional[float] = 0.3, close_delay_s: float = 0.2,
                 drop_first_n: int = 0):
        """deposit_after_s=None means nobody drops anything in (lid times out)."""
        import pty

        self._master, slave = pty.openpty()
        self.port = os.ttyname(slave)
        self._slave = slave
        self.deposit_after_s, self.close_delay_s = deposit_after_s, close_delay_s
        self.drop_first_n = drop_first_n          # ignore this many frames (tests retries)
        self.received: List[List[str]] = []
        self.open_bin: Optional[str] = None
        self._timers: List[threading.Timer] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> "Esp32Sim":
        self._thread.start()
        self.send("EVT", "BOOT", "sim")
        return self

    def stop(self) -> None:
        self._stop.set()
        for t in self._timers:
            t.cancel()
        self._thread.join(timeout=1)
        for fd in (self._master, self._slave):
            try:
                os.close(fd)
            except OSError:
                pass

    def send(self, *fields) -> None:
        try:
            os.write(self._master, protocol.encode(*fields))
        except OSError:
            pass

    def _later(self, delay: float, fn) -> None:
        t = threading.Timer(delay, fn)
        t.daemon = True
        self._timers.append(t)
        t.start()

    def _close(self, bin_id: str, reason: str) -> None:
        if self.open_bin == bin_id:
            self.open_bin = None
            self.send("EVT", "CLOSED", bin_id, reason)

    def _handle(self, f: List[str]) -> None:
        if self.drop_first_n > 0 and f[0] != "PING":
            self.drop_first_n -= 1
            return
        self.received.append(f)
        if f[0] == "PING":
            self.send("PONG", f[1] if len(f) > 1 else 0)
        elif f[0] == "OPEN" and len(f) >= 2 and f[1] in ("R", "C", "L"):
            if self.open_bin and self.open_bin != f[1]:
                self.send("NAK", "BUSY")
                return
            bin_id, self.open_bin = f[1], f[1]
            self.send("ACK", "OPEN", bin_id)
            timeout = (int(f[2]) if len(f) > 2 else 8000) / 1000.0
            if self.deposit_after_s is not None and self.deposit_after_s < timeout:
                self._later(self.deposit_after_s, lambda: self.send("EVT", "DEPOSIT", bin_id))
                self._later(self.deposit_after_s + self.close_delay_s,
                            lambda: self._close(bin_id, "DEPOSIT"))
            else:
                self._later(timeout, lambda: self._close(bin_id, "TIMEOUT"))
        elif f[0] == "CLOSE":
            which = f[1] if len(f) > 1 else "A"
            self.send("ACK", "CLOSE", which)
            if self.open_bin and which in ("A", self.open_bin):
                self._close(self.open_bin, "CMD")
        elif f[0] == "STATUS":
            self.send("STAT", *[int(self.open_bin == b) for b in "RCL"])
        else:
            self.send("NAK", "UNKNOWN")

    def _run(self) -> None:
        import select

        buf = b""
        while not self._stop.is_set():
            ready, _, _ = select.select([self._master], [], [], 0.05)
            if not ready:
                continue
            try:
                buf += os.read(self._master, 256)
            except OSError:
                return
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                frame = protocol.decode(line)
                if frame is None:
                    if line.strip():
                        self.send("NAK", "CSUM")
                    continue
                self._handle(frame)


if __name__ == "__main__":
    sim = Esp32Sim(deposit_after_s=2.0, close_delay_s=1.5).start()
    print(f"simulated ESP32 on {sim.port}  (Ctrl+C to stop)")
    try:
        seen = 0
        while True:
            time.sleep(0.2)
            for frame in sim.received[seen:]:
                if frame[0] != "PING":
                    print("<-", ",".join(frame))
            seen = len(sim.received)
    except KeyboardInterrupt:
        sim.stop()
