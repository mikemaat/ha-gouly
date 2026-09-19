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
from dataclasses import dataclass, field

Colour = tuple[int, int, int, int, int]  # red, green, blue, warm white, cold white
PaletteColour = tuple[int, int, int, int, int, int]  # colour plus its own brightness
BLACK: Colour = (0, 0, 0, 0, 0)

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
CMD_MUSIC_MODE = 0xC7

SUB_SCENE_HEADER = 0xA1
SUB_SEGMENT = 0xA2

# A segment frame carries a 16 entry palette of 5 bytes each.
PALETTE_SIZE = 16

# Frame lengths (including header and CRC) as sent by the Gouly app.
LEN_QUERY = 9
LEN_SHORT = 11
LEN_SCENE_HEADER = 14
LEN_SOLID_COLOUR = 19
LEN_SEGMENT = 113

# Program parameters and colour-list header the app sends for a static solid colour.
# The individual fields are not fully decoded yet.
_STATIC_SCENE_HEADER = bytes.fromhex("A1019000640064006400" "64")
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
        build_frame(CMD_PROGRAM, _STATIC_SCENE_HEADER, LEN_SCENE_HEADER),
        build_frame(CMD_PROGRAM, _STATIC_COLOUR_LIST_HEADER + rgbw, LEN_SEGMENT),
        build_frame(CMD_SOLID_COLOUR, rgbw, LEN_SOLID_COLOUR),
        build_frame(CMD_APPLY),
    ]


@dataclass(frozen=True, slots=True)
class Layout:
    """How many LEDs the controller drives, in total and per output."""

    total: int
    channels: tuple[int, int, int, int]


@dataclass(slots=True)
class Segment:
    """One zone of the string: a range of LEDs running one effect."""

    start: int
    end: int
    effect: int
    speed: int = 128
    width: int = 0
    brightness: int = 255
    direction: int = 0
    colours: tuple[Colour, Colour, Colour] = (BLACK, BLACK, BLACK)
    panel_id: int = -1
    palette: list[PaletteColour] = field(default_factory=list)
    segment_id: int = 0
    is_on: bool = True


def scene_header(layout: Layout) -> bytes:
    """Start a scene: total LED count followed by the four zone lengths."""
    return build_frame(
        CMD_PROGRAM,
        bytes([SUB_SCENE_HEADER])
        + layout.total.to_bytes(2, "big")
        + b"".join(c.to_bytes(2, "big") for c in layout.channels),
        LEN_SCENE_HEADER,
    )


def segment(seg: Segment) -> bytes:
    """Build a segment (zone) frame."""
    payload = bytearray([SUB_SEGMENT, 0, seg.segment_id, 1 if seg.is_on else 0])
    payload += max(seg.start - 1, 0).to_bytes(2, "big")
    payload += (max(seg.end - 1, 0)).to_bytes(2, "big")
    payload += bytes(
        [
            seg.effect,
            max(0, min(255, seg.speed)),
            seg.width,
            max(0, min(255, seg.brightness)),
            1 if seg.direction else 0,
        ]
    )
    for colour in seg.colours:
        payload += bytes(colour)
    payload += bytes([seg.panel_id if 0 <= seg.panel_id <= 255 else (255 if seg.panel_id != -1 else 0)])
    if seg.palette:
        for index in range(PALETTE_SIZE):
            red, green, blue, warm, white, bright = seg.palette[index % len(seg.palette)]
            payload += bytes([c * bright // 255 for c in (red, green, blue, warm, white)])
    else:
        payload += bytes(PALETTE_SIZE * 5)
    payload += bytes([len(seg.palette)])
    return build_frame(CMD_PROGRAM, bytes(payload), LEN_SEGMENT)


def music_mode(on: bool, mode: int = 0) -> bytes:
    """Turn music mode on or off (the app sends 'off' before setting a colour or effect)."""
    return build_frame(CMD_MUSIC_MODE, bytes([1 if on else 0, mode]))


def save() -> bytes:
    """Store the current scene in the controller (sent after a scene is built)."""
    return build_frame(CMD_APPLY, bytes(1))


def effect(layout: Layout, effect_id: int, colour: Colour, speed: int = 128, brightness: int = 255) -> list[bytes]:
    """Run one effect across the whole string, coloured by `colour`."""
    seg = Segment(
        0,
        layout.total,
        effect_id,
        speed=speed,
        brightness=brightness,
        colours=(colour, BLACK, BLACK),
        palette=[(*colour, 255)],
    )
    return [music_mode(False), scene_header(layout), segment(seg), save()]


def scene(layout: Layout, segments: list[Segment]) -> list[bytes]:
    """Build a multi zone scene (used for presets)."""
    frames = [music_mode(False), scene_header(layout)]
    frames += [segment(s) for s in segments if s.start < layout.total and s.start < s.end]
    frames.append(save())
    return frames


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
    effect: int | None = None
    layout: Layout | None = None
    # Colours a scene is showing: one entry for a single colour scene, more for a mixed one.
    palette: list[Colour] | None = None

    def __bool__(self) -> bool:
        return any(
            v is not None
            for v in (self.is_on, self.brightness, self.rgbw, self.effect, self.layout, self.palette)
        )


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
        elif command == CMD_PROGRAM and len(data) >= 11 and data[0] == SUB_SEGMENT:
            # Segment echo: ... start(2) end(2) effect speed ...
            update.effect = data[8]
            update.palette = _segment_palette(data)
    elif header == HEADER_REPORT:
        if command == CMD_QUERY_STATE and len(data) >= 2:
            update.is_on = data[0] == 1
            update.brightness = data[1]
            if len(data) >= 12:
                update.layout = Layout(
                    int.from_bytes(data[2:4], "big"),
                    tuple(int.from_bytes(data[i : i + 2], "big") for i in (4, 6, 8, 10)),
                )
    return update


def _segment_palette(data: bytes) -> list[Colour] | None:
    """The distinct colours in a segment frame's palette, in the order they appear."""
    # data: A2 tog seg on start(2) end(2) effect speed width bright dir c1(5) c2(5) c3(5)
    #       panel palette(16x5) count
    start = 1 + 3 + 4 + 5 + 15 + 1
    end = start + PALETTE_SIZE * 5
    if len(data) < end + 1:
        return None
    count = min(data[end], PALETTE_SIZE)
    colours: list[Colour] = []
    for index in range(count):
        colour = tuple(data[start + index * 5 : start + index * 5 + 5])
        if any(colour) and colour not in colours:
            colours.append(colour)  # type: ignore[arg-type]
    if not colours:
        # A single colour scene carries it as colour 1 rather than in the palette.
        first = tuple(data[13:18])
        if any(first):
            colours.append(first)  # type: ignore[arg-type]
    return colours or None


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
        for field in ("is_on", "brightness", "rgbw", "effect", "layout", "palette"):
            value = getattr(frame_update, field)
            if value is not None:
                setattr(update, field, value)
    return update
