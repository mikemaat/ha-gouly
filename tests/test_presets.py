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


# Custom presets ---------------------------------------------------------------------------

# A three zone scene as the Gouly app would send it, the last zone stopping short of the end.
APP_SCENE = [
    protocol.Segment(0, 500, 154, speed=90, palette=[(0, 255, 0, 0, 0, 255), (255, 255, 255, 0, 0, 255)],
                     panel_id=17, segment_id=0),
    protocol.Segment(501, 1000, 0, colours=((255, 80, 0, 0, 0), (0, 0, 0, 0, 0), (0, 0, 0, 0, 0)), segment_id=1),
    protocol.Segment(1001, 1500, 12, direction=1, brightness=128, segment_id=2,
                     palette=[(0, 32, 91, 0, 0, 255), (252, 76, 2, 0, 0, 255)], panel_id=3),
]


def _capture(segments: list) -> list:
    recorder = protocol.SceneRecorder()
    for frame in protocol.scene(LAYOUT, segments):
        recorder.feed(frame)
    return recorder.segments


def test_a_saved_scene_is_sent_back_exactly(tmp_path) -> None:
    captured = _capture(APP_SCENE)
    presets.save_custom(str(tmp_path), "Oilers", LAYOUT.total, presets.zones_from_segments(captured))
    library = presets.load(str(tmp_path))  # no library installed, only the custom preset
    assert library.folder_names == [presets.CUSTOM_FOLDER]
    frames = library.frames(library.find(presets.CUSTOM_FOLDER, "Oilers"), LAYOUT)
    assert frames == protocol.scene(LAYOUT, APP_SCENE)


def test_custom_presets_scale_to_a_different_string(tmp_path) -> None:
    presets.save_custom(str(tmp_path), "Oilers", LAYOUT.total, presets.zones_from_segments(_capture(APP_SCENE)))
    library = presets.load(str(tmp_path))
    small = protocol.Layout(800, (800, 0, 0, 0))
    segments = library.find(presets.CUSTOM_FOLDER, "Oilers").segments(small, library.palettes)
    assert segments[-1].end == small.total
    assert segments[0].palette == APP_SCENE[0].palette


def test_custom_presets_come_first_and_leave_the_library_alone(tmp_path) -> None:
    import json as _json

    (tmp_path / presets.PRESETS_FILE).write_text(_json.dumps(LIBRARY), encoding="utf-8")
    presets.save_custom(str(tmp_path), "Oilers", LAYOUT.total, presets.zones_from_segments(_capture(APP_SCENE)))
    library = presets.load(str(tmp_path))
    assert library.folder_names == [presets.CUSTOM_FOLDER, "Christmas", "Halloween"]
    assert _json.loads((tmp_path / presets.PRESETS_FILE).read_text(encoding="utf-8")) == LIBRARY


def test_saving_under_the_same_name_replaces_it(tmp_path) -> None:
    config = str(tmp_path)
    presets.save_custom(config, "Oilers", LAYOUT.total, presets.zones_from_segments(_capture(APP_SCENE)))
    presets.save_custom(config, "Flames", LAYOUT.total, presets.zones_from_segments(_capture(APP_SCENE[:1])))
    custom = presets.save_custom(config, "Oilers", LAYOUT.total, presets.zones_from_segments(_capture(APP_SCENE[1:])))
    assert [(p["name"], len(p["zones"])) for p in custom] == [("Oilers", 2), ("Flames", 1)]
    assert presets.load_custom(config) == custom


def test_delete_custom(tmp_path) -> None:
    config = str(tmp_path)
    presets.save_custom(config, "Oilers", LAYOUT.total, presets.zones_from_segments(_capture(APP_SCENE)))
    assert presets.delete_custom(config, "Nope") is None
    assert presets.delete_custom(config, "Oilers") == []
    assert presets.load(config) is None


def test_set_custom_updates_the_library(library) -> None:
    library.set_custom([{"name": "Oilers", "total": LAYOUT.total, "zones": presets.zones_from_segments(APP_SCENE)}])
    assert library.folder_names[0] == presets.CUSTOM_FOLDER
    assert library.find_by_effect_name("Custom / Oilers") is not None
    library.set_custom([])
    assert library.folder_names == ["Christmas", "Halloween"]


def test_unreadable_custom_file_is_ignored(tmp_path) -> None:
    (tmp_path / presets.CUSTOM_PRESETS_FILE).write_text("{oops", encoding="utf-8")
    assert presets.load_custom(str(tmp_path)) == []
