"""Preset library scaling (no Home Assistant, no network)."""

import importlib.util
import sys
from pathlib import Path

import pytest

from gouly_core import protocol

spec = importlib.util.spec_from_file_location(
    "gouly_core.presets", Path(__file__).resolve().parent.parent / "custom_components" / "gouly" / "presets.py"
)
presets = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = presets
spec.loader.exec_module(presets)

LAYOUT = protocol.Layout(1599, (999, 200, 200, 200))


def zone(start, end, effect=154, **kwargs):
    return {
        "start": start, "end": end, "effect": effect, "speed": 128, "width": 0,
        "brightness": 255, "direction": 0, "on": True,
        "colours": [[0, 0, 0, 0, 0]] * 3, "palette": 3024, **kwargs,
    }


LIBRARY = {
    "version": 1,
    "palettes": {"3024": [[0, 255, 0, 0, 0, 255], [255, 255, 255, 0, 0, 255]]},
    "folders": {
        "Christmas": [{"name": "One zone", "total": 800, "zones": [zone(0, 799)]}],
        "Halloween": [{"name": "Three zones", "total": 800, "zones": [zone(0, 265), zone(266, 532), zone(533, 799)]}],
    },
}


@pytest.fixture
def library():
    return presets.PresetLibrary(LIBRARY)


def test_folders_and_names(library) -> None:
    assert library.folder_names == ["Christmas", "Halloween"]
    assert library.names_in("Halloween") == ["Three zones"]
    assert library.find("Christmas", "One zone") is not None
    assert library.find("Christmas", "nope") is None


def test_single_zone_covers_the_whole_string(library) -> None:
    segments = library.find("Christmas", "One zone").segments(LAYOUT, library.palettes)
    assert len(segments) == 1
    assert (segments[0].start, segments[0].end) == (0, LAYOUT.total)


def test_zones_are_scaled_and_contiguous(library) -> None:
    segments = library.find("Halloween", "Three zones").segments(LAYOUT, library.palettes)
    # zone ends are exclusive, so each zone starts where the previous one ended
    assert [(s.start, s.end) for s in segments] == [(0, 532), (532, 1065), (1065, 1599)]
    assert segments[-1].end == LAYOUT.total  # no dark tail from rounding
    assert all(s.palette == [(0, 255, 0, 0, 0, 255), (255, 255, 255, 0, 0, 255)] for s in segments)


def test_frames_are_valid(library) -> None:
    frames = library.frames(library.find("Halloween", "Three zones"), LAYOUT)
    assert len(frames) == 6  # music off, header, 3 segments, save
    for frame in frames:
        protocol.verify_frame(frame)
    assert [len(f) for f in frames] == [11, 14, 113, 113, 113, 11]


def test_zones_past_the_end_are_dropped() -> None:
    library = presets.PresetLibrary(
        {"version": 1, "palettes": {}, "folders": {"F": [{"name": "P", "total": 800, "zones": [zone(0, 99), zone(900, 999)]}]}}
    )
    small = protocol.Layout(100, (100, 0, 0, 0))
    segments = library.find("F", "P").segments(small, library.palettes)
    assert [(s.start, s.end) for s in segments] == [(0, 12)]


def test_load_missing_file(tmp_path) -> None:
    assert presets.load(str(tmp_path)) is None


def test_load_wrong_version(tmp_path) -> None:
    (tmp_path / presets.PRESETS_FILE).write_text('{"version": 99, "folders": {}}', encoding="utf-8")
    assert presets.load(str(tmp_path)) is None


def test_validate_accepts_a_real_library() -> None:
    assert presets.validate(LIBRARY) == (2, 2)


@pytest.mark.parametrize(
    "data",
    [
        "not a dict",
        {"version": 99, "folders": {"F": []}},
        {"version": 1, "folders": {}},
        {"version": 1, "folders": {"F": "nope"}},
        {"version": 1, "folders": {"F": [{"name": "no zones"}]}},
    ],
)
def test_validate_rejects_bad_files(data) -> None:
    with pytest.raises(ValueError):
        presets.validate(data)


def test_install_writes_the_library(tmp_path) -> None:
    import json as _json

    source = tmp_path / "upload.json"
    source.write_text(_json.dumps(LIBRARY), encoding="utf-8")
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    assert presets.install(source, str(config_dir)) == (2, 2)
    assert presets.load(str(config_dir)) is not None


def test_effect_names_round_trip(library) -> None:
    preset = library.find("Halloween", "Three zones")
    name = library.effect_name(preset)
    assert name == "Halloween / Three zones"
    assert library.find_by_effect_name(name) is preset


def test_find_by_effect_name_rejects_junk(library) -> None:
    assert library.find_by_effect_name("Halloween") is None
    assert library.find_by_effect_name("Nope / Three zones") is None
    assert library.find_by_effect_name("") is None


def test_all_presets(library) -> None:
    assert sorted(library.effect_name(p) for p in library.all_presets()) == [
        "Christmas / One zone",
        "Halloween / Three zones",
    ]


def _zones(effect: int) -> list[dict]:
    return [
        {
            "start": 0,
            "end": 799,
            "effect": effect,
            "speed": 5,
            "width": 1,
            "brightness": 100,
            "direction": 0,
            "colours": [[255, 0, 0, 0, 0]],
            "palette": 0,
        }
    ]


def _library(scenes: list[dict]) -> "presets.PresetLibrary":
    return presets.PresetLibrary({"version": 1, "folders": {"F": scenes}, "palettes": {}})


def test_repeated_names_are_numbered() -> None:
    """Gouly reuses names within a folder for scenes that differ; each needs its own name."""
    library = _library(
        [
            {"name": "Christmas", "total": 800, "zones": _zones(1)},
            {"name": "Christmas", "total": 800, "zones": _zones(2)},
            {"name": "Christmas", "total": 800, "zones": _zones(3)},
        ]
    )
    # The first keeps the plain name, so favourites and automations saved before this still work.
    assert library.names_in("F") == ["Christmas", "Christmas (2)", "Christmas (3)"]
    assert library.find("F", "Christmas").zones[0]["effect"] == 1
    assert library.find("F", "Christmas (3)").zones[0]["effect"] == 3


def test_identical_scenes_are_dropped() -> None:
    library = _library(
        [
            {"name": "Same", "total": 800, "zones": _zones(1)},
            {"name": "Same", "total": 800, "zones": _zones(1)},
            {"name": "Same", "total": 800, "zones": _zones(2)},
        ]
    )
    assert library.names_in("F") == ["Same", "Same (2)"]
    assert library.find("F", "Same (2)").zones[0]["effect"] == 2


def test_a_name_that_looks_numbered_still_gets_its_own() -> None:
    library = _library(
        [
            {"name": "Glow", "total": 800, "zones": _zones(1)},
            {"name": "Glow (2)", "total": 800, "zones": _zones(2)},
            {"name": "Glow", "total": 800, "zones": _zones(3)},
        ]
    )
    assert library.names_in("F") == ["Glow", "Glow (2)", "Glow (3)"]
    assert library.find("F", "Glow (2)").zones[0]["effect"] == 2
    assert library.find("F", "Glow (3)").zones[0]["effect"] == 3
