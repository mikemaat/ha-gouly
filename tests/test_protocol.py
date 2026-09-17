"""Protocol tests against frames captured from a real Gouly controller and app."""

import pytest

from gouly_core import protocol

# Frames sent by the Gouly app (1.8.2) and echoed by the controller.
CAPTURED_POWER_ON = "aaf101000000000000002e"
CAPTURED_POWER_OFF = "aaf100000000000000006d"
CAPTURED_BRIGHTNESS_40 = "aaf228000000000000001a"
CAPTURED_BRIGHTNESS_255 = "aaf2ff0000000000000045"
CAPTURED_QUERY_STATE = "aab60000000000009b"
CAPTURED_RED = [
    "aac7000000000000000049",
    "aaf3a10190006400640064006430",
    "aaf3a20000010000063e000000ff00ff0000" + "00" * 94 + "8c",
    "aaf6ff000000000000000000000000000000a3",
    "aaa00000000000000000a9",
]
CAPTURED_BLUE_SOLID = "aaf60000ff00000000000000000000000000de"
CAPTURED_WHITE_SOLID = "aaf6000000ff000000000000000000000000e2"
CAPTURED_WHITE_COLOUR_LIST = "aaf3a20000010000063e000000ff00000000ff" + "00" * 93 + "46"
# Controller state reports (0xBB B6): on/off, brightness, then program parameters.
REPORT_ON_FULL = "bbb601ff063f03e700c800c800c800030101530001070013000000000012"
REPORT_OFF_FULL = "bbb600ff063f03e700c800c800c8000301015300010700130000000000f4"


def hexes(frames: list[bytes]) -> list[str]:
    return [f.hex() for f in frames]


@pytest.mark.parametrize(
    "frame",
    [
        CAPTURED_POWER_ON,
        CAPTURED_POWER_OFF,
        CAPTURED_BRIGHTNESS_40,
        CAPTURED_QUERY_STATE,
        *CAPTURED_RED,
        CAPTURED_BLUE_SOLID,
        CAPTURED_WHITE_COLOUR_LIST,
        REPORT_ON_FULL,
        REPORT_OFF_FULL,
    ],
)
def test_captured_frames_pass_checksum(frame: str) -> None:
    protocol.verify_frame(bytes.fromhex(frame))


def test_bad_checksum_rejected() -> None:
    frame = bytearray.fromhex(CAPTURED_POWER_ON)
    frame[-1] ^= 0xFF
    with pytest.raises(protocol.FrameError):
        protocol.verify_frame(bytes(frame))


def test_power_matches_app() -> None:
    assert hexes(protocol.power(True)) == [CAPTURED_POWER_ON]
    assert hexes(protocol.power(False)) == [CAPTURED_POWER_OFF]


def test_brightness_matches_app() -> None:
    assert hexes(protocol.brightness(40)) == [CAPTURED_BRIGHTNESS_40]
    assert hexes(protocol.brightness(255)) == [CAPTURED_BRIGHTNESS_255]


def test_brightness_is_clamped() -> None:
    assert protocol.brightness(0)[0][2] == 1
    assert protocol.brightness(999)[0][2] == 255


def test_query_state_matches_app() -> None:
    assert hexes(protocol.query_state()) == [CAPTURED_QUERY_STATE]


def test_solid_colour_matches_app() -> None:
    assert hexes(protocol.solid_colour(255, 0, 0)) == CAPTURED_RED
    assert hexes(protocol.solid_colour(0, 0, 255))[3] == CAPTURED_BLUE_SOLID
    white = hexes(protocol.solid_colour(0, 0, 0, 255))
    assert white[2] == CAPTURED_WHITE_COLOUR_LIST
    assert white[3] == CAPTURED_WHITE_SOLID


def test_dp_round_trip() -> None:
    frame = bytes.fromhex(CAPTURED_POWER_ON)
    assert protocol.decode_dp(protocol.encode_dp(frame)) == frame


def test_parse_echoes() -> None:
    assert protocol.parse_frame(bytes.fromhex(CAPTURED_POWER_OFF)).is_on is False
    assert protocol.parse_frame(bytes.fromhex(CAPTURED_BRIGHTNESS_40)).brightness == 40
    assert protocol.parse_frame(bytes.fromhex(CAPTURED_BLUE_SOLID)).rgbw == (0, 0, 255, 0)
    assert protocol.parse_frame(bytes.fromhex(CAPTURED_WHITE_SOLID)).rgbw == (0, 0, 0, 255)
    assert not protocol.parse_frame(bytes.fromhex(CAPTURED_QUERY_STATE))


def test_parse_state_report() -> None:
    update = protocol.parse_frame(bytes.fromhex(REPORT_ON_FULL))
    assert update.is_on is True
    assert update.brightness == 255
    assert protocol.parse_frame(bytes.fromhex(REPORT_OFF_FULL)).is_on is False


def test_parse_dps() -> None:
    assert protocol.parse_dps({"20": False}).is_on is False
    raw = protocol.encode_dp(bytes.fromhex(CAPTURED_BRIGHTNESS_40))
    update = protocol.parse_dps({"101": raw})
    assert update.brightness == 40
    assert update.is_on is None
    assert not protocol.parse_dps({"101": "not base64!"})
