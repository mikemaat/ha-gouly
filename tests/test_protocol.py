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


# A multi zone preset ("Eid-Cyan-Pacman"), whose palette is green/white/white/green.
SEGMENT_WITH_PALETTE = (
    "aaf3a2000001000003e69a7800ff00000000000000000000000000000000ff00ff000000ffffff0000ffffff0000"
    "00ff00000000ff000000ffffff0000ffffff000000ff00000000ff000000ffffff0000ffffff000000ff00000000"
    "ff000000ffffff0000ffffff000000ff00000004f9"
)


def test_single_colour_scene_reports_that_colour() -> None:
    # The red solid colour scene keeps its colour in colour 1, not the palette.
    update = protocol.parse_frame(bytes.fromhex(CAPTURED_RED[2]))
    assert update.palette == [(255, 0, 0, 0, 0)]


def test_multi_colour_scene_reports_each_distinct_colour() -> None:
    update = protocol.parse_frame(bytes.fromhex(SEGMENT_WITH_PALETTE))
    assert update.effect == 154
    assert update.palette == [(0, 255, 0, 0, 0), (255, 255, 255, 0, 0)]


def test_palette_survives_a_dp_round_trip() -> None:
    raw = protocol.encode_dp(bytes.fromhex(SEGMENT_WITH_PALETTE))
    assert protocol.parse_dps({"101": raw}).palette == [(0, 255, 0, 0, 0), (255, 255, 255, 0, 0)]


@pytest.mark.parametrize("frame", [SEGMENT_WITH_PALETTE, CAPTURED_RED[2]])
def test_captured_segments_rebuild_exactly(frame: str) -> None:
    """A segment read back from the app's frame is sent again byte for byte."""
    seg = protocol.parse_segment(bytes.fromhex(frame)[2:-1])
    assert protocol.segment(seg).hex() == frame


def test_parse_segment_reads_the_fields() -> None:
    seg = protocol.parse_segment(bytes.fromhex(SEGMENT_WITH_PALETTE)[2:-1])
    assert (seg.start, seg.end, seg.effect, seg.speed) == (0, 999, 154, 120)
    assert seg.palette[:2] == [(0, 255, 0, 0, 0, 255), (255, 255, 255, 0, 0, 255)]
    assert len(seg.palette) == 4


def test_parse_segment_rejects_other_frames() -> None:
    with pytest.raises(protocol.FrameError):
        protocol.parse_segment(bytes.fromhex(CAPTURED_RED[1])[2:-1])


def test_scene_recorder_keeps_the_last_whole_scene() -> None:
    recorder = protocol.SceneRecorder()
    for frame in CAPTURED_RED:
        recorder.feed(bytes.fromhex(frame))
    assert recorder.segments is not None and recorder.segments[0].colours[0] == (255, 0, 0, 0, 0)

    layout = protocol.Layout(1599, (999, 200, 200, 200))
    seg = protocol.parse_segment(bytes.fromhex(SEGMENT_WITH_PALETTE)[2:-1])
    for frame in protocol.scene(layout, [seg, seg]):
        recorder.feed(frame)
    assert [s.effect for s in recorder.segments] == [154, 154]


def test_scene_recorder_ignores_unfinished_scenes() -> None:
    recorder = protocol.SceneRecorder()
    for frame in CAPTURED_RED:
        recorder.feed(bytes.fromhex(frame))
    before = recorder.segments
    layout = protocol.Layout(1599, (999, 200, 200, 200))
    frames = protocol.scene(layout, [protocol.parse_segment(bytes.fromhex(SEGMENT_WITH_PALETTE)[2:-1])])
    for frame in frames[:-1]:  # no save
        recorder.feed(frame)
    assert recorder.segments is before
    recorder.reset()
    recorder.feed(frames[-1])  # a save on its own doesn't make a scene
    assert recorder.segments is before


def test_scene_recorder_needs_a_header() -> None:
    recorder = protocol.SceneRecorder()
    recorder.feed(bytes.fromhex(SEGMENT_WITH_PALETTE))
    recorder.feed(protocol.save())
    assert recorder.segments is None
