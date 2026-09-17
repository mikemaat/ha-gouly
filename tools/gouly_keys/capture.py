"""Run the Gouly app under Frida and collect device credentials."""

from __future__ import annotations

import json
import lzma
import queue
import time
from importlib import resources
from pathlib import Path

import frida
import frida_tools

from .android import FRIDA_ARCH, SERIAL, AndroidEnv, SetupError
from .apk import PACKAGE
from .ui import download, info, step

REMOTE_SERVER = "/data/local/tmp/gouly-frida-server"
# How long to wait for the hook to report in after the app starts.
HOOK_TIMEOUT = 90


class CaptureFailed(SetupError):
    """The app or the hook didn't work; trying another app version may help."""


def start_frida_server(env: AndroidEnv) -> None:
    """Install and start a frida-server matching the installed frida Python package."""
    step("Starting Frida in the emulator")
    version = frida.__version__
    local = env.cache / f"frida-server-{version}-android-{FRIDA_ARCH}"
    if not local.exists():
        archive = download(
            f"https://github.com/frida/frida/releases/download/{version}/frida-server-{version}-android-{FRIDA_ARCH}.xz",
            env.cache / f"frida-server-{version}-android-{FRIDA_ARCH}.xz",
        )
        local.write_bytes(lzma.decompress(archive.read_bytes()))
    remote = f"{REMOTE_SERVER}-{version}"
    env.adb_cmd("push", str(local), remote, timeout=300)
    env.adb_cmd("shell", f"chmod 755 {remote}; setenforce 0; pkill -f gouly-frida-server", check=False)
    try:
        env.adb_cmd("shell", f"nohup {remote} >/dev/null 2>&1 &", timeout=10, check=False)
    except Exception:  # noqa: BLE001 - adb may keep the shell open; the server still starts
        pass


def _frida_device(timeout: float = 60) -> frida.core.Device:
    manager = frida.get_device_manager()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for device in manager.enumerate_devices():
            if device.id == SERIAL:
                try:
                    device.enumerate_processes()
                    return device
                except frida.ServerNotRunningError:
                    break
                except frida.TransportError:
                    break
        time.sleep(1)
    raise SetupError("Couldn't connect to Frida in the emulator.")


def _agent_source() -> str:
    """The agent, preceded by Frida's Java bridge.

    Frida 17 no longer bundles the Java bridge into the runtime. The frida CLI injects it
    from frida-tools; we evaluate the same bridge file up front.
    """
    bridge = (Path(frida_tools.__file__).parent / "bridges" / "java.js").read_text(encoding="utf-8")
    wrapped = (
        "(function () { " + bridge + "\nObject.defineProperty(globalThis, 'Java', { value: bridge });"
        "\nreturn bridge;\n })();"
    )
    agent = resources.files(__package__).joinpath("agent.js").read_text(encoding="utf-8")
    return f"Script.evaluate('/frida/bridges/java.js', {json.dumps(wrapped)});\n{agent}"


def capture_devices(
    on_ready: callable,
    on_device: callable,
    idle_seconds: float = 20,
    timeout: float = 20 * 60,
) -> dict[str, dict]:
    """Launch the Gouly app with the hook and return devices by device ID.

    Returns once at least one device has been captured and no new device has shown up
    for `idle_seconds`, or after `timeout`.
    """
    device = _frida_device()
    messages: queue.Queue[dict] = queue.Queue()
    pid = device.spawn([PACKAGE])
    session = device.attach(pid)
    script = session.create_script(_agent_source())

    def on_message(message: dict, _data: bytes | None) -> None:
        if message.get("type") == "error":
            messages.put({"type": "agent-error", "description": message.get("description")})
            return
        payload = message.get("payload")
        if isinstance(payload, dict):
            messages.put(payload)

    detached: list[str] = []
    session.on("detached", lambda reason, crash: detached.append(str(reason)))
    script.on("message", on_message)
    try:
        script.load()
    except Exception as err:  # noqa: BLE001 - frida raises several unrelated error types here
        raise CaptureFailed(f"The hook failed to load in the Gouly app: {err}") from err
    device.resume(pid)

    devices: dict[str, dict] = {}
    first_seen: dict[str, float] = {}
    announced: set[str] = set()
    started = time.monotonic()
    last_new = None

    def announce(ready_only: bool) -> None:
        # The key often arrives a moment before the name; wait briefly so we can show the name.
        for dev_id, dev in devices.items():
            if dev_id not in announced and (not ready_only or dev.get("name") or time.monotonic() - first_seen[dev_id] > 5):
                announced.add(dev_id)
                on_device(dev)

    hooks_reported = False
    try:
        while True:
            if detached:
                if devices:
                    break
                raise CaptureFailed(f"The Gouly app closed unexpectedly ({detached[0]}).")
            now = time.monotonic()
            if not hooks_reported and now - started > HOOK_TIMEOUT:
                raise CaptureFailed("The hook never started inside the Gouly app.")
            if now - started > timeout:
                break
            if last_new is not None and now - last_new > idle_seconds:
                break
            announce(ready_only=True)
            try:
                msg = messages.get(timeout=1)
            except queue.Empty:
                continue
            if msg.get("type") == "gouly-hooks":
                hooks_reported = True
                if not msg.get("hooked"):
                    raise CaptureFailed(
                        "This version of the Gouly app doesn't have the code gouly-keys hooks into "
                        f"(missing: {', '.join(msg.get('missing') or [])}). The app has probably changed."
                    )
                if msg.get("missing"):
                    info(f"(some hooks unavailable: {', '.join(msg['missing'])})")
            elif msg.get("type") == "gouly-ready":
                on_ready()
            elif msg.get("type") == "gouly-device":
                found = msg["device"]
                dev_id = found["devId"]
                if dev_id not in devices:
                    first_seen[dev_id] = last_new = time.monotonic()
                devices[dev_id] = {**devices.get(dev_id, {}), **{k: v for k, v in found.items() if v}}
            elif msg.get("type") == "agent-error":
                if not hooks_reported:
                    raise CaptureFailed(f"The hook crashed inside the Gouly app: {msg.get('description')}")
                info(f"(hook warning: {msg.get('description')})")
        announce(ready_only=False)
    finally:
        try:
            session.detach()
        except frida.InvalidOperationError:
            pass
    return devices
