"""gouly-keys: get the local keys for your Gouly controllers.

    gouly-keys                 set everything up, log in, print keys, find controllers
    gouly-keys --apk FILE      use an app file you downloaded yourself
    gouly-keys --app-version known-good   use the app version gouly-keys was tested with
    gouly-keys find            look for controllers on the network again (uses gouly_devices.json)
    gouly-keys clean           stop the emulator and delete everything gouly-keys downloaded
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path

from . import __version__
from .android import AndroidEnv, SetupError
from .ui import ask_yes_no, error, highlight, info, step, success, warn

DEFAULT_HOME = Path(os.environ.get("GOULY_KEYS_HOME", Path.home() / ".gouly-keys"))
DEFAULT_OUTPUT = Path("gouly_devices.json")


def _discovery():
    """The network discovery module is shared with the Home Assistant integration."""
    try:
        from . import discovery  # packaged copy (see pyproject.toml)

        return discovery
    except ImportError:
        path = Path(__file__).resolve().parents[2] / "custom_components" / "gouly" / "discovery.py"
        spec = importlib.util.spec_from_file_location("gouly_keys_discovery", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gouly-keys", description="Get local keys for Gouly lighting controllers.")
    parser.add_argument("command", nargs="?", default="extract", choices=["extract", "find", "clean"])
    parser.add_argument("--apk", type=Path, help="use this .apk/.xapk/.apks instead of downloading the app")
    parser.add_argument(
        "--app-version",
        default="latest",
        metavar="VERSION",
        help="app version to download: 'latest' (default, falls back to known-good if it doesn't work), "
        "'known-good', or a version code",
    )
    parser.add_argument("--output", "-o", type=Path, default=DEFAULT_OUTPUT, help="where to save the results")
    parser.add_argument("--home", type=Path, default=DEFAULT_HOME, help="where to keep the emulator and downloads")
    parser.add_argument("--no-scan", action="store_true", help="don't look for the controllers on the network")
    parser.add_argument("--version", action="version", version=f"gouly-keys {__version__}")
    args = parser.parse_args(argv)

    try:
        if args.command == "clean":
            return clean(args.home)
        if args.command == "find":
            return find(args.output)
        return extract(args)
    except KeyboardInterrupt:
        print()
        warn("Stopped. Run gouly-keys again to pick up where you left off.")
        return 130
    except SetupError as err:
        print()
        error(str(err))
        return 1


def extract(args: argparse.Namespace) -> int:
    from . import apk, capture  # imported late so `clean`/`find` work without frida

    print(
        f"\n{highlight('gouly-keys')} gets the device ID and local key for your Gouly lighting controllers,\n"
        "so Home Assistant can control them directly over your network.\n\n"
        "What happens:\n"
        "  1. A private Android emulator is set up (one time, about 6 GB of disk space)\n"
        "  2. The Gouly Lighting app is installed in it\n"
        "  3. You log in to the app with your normal Gouly account\n"
        "  4. The keys are read from the app as it loads your controllers\n\n"
        "Your password is typed into the Gouly app only; gouly-keys never sees or stores it.\n"
        f"Everything is kept in {args.home} (remove it with: gouly-keys clean)."
    )

    env = AndroidEnv(args.home)
    env.install()
    env.check_acceleration()

    if args.apk:
        releases: list[apk.AppRelease | None] = [None]
    else:
        requested = apk.resolve_release(apk.parse_version_arg(args.app_version))
        releases = [requested]
        if args.app_version.strip().lower() == "latest" and not requested.is_known_good:
            releases.append(None)  # resolved lazily: the known-good fallback

    env.start_emulator()
    capture.start_frida_server(env)

    def on_ready() -> None:
        print(
            f"\n    {highlight('In the emulator window:')}\n"
            "      1. Accept the app's prompts and log in with your Gouly account\n"
            "      2. Wait until your lights appear in the device list\n"
            "      3. Leave the app open; this window will continue automatically\n",
            flush=True,
        )

    def on_device(device: dict) -> None:
        success(f"Found {device.get('name') or 'a controller'} ({device['devId']})")
        info("Waiting a little longer in case you have more controllers...")

    devices: dict[str, dict] = {}
    for attempt, release in enumerate(releases):
        if attempt and release is None:
            release = apk.resolve_release(apk.KNOWN_GOOD_VERSION_CODE)
        if release is None:
            apks, version_code = apk.prepare_apks(args.apk, env.home), None
        else:
            apks, version_code = apk.prepare_apks(apk.download_release(release, env.cache), env.home), release.version_code
        env.install_apks(apk.PACKAGE, apks, version_code)

        step("Log in to the Gouly app")
        try:
            devices = capture.capture_devices(on_ready, on_device)
            break
        except capture.CaptureFailed as err:
            if attempt + 1 >= len(releases):
                raise capture.CaptureFailed(
                    f"{err}\n\nPlease open an issue at https://github.com/mikemaat/ha-gouly/issues "
                    "and include this message."
                ) from err
            warn(str(err))
            warn(
                f"Trying the Gouly app version gouly-keys was tested with "
                f"({apk.KNOWN_GOOD_VERSION_NAME}) instead."
            )

    if not devices:
        raise SetupError("No controllers were found. Make sure you logged in and your lights show in the app.")

    results = [
        {
            "name": d.get("name"),
            "device_id": d["devId"],
            "local_key": d["localKey"],
            "product_id": d.get("productId"),
            "host": None,
            "protocol_version": None,
        }
        for d in devices.values()
    ]

    if not args.no_scan:
        _locate(results)

    _save(results, args.output)
    _print_summary(results, args.output)

    if ask_yes_no("\nShut down the emulator now?"):
        env.stop_emulator()
    info("To free the disk space used by the emulator, run: gouly-keys clean")
    return 0


def find(output: Path) -> int:
    if not output.exists():
        raise SetupError(f"{output} not found. Run gouly-keys first, or pass --output.")
    results = json.loads(output.read_text(encoding="utf-8"))
    _locate(results)
    _save(results, output)
    _print_summary(results, output)
    return 0


def clean(home: Path) -> int:
    env = AndroidEnv(home)
    if env.adb.exists():
        try:
            if env.is_running():
                step("Stopping the emulator")
                env.stop_emulator()
        except Exception:  # noqa: BLE001
            pass
    if not home.exists():
        info(f"Nothing to remove ({home} doesn't exist).")
        return 0
    if not ask_yes_no(f"Delete {home} (emulator, Android SDK and downloads)?"):
        return 0
    shutil.rmtree(home, ignore_errors=True)
    success(f"Removed {home}")
    return 0


def _locate(results: list[dict]) -> None:
    discovery = _discovery()
    step("Looking for your controllers on the network (up to a minute)")
    networks = discovery.guess_local_networks()
    if not networks:
        warn("Couldn't work out which network this computer is on; skipping.")
        return
    info("Scanning " + ", ".join(str(n) for n in networks))
    hosts = discovery.find_tuya_hosts(networks)
    for device in results:
        found = discovery.discover(device["device_id"], device["local_key"], candidates=hosts)
        if found:
            device["host"], device["protocol_version"] = found
            success(f"{device.get('name') or device['device_id']} is at {device['host']}")
        else:
            warn(
                f"Couldn't find {device.get('name') or device['device_id']} on this network. "
                "That's fine if this computer isn't on the same network as the lights; "
                "Home Assistant will look for it during setup."
            )


def _save(results: list[dict], output: Path) -> None:
    output.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")


def _print_summary(results: list[dict], output: Path) -> None:
    step("Your controllers")
    for device in results:
        print(
            f"\n    {highlight(device.get('name') or 'Gouly controller')}\n"
            f"      Device ID : {device['device_id']}\n"
            f"      Local key : {device['local_key']}\n"
            f"      IP address: {device.get('host') or 'not found from this computer'}"
        )
    print(
        f"\nSaved to {highlight(str(output.resolve()))}\n"
        "Keep this file private: anyone on your network with it can control your lights.\n\n"
        "Next, in Home Assistant: Settings > Devices & services > Add integration > Gouly >\n"
        '"Paste gouly_devices.json", and paste the contents of that file.\n\n'
        "Note: if you reset or re-pair a controller in the Gouly app, its key changes and you'll\n"
        "need to run gouly-keys again."
    )


if __name__ == "__main__":
    sys.exit(main())
