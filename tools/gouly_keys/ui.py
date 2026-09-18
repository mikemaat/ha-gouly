"""Console output and download helpers (standard library only)."""

from __future__ import annotations

import os
import shutil
import sys
import urllib.request
from pathlib import Path

_COLOUR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
if _COLOUR and sys.platform == "win32":
    try:  # enable ANSI escape codes (ENABLE_VIRTUAL_TERMINAL_PROCESSING) in the Windows console
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
        else:
            _COLOUR = False
    except (AttributeError, OSError):
        _COLOUR = False

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOUR else text


def _supports(text: str) -> bool:
    """Whether the console encoding can print `text` (Windows consoles are often cp1252)."""
    try:
        text.encode(sys.stdout.encoding or "ascii")
    except (UnicodeEncodeError, LookupError):
        return False
    return True


_TICK = "✔" if _supports("✔") else "+"
_CROSS = "✘" if _supports("✘") else "x"


def step(message: str) -> None:
    print(f"\n{_c('1;36', '==>')} {_c('1', message)}", flush=True)


def info(message: str) -> None:
    print(f"    {message}", flush=True)


def success(message: str) -> None:
    print(f"{_c('1;32', _TICK)} {message}", flush=True)


def warn(message: str) -> None:
    print(f"{_c('1;33', '!')} {message}", flush=True)


def error(message: str) -> None:
    print(f"{_c('1;31', _CROSS)} {message}", file=sys.stderr, flush=True)


def highlight(text: str) -> str:
    return _c("1;35", text)


def ask_yes_no(question: str, default: bool = True) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    try:
        answer = input(f"{question} {suffix} ").strip().lower()
    except EOFError:
        return default
    return default if not answer else answer.startswith("y")


def download(url: str, dest: Path, *, headers: dict[str, str] | None = None) -> Path:
    """Download `url` to `dest` with a progress bar. Skips files that already exist."""
    if dest.exists() and dest.stat().st_size > 0:
        info(f"Using cached {dest.name}")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(request, timeout=120) as response, open(partial, "wb") as out:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        width = min(40, max(10, shutil.get_terminal_size().columns - 40))
        while chunk := response.read(1024 * 256):
            out.write(chunk)
            done += len(chunk)
            if total and sys.stdout.isatty():
                filled = int(width * done / total)
                print(
                    f"\r    [{'#' * filled}{'.' * (width - filled)}] {done / 1e6:6.1f} / {total / 1e6:.1f} MB",
                    end="", flush=True,
                )
        if total and sys.stdout.isatty():
            print()
    partial.replace(dest)
    return dest
