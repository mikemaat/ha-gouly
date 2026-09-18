"""Extract the Gouly app's preset library (folders, scenes, zones and palettes).

The library lives in the app package as a SQLite database plus a JSON effect table. It is
Gouly's content, so it is never redistributed with this project: this reads it from the app
on the user's own machine and writes a file the Home Assistant integration can load.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from .android import SetupError
from .ui import info, step, success

# Assets inside the Gouly Lighting APK.
DB_ASSET = "assets/gouly_pro_db_06.db"
EFFECTS_ASSET = "assets/json/SLProEffect01.json"

FORMAT_VERSION = 1


def _base_apk(source: Path, workdir: Path) -> Path:
    """The APK holding the assets (the base APK of an .xapk/.apks bundle)."""
    if source.is_dir():
        candidates = sorted(source.glob("*.apk"))
    elif source.suffix.lower() == ".apk":
        return source
    elif zipfile.is_zipfile(source):
        with zipfile.ZipFile(source) as bundle:
            names = [n for n in bundle.namelist() if n.lower().endswith(".apk")]
            candidates = []
            for name in names:
                if "config." in name or "split_" in name:
                    continue
                target = workdir / Path(name).name
                target.write_bytes(bundle.read(name))
                candidates.append(target)
    else:
        raise SetupError(f"Don't know how to read {source}")
    for apk in candidates:
        with zipfile.ZipFile(apk) as zf:
            if DB_ASSET in zf.namelist():
                return apk
    raise SetupError("Couldn't find the preset library inside the Gouly app package.")


def extract(source: Path) -> dict:
    """Read the preset library out of a Gouly app package."""
    step("Reading the preset library from the Gouly app")
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        apk = _base_apk(source, workdir)
        with zipfile.ZipFile(apk) as zf:
            names = zf.namelist()
            if DB_ASSET not in names:
                raise SetupError(f"{apk.name} doesn't contain {DB_ASSET}")
            db_path = workdir / "presets.db"
            db_path.write_bytes(zf.read(DB_ASSET))
            effects = json.loads(zf.read(EFFECTS_ASSET)) if EFFECTS_ASSET in names else []
        return _read_database(db_path, effects)


def _read_database(db_path: Path, effects: list[dict]) -> dict:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        return _read_tables(con, effects)
    finally:
        con.close()  # Windows can't delete the temp file while the database is open


def _read_tables(con: sqlite3.Connection, effects: list[dict]) -> dict:

    palettes: dict[str, list[list[int]]] = {}
    for row in con.execute("select presetId, colorsBean from PresetColor"):
        try:
            colours = json.loads(row["colorsBean"])
        except (TypeError, ValueError):
            continue
        palettes[str(row["presetId"])] = [
            [
                c.get("red", 0),
                c.get("green", 0),
                c.get("blue", 0),
                c.get("warmWhite", 0),
                c.get("white", 0),
                c.get("bright", 255),
            ]
            for c in colours
        ]

    zones_by_scene: dict[int, list[dict]] = {}
    for row in con.execute("select * from PartBean order by sceneId, segmentId"):
        colours = []
        for index in (1, 2, 3):
            bright = row[f"color{index}Bright"] or 0
            colours.append(
                [
                    (row[f"color{index}Red"] or 0) * bright // 255,
                    (row[f"color{index}Green"] or 0) * bright // 255,
                    (row[f"color{index}Blue"] or 0) * bright // 255,
                    (row[f"color{index}WarmWhite"] or 0) * bright // 255,
                    (row[f"color{index}White"] or 0) * bright // 255,
                ]
            )
        zones_by_scene.setdefault(row["sceneId"], []).append(
            {
                "start": row["startNum"],
                "end": row["endNum"],
                "effect": row["model"],
                "speed": row["speed"],
                "width": row["width"],
                "brightness": row["brightness"],
                "direction": row["direction"],
                "on": bool(row["open"]),
                "colours": colours,
                "palette": row["panelId"],
            }
        )

    folders: dict[str, list[dict]] = {}
    for row in con.execute("select * from SceneBean order by folderName, sceneName"):
        zones = zones_by_scene.get(row["sceneId"])
        if not zones:
            continue
        folder = (row["folderName"] or "Other").strip()
        folders.setdefault(folder, []).append(
            {
                "name": (row["sceneName"] or "").strip() or f"Scene {row['sceneId']}",
                "total": row["total"] or 800,
                "zones": zones,
            }
        )

    used = {str(z["palette"]) for scenes in folders.values() for s in scenes for z in s["zones"]}
    library = {
        "version": FORMAT_VERSION,
        "effects": {str(e["modeId"]): e["modeName"] for e in effects if not e.get("isMusic")},
        "palettes": {k: v for k, v in palettes.items() if k in used},
        "folders": folders,
    }
    scenes = sum(len(v) for v in folders.values())
    info(f"{scenes} presets in {len(folders)} folders, {len(library['palettes'])} colour palettes")
    return library


def save(library: dict, output: Path) -> None:
    output.write_text(json.dumps(library, separators=(",", ":")), encoding="utf-8")
    success(f"Saved {output.resolve()} ({output.stat().st_size / 1e6:.1f} MB)")
