"""Serial link from the Jetson to the ESP32 lid controller.

Works over the 40-pin header UART (/dev/ttyTHS1) or a USB cable
(/dev/ttyUSB0 or /dev/ttyACM0) - the protocol is identical.

A background thread reads frames, answers nothing itself, sends a PING every
few seconds and reconnects if the port disappears. Commands are sent from the
caller's thread and wait for the matching ACK, with retries.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from typing import List, Optional

from . import protocol

log = logging.getLogger("biotag.link")


class Esp32Link:
    def __init__(self, port: str, baud: int = 115200, ack_timeout_s: float = 0.3,
                 retries: int = 3, heartbeat_s: float = 2.0):
        self.port, self.baud = port, baud
        self.ack_timeout_s, self.retries, self.heartbeat_s = ack_timeout_s, retries, heartbeat_s
        self.events: "queue.Queue[List[str]]" = queue.Queue()
        self._replies: "queue.Queue[List[str]]" = queue.Queue()
        self._ser = None
        self._write_lock = threading.Lock()
        self._cmd_lock = threading.Lock()
        self._stop = threading.Event()
        self._last_pong = 0.0
        self._seq = 0
        self._thread: Optional[threading.Thread] = None

    # ---- lifecycle -------------------------------------------------------
    def start(self) -> "Esp32Link":
        self._thread = threading.Thread(target=self._run, name="esp32-link", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        self._close()

    @property
    def connected(self) -> bool:
        return time.monotonic() - self._last_pong < 3 * self.heartbeat_s

    def wait_connected(self, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.connected:
                return True
            time.sleep(0.05)
        return False

    # ---- commands --------------------------------------------------------
    def open_lid(self, bin_id: str, timeout_ms: int) -> bool:
        return self._command(("OPEN", bin_id, int(timeout_ms)), ("ACK", "OPEN", bin_id))

    def close_lid(self, bin_id: str = "A") -> bool:
        return self._command(("CLOSE", bin_id), ("ACK", "CLOSE", bin_id))

    def status(self) -> Optional[List[str]]:
        """Return ['0'|'1', '0'|'1', '0'|'1'] for R, C, L lids (1 = open)."""
        with self._cmd_lock:
            self._drain()
            for _ in range(self.retries):
                self._write(protocol.encode("STATUS"))
                reply = self._wait_reply(lambda f: f[0] == "STAT")
                if reply:
                    return reply[1:]
        return None

    def poll_events(self) -> List[List[str]]:
        out = []
        while True:
            try:
                out.append(self.events.get_nowait())
            except queue.Empty:
                return out

    # ---- internals -------------------------------------------------------
    def _command(self, fields, expect) -> bool:
        expect = [str(x) for x in expect]
        with self._cmd_lock:
            self._drain()
            for attempt in range(1, self.retries + 1):
                if not self._write(protocol.encode(*fields)):
                    time.sleep(self.ack_timeout_s)
                    continue
                reply = self._wait_reply(lambda f: f[0] == "NAK" or f[:len(expect)] == expect)
                if reply and reply[0] != "NAK":
                    return True
                if reply and reply[1:2] == ["BUSY"]:
                    log.warning("ESP32 busy: %s", fields)
                    return False
                log.warning("no ACK for %s (attempt %d): %s", fields, attempt, reply)
        return False

    def _wait_reply(self, match) -> Optional[List[str]]:
        deadline = time.monotonic() + self.ack_timeout_s
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                frame = self._replies.get(timeout=remaining)
            except queue.Empty:
                return None
            if match(frame):
                return frame

    def _drain(self) -> None:
        while not self._replies.empty():
            try:
                self._replies.get_nowait()
            except queue.Empty:
                break

    def _write(self, data: bytes) -> bool:
        with self._write_lock:
            if self._ser is None:
                return False
            try:
                self._ser.write(data)
                self._ser.flush()
                return True
            except Exception as exc:  # serial.SerialException, OSError
                log.warning("write failed: %s", exc)
                self._close()
                return False

    def _close(self) -> None:
        ser, self._ser = self._ser, None
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass

    def _open(self) -> bool:
        import serial

        try:
            self._ser = serial.Serial(self.port, self.baud, timeout=0.1)
            log.info("opened %s @ %d", self.port, self.baud)
            return True
        except Exception as exc:
            log.warning("cannot open %s: %s", self.port, exc)
            self._ser = None
            return False

    def _run(self) -> None:
        next_ping = 0.0
        while not self._stop.is_set():
            if self._ser is None and not self._open():
                self._stop.wait(1.0)
                continue
            now = time.monotonic()
            if now >= next_ping:
                self._seq = (self._seq + 1) % 1000
                self._write(protocol.encode("PING", self._seq))
                next_ping = now + self.heartbeat_s
            try:
                line = self._ser.readline() if self._ser else b""
            except Exception as exc:
                log.warning("read failed: %s", exc)
                self._close()
                continue
            if not line:
                continue
            frame = protocol.decode(line)
            if frame is None:
                continue
            if frame[0] == "PONG":
                self._last_pong = time.monotonic()
            elif frame[0] == "EVT":
                self._last_pong = time.monotonic()
                self.events.put(frame)
            else:
                self._replies.put(frame)


class NullLink:
    """Stand-in used with --no-link: pretends the lid closes after a short delay."""

    connected = True

    def __init__(self, hold_s: float = 2.0):
        self.hold_s = hold_s
        self._pending: List[tuple] = []

    def start(self):
        return self

    def stop(self):
        pass

    def wait_connected(self, timeout: float = 0.0) -> bool:
        return True

    def open_lid(self, bin_id: str, timeout_ms: int) -> bool:
        log.info("[no-link] OPEN %s", bin_id)
        self._pending.append((time.monotonic() + self.hold_s, bin_id))
        return True

    def close_lid(self, bin_id: str = "A") -> bool:
        return True

    def poll_events(self):
        now = time.monotonic()
        done = [p for p in self._pending if p[0] <= now]
        self._pending = [p for p in self._pending if p[0] > now]
        return [["EVT", "CLOSED", b, "TIMEOUT"] for _, b in done]
