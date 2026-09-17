"""Get the Gouly Lighting app package."""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

from .android import SetupError
from .ui import download, info, step

PACKAGE = "com.goulyled.ledlight"
PLAY_STORE_URL = f"https://play.google.com/store/apps/details?id={PACKAGE}"
# APKPure serves the current Play Store build as an XAPK (base APK + split APKs).
DOWNLOAD_URLS = (
    f"https://d.apkpure.com/b/XAPK/{PACKAGE}?version=latest",
    f"https://d.apkpure.com/b/APK/{PACKAGE}?version=latest",
)


def download_app(cache: Path) -> Path:
    """Download the latest Gouly Lighting app. Returns the downloaded file."""
    step("Downloading the Gouly Lighting app")
    dest = cache / f"{PACKAGE}.xapk"
    dest.unlink(missing_ok=True)  # always fetch the latest version
    last_error: Exception | None = None
    for url in DOWNLOAD_URLS:
        try:
            download(url, dest)
            if zipfile.is_zipfile(dest):
                return dest
            last_error = SetupError("the download wasn't an app package")
        except OSError as err:
            last_error = err
        dest.unlink(missing_ok=True)
    raise SetupError(
        "Couldn't download the Gouly Lighting app automatically "
        f"({last_error}).\n\nDownload it yourself (an .apk, .xapk or .apks file for {PACKAGE}, "
        "for example from apkpure.com or apkmirror.com) and run:\n\n"
        "    gouly-keys --apk path/to/file"
    )


def prepare_apks(source: Path, workdir: Path) -> list[Path]:
    """Turn an .apk, .xapk/.apks bundle or a folder of split APKs into a list to install."""
    if source.is_dir():
        apks = sorted(source.glob("*.apk"))
    elif source.suffix.lower() == ".apk":
        apks = [source]
    elif zipfile.is_zipfile(source):
        target = workdir / "apks"
        shutil.rmtree(target, ignore_errors=True)
        target.mkdir(parents=True)
        with zipfile.ZipFile(source) as bundle:
            names = [n for n in bundle.namelist() if n.lower().endswith(".apk") and "/" not in n.strip("/")]
            if not names:
                raise SetupError(f"{source.name} doesn't contain any APK files.")
            for name in names:
                bundle.extract(name, target)
        apks = sorted(target.glob("*.apk"))
    else:
        raise SetupError(f"Don't know how to install {source}")
    if not apks:
        raise SetupError(f"No APK files found in {source}")
    # The base APK must come first; split APKs are named config.*.apk or split_*.apk.
    apks.sort(key=lambda p: (p.name.startswith(("config.", "split_")), p.name))
    info("App files: " + ", ".join(p.name for p in apks))
    return apks
