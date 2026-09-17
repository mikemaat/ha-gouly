"""Get the Gouly Lighting app package."""

from __future__ import annotations

import base64
import re
import shutil
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .android import SetupError
from .ui import USER_AGENT, download, info, step

PACKAGE = "com.goulyled.ledlight"

# The newest app version gouly-keys has been tested with. Used as a fallback when the
# latest version doesn't work, and selectable with --app-version known-good.
KNOWN_GOOD_VERSION_CODE = 109
KNOWN_GOOD_VERSION_NAME = "1.8.2"

# APKPure serves Play Store builds as an XAPK (base APK + split APKs) or a plain APK.
_DOWNLOAD_URL = "https://d.apkpure.com/b/{kind}/" + PACKAGE + "?{query}"
_KINDS = ("XAPK", "APK")


@dataclass(frozen=True)
class AppRelease:
    version_code: int
    version_name: str
    url: str
    kind: str

    @property
    def is_known_good(self) -> bool:
        return self.version_code == KNOWN_GOOD_VERSION_CODE

    def __str__(self) -> str:
        return f"{self.version_name} ({self.version_code})"


def parse_version_arg(value: str) -> int | None:
    """--app-version: 'latest' -> None, 'known-good' -> its version code, or a version code."""
    value = value.strip().lower()
    if value == "latest":
        return None
    if value in ("known-good", KNOWN_GOOD_VERSION_NAME):
        return KNOWN_GOOD_VERSION_CODE
    if value.isdigit():
        return int(value)
    raise SetupError(
        f"Unknown app version {value!r}. Use 'latest', 'known-good' or a version code "
        f"(e.g. {KNOWN_GOOD_VERSION_CODE} for {KNOWN_GOOD_VERSION_NAME})."
    )


def resolve_release(version_code: int | None) -> AppRelease:
    """Find the download for a version without downloading it (reads the redirect)."""
    query = "version=latest" if version_code is None else f"versionCode={version_code}"
    last_error = "no response"
    for kind in _KINDS:
        url = _DOWNLOAD_URL.format(kind=kind, query=query)
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Range": "bytes=0-0"})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                final_url = response.geturl()
        except OSError as err:
            last_error = str(err)
            continue
        release = _release_from_url(final_url, kind)
        if release is not None:
            return release
        last_error = "the download site didn't return an app file"
    wanted = "the latest version" if version_code is None else f"version code {version_code}"
    raise SetupError(
        f"Couldn't find {wanted} of the Gouly Lighting app for download ({last_error}).\n\n"
        f"Download it yourself (an .apk, .xapk or .apks file for {PACKAGE}, for example from "
        "apkpure.com or apkmirror.com) and run:\n\n    gouly-keys --apk path/to/file"
    )


def _release_from_url(url: str, kind: str) -> AppRelease | None:
    """Parse the CDN redirect, e.g. .../XAPK/<base64 'package_109_hash'>?filename=Gouly+Lighting_1.8.2_APKPure.xapk"""
    parsed = urllib.parse.urlparse(url)
    filename = urllib.parse.parse_qs(parsed.query).get("filename", [""])[0]
    name_match = re.search(r"_([\d.]+)_APKPure\.", filename)
    token = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    try:
        decoded = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode("utf-8", "replace")
    except ValueError:
        return None
    code_match = re.match(rf"{re.escape(PACKAGE)}_(\d+)_", decoded)
    if not name_match or not code_match:
        return None
    return AppRelease(int(code_match.group(1)), name_match.group(1), url, kind)


def download_release(release: AppRelease, cache: Path) -> Path:
    """Download a release (cached per version)."""
    step(f"Downloading the Gouly Lighting app {release}")
    dest = cache / f"{PACKAGE}-{release.version_code}.{release.kind.lower()}"
    download(release.url, dest)
    if not zipfile.is_zipfile(dest):
        dest.unlink(missing_ok=True)
        raise SetupError("The Gouly Lighting app download was corrupt. Run gouly-keys again, or use --apk.")
    return dest


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
