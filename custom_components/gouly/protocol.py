"""Gouly controller protocol.

Gouly controllers are Tuya devices, but the Gouly app does not use the standard Tuya
light data points. Instead it sends binary frames through the raw "transparent" data
point (DP 101). This module encodes and decodes those frames and has no Home Assistant
dependencies, so it can be unit tested and reused on its own.

Frame layout (see docs/PROTOCOL.md):

    <header> <command> <payload...> <crc>

* header: 0xAA for commands (and command echoes), 0xBB for controller reports
* crc: CRC-8/MAXIM over every preceding byte, including the header
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

DP_SWITCH = "20"
DP_TRANSPARENT = "101"

HEADER_COMMAND = 0xAA
HEADER_REPORT = 0xBB

CMD_APPLY = 0xA0
CMD_QUERY_STATE = 0xB6
CMD_STOP_MUSIC = 0xC7
CMD_POWER = 0xF1
CMD_BRIGHTNESS = 0xF2
CMD_PROGRAM = 0xF3
CMD_SOLID_COLOUR = 0xF6

SUB_PROGRAM_PARAMS = 0xA1
SUB_PROGRAM_COLOURS = 0xA2

# Frame lengths (including header and CRC) as sent by the Gouly app.
LEN_QUERY = 9
LEN_SHORT = 11
LEN_PROGRAM_PARAMS = 14
LEN_SOLID_COLOUR = 19
LEN_PROGRAM_COLOURS = 113

# Program parameters and colour-list header the app sends for a static solid colour.
# The individual fields are not fully decoded yet.
_STATIC_PROGRAM_PARAMS = bytes.fromhex("A1019000640064006400" "64")
_STATIC_COLOUR_LIST_HEADER = bytes.fromhex("A20000010000063e000000ff00")


class FrameError(ValueError):
    """Raised when a frame is malformed or fails its checksum."""


def crc8_maxim(data: bytes) -> int:
    """CRC-8/MAXIM (Dallas 1-Wire): poly 0x31 reflected, init 0x00, no final XOR."""
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8C if crc & 1 else crc >> 1
    return crc


def build_frame(command: int, payload: bytes = b"", length: int = LEN_SHORT) -> bytes:
    """Build a command frame, zero padded to `length` bytes including the CRC."""
    body = bytes([HEADER_COMMAND, command]) + payload
    if len(body) > length - 1:
        raise FrameError(f"payload too long for a {length} byte frame")
    body = body.ljust(length - 1, b"\x00")
    return body + bytes([crc8_maxim(body)])


def verify_frame(frame: bytes) -> None:
    """Raise FrameError if the frame is too short, has an unknown header or a bad CRC."""
    if len(frame) < 3:
        raise FrameError("frame too short")
    if frame[0] not in (HEADER_COMMAND, HEADER_REPORT):
        raise FrameError(f"unknown header 0x{frame[0]:02x}")
    if crc8_maxim(frame[:-1]) != frame[-1]:
        raise FrameError("checksum mismatch")


def power(on: bool) -> list[bytes]:
    """Turn the lights on or off."""
    return [build_frame(CMD_POWER, bytes([1 if on else 0]))]


def brightness(value: int) -> list[bytes]:
    """Set brightness, 1-255."""
    value = max(1, min(255, int(value)))
    return [build_frame(CMD_BRIGHTNESS, bytes([value]))]


def solid_colour(red: int, green: int, blue: int, white: int = 0) -> list[bytes]:
    """Show a single static RGBW colour, replaying the sequence the Gouly app sends."""
    rgbw = bytes(max(0, min(255, int(c))) for c in (red, green, blue, white))
    return [
        build_frame(CMD_STOP_MUSIC),
        build_frame(CMD_PROGRAM, _STATIC_PROGRAM_PARAMS, LEN_PROGRAM_PARAMS),
        build_frame(CMD_PROGRAM, _STATIC_COLOUR_LIST_HEADER + rgbw, LEN_PROGRAM_COLOURS),
        build_frame(CMD_SOLID_COLOUR, rgbw, LEN_SOLID_COLOUR),
        build_frame(CMD_APPLY),
    ]


def query_state() -> list[bytes]:
    """Ask the controller to report its state (answered with a 0xBB 0xB6 report)."""
    return [build_frame(CMD_QUERY_STATE, length=LEN_QUERY)]


def encode_dp(frame: bytes) -> str:
    """Encode a frame for the Tuya local protocol (raw DPs are base64 strings)."""
    return base64.b64encode(frame).decode("ascii")


def decode_dp(value: str) -> bytes:
    """Decode a raw DP value received over the Tuya local protocol."""
    return base64.b64decode(value)


@dataclass(slots=True)
class StateUpdate:
    """Partial light state learned from a frame. Fields that are None are unknown."""

    is_on: bool | None = None
    brightness: int | None = None
    rgbw: tuple[int, int, int, int] | None = None

    def __bool__(self) -> bool:
        return any(v is not None for v in (self.is_on, self.brightness, self.rgbw))


def parse_frame(frame: bytes) -> StateUpdate:
    """Extract light state from a command echo or controller report.

    The controller echoes every command it accepts (from the Gouly app or from us),
    which lets Home Assistant follow changes made elsewhere.
    """
    verify_frame(frame)
    header, command, data = frame[0], frame[1], frame[2:-1]
    update = StateUpdate()
    if header == HEADER_COMMAND:
        if command == CMD_POWER and data:
            update.is_on = data[0] == 1
        elif command == CMD_BRIGHTNESS and data:
            update.brightness = data[0]
        elif command == CMD_SOLID_COLOUR and len(data) >= 4:
            update.rgbw = (data[0], data[1], data[2], data[3])
    elif header == HEADER_REPORT:
        if command == CMD_QUERY_STATE and len(data) >= 2:
            update.is_on = data[0] == 1
            update.brightness = data[1]
    return update


def parse_dps(dps: dict[str, object]) -> StateUpdate:
    """Extract light state from a Tuya DP update dict."""
    update = StateUpdate()
    switch = dps.get(DP_SWITCH)
    if isinstance(switch, bool):
        update.is_on = switch
    raw = dps.get(DP_TRANSPARENT)
    if isinstance(raw, str):
        try:
            frame_update = parse_frame(decode_dp(raw))
        except (FrameError, ValueError):
            return update
        for field in ("is_on", "brightness", "rgbw"):
            value = getattr(frame_update, field)
            if value is not None:
                setattr(update, field, value)
    return update
