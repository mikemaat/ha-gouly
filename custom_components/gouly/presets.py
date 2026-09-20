"""Optional preset library, extracted from the Gouly app by `gouly-keys presets`.

The library is Gouly's content and is not shipped with this integration. If the user drops
`gouly_presets.json` into their Home Assistant config folder, presets become available.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from . import protocol

_LOGGER = logging.getLogger(__name__)

PRESETS_FILE = "gouly_presets.json"
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
            # Stretch the last zone to the end so rounding never leaves a dark tail.
            end = layout.total if index == len(self.zones) - 1 else round((zone["end"] + 1) * scale)
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
                    palette=[tuple(c) for c in palettes.get(str(zone["palette"]), [])],
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


class PresetLibrary:
    """Presets grouped by folder."""

    def __init__(self, data: dict) -> None:
        self.palettes: dict[str, list] = data.get("palettes", {})
        self.folders: dict[str, list[Preset]] = {}
        for folder, scenes in sorted(data.get("folders", {}).items()):
            self.folders[folder] = _named(
                [
                    Preset(s["name"], folder, s.get("total", DESIGN_TOTAL), s["zones"])
                    for s in scenes
                ]
            )

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


def load(config_dir: str) -> PresetLibrary | None:
    """Load the preset library from the Home Assistant config folder, if present."""
    path = Path(config_dir) / PRESETS_FILE
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
    library = PresetLibrary(data)
    _LOGGER.info(
        "Loaded %s presets in %s folders from %s",
        sum(len(v) for v in library.folders.values()),
        len(library.folders),
        path,
    )
    return library
