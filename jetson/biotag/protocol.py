"""Jetson <-> ESP32 wire format. See docs/protocol.md.

A frame is one ASCII line:   $FIELD,FIELD,...*XX\\n
XX is the XOR of every byte between '$' and '*', as two uppercase hex digits.
The same framing is implemented in bin_controller/src/main.cpp.
"""
from __future__ import annotations

from typing import List, Optional, Union


def checksum(body: str) -> int:
    value = 0
    for byte in body.encode("ascii"):
        value ^= byte
    return value


def encode(*fields) -> bytes:
    body = ",".join(str(f) for f in fields)
    if any(c in body for c in "$*\r\n"):
        raise ValueError("illegal character in frame")
    return f"${body}*{checksum(body):02X}\n".encode("ascii")


def decode(line: Union[bytes, str]) -> Optional[List[str]]:
    """Return the fields of a valid frame, or None for noise / bad checksum."""
    if isinstance(line, bytes):
        try:
            line = line.decode("ascii")
        except UnicodeDecodeError:
            return None
    line = line.strip()
    start = line.rfind("$")          # tolerate boot-ROM garbage before the frame
    star = line.rfind("*")
    if start < 0 or star < start or len(line) - star != 3:
        return None
    body = line[start + 1:star]
    try:
        if int(line[star + 1:], 16) != checksum(body):
            return None
    except ValueError:
        return None
    return body.split(",")
