"""Optional preset library, extracted from the Gouly app by `gouly-keys presets`.

The library is Gouly's content and is not shipped with this integration. If the user drops
`gouly_presets.json` into their Home Assistant config folder, presets become available.

Custom presets - scenes saved from the lights - live in their own file,
`gouly_custom_presets.json`, so re-installing the library never touches them. They appear in the
library as the Custom folder.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from . import protocol

_LOGGER = logging.getLogger(__name__)

PRESETS_FILE = "gouly_presets.json"
CUSTOM_PRESETS_FILE = "gouly_custom_presets.json"
CUSTOM_FOLDER = "Custom"
SUPPORTED_VERSION = 1
# The app's preset library is designed for this many LEDs; zones are scaled from it.
DESIGN_TOTAL = 800


@dataclass(slots=True)
class Preset:
    name: str
    folder: str
    total: int
    zones: list[dict]

    def segments(self, layout: protocol.Layout, palettes: dict[str, list]) -> list[protocol.Segment]:
        """Scale the preset's zones onto this controller's string."""
        design_total = self.total or DESIGN_TOTAL
        scale = layout.total / design_total
        segments: list[protocol.Segment] = []
        for index, zone in enumerate(self.zones):
            start = round(zone["start"] * scale)
            # Stretch the last zone to the end so rounding never leaves a dark tail. Unscaled (a
            # custom preset on the string it was saved from) it's shown exactly as it was.
            last = index == len(self.zones) - 1
            end = layout.total if last and scale != 1 else round((zone["end"] + 1) * scale)
            if start >= end or start >= layout.total:
                continue
            colours = tuple(tuple(c) for c in zone["colours"])  # type: ignore[assignment]
            segments.append(
                protocol.Segment(
                    start=start,
                    end=min(end, layout.total),
                    effect=zone["effect"],
                    speed=zone["speed"],
                    width=zone["width"],
                    brightness=zone["brightness"],
                    direction=zone["direction"],
                    colours=colours,
                    panel_id=zone["palette"],
                    # Custom presets carry their palette; the library's are shared by id.
                    palette=[
                        tuple(c)
                        for c in zone.get("palette_colours", palettes.get(str(zone["palette"]), []))
                    ],
                    segment_id=index,
                    is_on=zone.get("on", True),
                )
            )
        return segments


def _named(presets: list[Preset]) -> list[Preset]:
    """Give every preset in a folder its own name.

    Gouly's library reuses names within a folder - 'Christmas' appears six times in Christmas 1 -
    and those are different scenes, not copies. Presets are referred to by name here, so without
    this only the first of each could ever be picked. The first keeps the plain name so existing
    favourites and automations still match; the rest are numbered.

    Scenes that really are identical are dropped.
    """
    bodies: set[tuple] = set()
    taken: set[str] = set()
    unique: list[Preset] = []
    for preset in presets:
        body = (preset.name, preset.total, json.dumps(preset.zones, sort_keys=True))
        if body in bodies:
            continue
        bodies.add(body)
        name, count = preset.name, 1
        while name in taken:
            count += 1
            name = f"{preset.name} ({count})"
        taken.add(name)
        preset.name = name
        unique.append(preset)
    return unique


def zones_from_segments(segments: list[protocol.Segment]) -> list[dict]:
    """Describe a scene the way the library does, so it can be stored as a custom preset."""
    return [
        {
            "start": seg.start,
            "end": seg.end - 1,
            "effect": seg.effect,
            "speed": seg.speed,
            "width": seg.width,
            "brightness": seg.brightness,
            "direction": seg.direction,
            "on": seg.is_on,
            "colours": [list(c) for c in seg.colours],
            "palette": seg.panel_id,
            "palette_colours": [list(c) for c in seg.palette],
        }
        for seg in segments
    ]


class PresetLibrary:
    """Presets grouped by folder, with the custom presets first."""

    def __init__(self, data: dict, custom: list[dict] | None = None) -> None:
        self.palettes: dict[str, list] = data.get("palettes", {})
        self.folders: dict[str, list[Preset]] = {}
        for folder, scenes in sorted(data.get("folders", {}).items()):
            self.folders[folder] = _named(
                [
                    Preset(s["name"], folder, s.get("total", DESIGN_TOTAL), s["zones"])
                    for s in scenes
                ]
            )
        self.set_custom(custom or [])

    def set_custom(self, scenes: list[dict]) -> None:
        """Replace the Custom folder."""
        self.folders.pop(CUSTOM_FOLDER, None)
        if scenes:
            custom = [Preset(s["name"], CUSTOM_FOLDER, s["total"], s["zones"]) for s in scenes]
            self.folders = {CUSTOM_FOLDER: custom, **self.folders}

    def __bool__(self) -> bool:
        return bool(self.folders)

    @property
    def folder_names(self) -> list[str]:
        return list(self.folders)

    def names_in(self, folder: str) -> list[str]:
        return [p.name for p in self.folders.get(folder, [])]

    def effect_name(self, preset: Preset) -> str:
        """How a preset is named in the light's effect list."""
        return f"{preset.folder} / {preset.name}"

    def all_presets(self) -> list[Preset]:
        return [preset for presets in self.folders.values() for preset in presets]

    def find_by_effect_name(self, effect: str) -> Preset | None:
        folder, _, name = effect.partition(" / ")
        return self.find(folder, name) if name else None

    def find(self, folder: str, name: str) -> Preset | None:
        return next((p for p in self.folders.get(folder, []) if p.name == name), None)

    def frames(self, preset: Preset, layout: protocol.Layout) -> list[bytes]:
        return protocol.scene(layout, preset.segments(layout, self.palettes))


def validate(data: object) -> tuple[int, int]:
    """Check an uploaded library. Returns (folders, presets) or raises ValueError."""
    if not isinstance(data, dict):
        raise ValueError("not a preset library")
    if data.get("version") != SUPPORTED_VERSION:
        raise ValueError(f"unsupported format version {data.get('version')!r}")
    folders = data.get("folders")
    if not isinstance(folders, dict) or not folders:
        raise ValueError("no presets in the file")
    scenes = 0
    for name, presets in folders.items():
        if not isinstance(presets, list):
            raise ValueError(f"folder {name!r} is malformed")
        for preset in presets:
            if not isinstance(preset, dict) or not preset.get("zones"):
                raise ValueError(f"a preset in {name!r} has no zones")
            scenes += 1
    return len(folders), scenes


def install(source: Path, config_dir: str) -> tuple[int, int]:
    """Validate an uploaded preset library and put it where the integration loads it."""
    data = json.loads(source.read_text(encoding="utf-8"))
    counts = validate(data)
    target = Path(config_dir) / PRESETS_FILE
    target.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    _LOGGER.info("Installed preset library at %s", target)
    return counts


def load_custom(config_dir: str) -> list[dict]:
    """The custom presets saved from the lights, in the order they were first saved."""
    path = Path(config_dir) / CUSTOM_PRESETS_FILE
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        _LOGGER.warning("Couldn't read %s: %s", path, err)
        return []
    if not isinstance(data, dict) or data.get("version") != SUPPORTED_VERSION:
        _LOGGER.warning("%s isn't a custom preset file this integration can read", path)
        return []
    return [
        p for p in data.get("presets", []) if isinstance(p, dict) and p.get("name") and p.get("zones")
    ]


def save_custom(config_dir: str, name: str, total: int, zones: list[dict]) -> list[dict]:
    """Add a custom preset, replacing one with the same name. Returns them all."""
    presets = load_custom(config_dir)
    preset = {"name": name, "total": total, "zones": zones}
    index = next((i for i, p in enumerate(presets) if p["name"] == name), None)
    if index is None:
        presets.append(preset)
    else:
        presets[index] = preset
    _write_custom(config_dir, presets)
    return presets


def delete_custom(config_dir: str, name: str) -> list[dict] | None:
    """Remove a custom preset. Returns what's left, or None if there was no such preset."""
    presets = load_custom(config_dir)
    remaining = [p for p in presets if p["name"] != name]
    if len(remaining) == len(presets):
        return None
    _write_custom(config_dir, remaining)
    return remaining


def _write_custom(config_dir: str, presets: list[dict]) -> None:
    path = Path(config_dir) / CUSTOM_PRESETS_FILE
    data = {"version": SUPPORTED_VERSION, "presets": presets}
    path.write_text(json.dumps(data, indent=1), encoding="utf-8")


def load(config_dir: str) -> PresetLibrary | None:
    """Load the preset library and custom presets from the config folder, if there are any."""
    custom = load_custom(config_dir)
    data = _load_library(Path(config_dir) / PRESETS_FILE)
    if data is None and not custom:
        return None
    library = PresetLibrary(data or {}, custom)
    _LOGGER.info(
        "Loaded %s presets in %s folders from %s",
        sum(len(v) for v in library.folders.values()),
        len(library.folders),
        config_dir,
    )
    return library


def _load_library(path: Path) -> dict | None:
    """The library extracted from the Gouly app, if it's installed and readable."""
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        _LOGGER.warning("Couldn't read %s: %s", path, err)
        return None
    if data.get("version") != SUPPORTED_VERSION:
        _LOGGER.warning(
            "%s has format version %s, this integration expects %s; re-run 'gouly-keys presets'",
            path,
            data.get("version"),
            SUPPORTED_VERSION,
        )
        return None
    return data
