from biotag import protocol


def test_round_trip():
    assert protocol.decode(protocol.encode("OPEN", "R", 8000)) == ["OPEN", "R", "8000"]


def test_known_checksum():
    # 0x50^0x49^0x4E^0x47^0x2C^0x31 = 0x0D - the firmware must produce the same value
    assert protocol.encode("PING", 1) == b"$PING,1*0D\n"


def test_bad_checksum_rejected():
    assert protocol.decode(b"$OPEN,R,8000*00\n") is None


def test_corrupted_byte_rejected():
    good = protocol.encode("OPEN", "R", 8000)
    assert protocol.decode(good.replace(b"R", b"C")) is None


def test_noise_ignored():
    assert protocol.decode(b"ets Jul 29 2019 12:21:46\r\n") is None
    assert protocol.decode(b"\xff\xfe\x00") is None
    assert protocol.decode(b"") is None


def test_garbage_before_frame_tolerated():
    assert protocol.decode(b"rst:0x1$PONG,7*" + b"%02X" % protocol.checksum("PONG,7")) == ["PONG", "7"]


def test_illegal_characters():
    import pytest

    with pytest.raises(ValueError):
        protocol.encode("OPEN", "R*")
