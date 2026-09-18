"""Persistent local connection to a Gouly controller.

tinytuya is synchronous, so each controller gets one worker thread. The thread waits on
the device socket and a wake-up socket at the same time: commands are sent as soon as
they are queued, and pushed updates are read as soon as they arrive.

This module does not import Home Assistant.
"""

from __future__ import annotations

import logging
import queue
import select
import socket
import threading
import time
from collections.abc import Callable

import tinytuya

from . import protocol
from .const import DEFAULT_EFFECT_SPEED

_LOGGER = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 10.0
RECONNECT_DELAYS = (2, 5, 10, 30, 60)
# After this many failed connection attempts, try to find the controller at a new IP.
REDISCOVER_AFTER_FAILURES = 3
# Gap between frames of a multi-frame command; the Gouly app uses ~150-250 ms.
FRAME_GAP = 0.15

UpdateListener = Callable[[protocol.StateUpdate | None], None]
Rediscover = Callable[[], str | None]


class GoulyConnection:
    """Keeps a connection open, sends commands and reports state changes."""

    def __init__(
        self,
        host: str,
        device_id: str,
        local_key: str,
        version: float = 3.5,
        rediscover: Rediscover | None = None,
    ) -> None:
        self.host = host
        self.device_id = device_id
        self._local_key = local_key
        self.version = version
        self._rediscover = rediscover
        self._listeners: list[UpdateListener] = []
        self._outbox: queue.Queue[list[bytes]] = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._wake_recv, self._wake_send = socket.socketpair()
        self._wake_recv.setblocking(False)
        self.available = False
        self.layout: protocol.Layout | None = None
        # Current scene, tracked from the frames the controller echoes.
        self.effect_speed = DEFAULT_EFFECT_SPEED
        self.effect: int | None = None
        self.colour: protocol.Colour = (255, 255, 255, 0, 0)
        # Optional preset library, set during setup (see presets.py).
        self.presets: object | None = None
        # The preset currently chosen in the select entities, as (folder, name).
        self.selected_preset: tuple[str, str] | None = None

    # Public API (thread safe) --------------------------------------------------------

    def add_listener(self, listener: UpdateListener) -> Callable[[], None]:
        """Register for state updates (StateUpdate) and availability changes (None)."""
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(
                target=self._run, name=f"gouly-{self.device_id[-6:]}", daemon=True
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake()
        if self._thread is not None:
            self._thread.join(timeout=10)
            self._thread = None
        self._wake_recv.close()
        self._wake_send.close()

    def send(self, frames: list[bytes]) -> None:
        """Queue frames to send, in order."""
        self._outbox.put(frames)
        self._wake()

    def apply_effect(self, effect: int | None = None, colour: protocol.Colour | None = None) -> bool:
        """Run an effect across the whole string. False if the layout isn't known yet."""
        if effect is not None:
            self.effect = effect
        if colour is not None:
            self.colour = colour
        if self.layout is None or self.effect is None:
            return False
        self.send(protocol.effect(self.layout, self.effect, self.colour, speed=self.effect_speed))
        return True

    # Worker thread -------------------------------------------------------------------

    def _wake(self) -> None:
        try:
            self._wake_send.send(b"\x00")
        except OSError:
            pass

    def _notify(self, update: protocol.StateUpdate | None) -> None:
        for listener in list(self._listeners):
            try:
                listener(update)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Error in Gouly state listener")

    def _set_available(self, available: bool) -> None:
        if available != self.available:
            self.available = available
            self._notify(None)

    def _run(self) -> None:
        failures = 0
        while not self._stop.is_set():
            device = tinytuya.Device(
                self.device_id,
                self.host,
                self._local_key,
                version=self.version,
                persist=True,
                connection_timeout=5,
                connection_retry_limit=1,
            )
            try:
                status = device.status()
                if not isinstance(status, dict) or "dps" not in status:
                    raise ConnectionError(f"status failed: {status}")
                failures = 0
                _LOGGER.debug("Connected to Gouly controller %s at %s", self.device_id, self.host)
                self._set_available(True)
                self._handle_payload(status)
                self._outbox.put(protocol.query_state())
                self._serve(device)
            except Exception as err:  # noqa: BLE001
                if self._stop.is_set():
                    break
                failures += 1
                _LOGGER.debug("Gouly controller %s at %s: %s", self.device_id, self.host, err)
                self._set_available(False)
                if failures >= REDISCOVER_AFTER_FAILURES and self._rediscover is not None:
                    new_host = self._rediscover()
                    if new_host and new_host != self.host:
                        _LOGGER.info("Gouly controller %s moved to %s", self.device_id, new_host)
                        self.host = new_host
                        continue
                delay = RECONNECT_DELAYS[min(failures, len(RECONNECT_DELAYS)) - 1]
                self._stop.wait(delay)
            finally:
                device.close()
        self._set_available(False)

    def _serve(self, device: tinytuya.Device) -> None:
        last_heartbeat = time.monotonic()
        # Commands queued while disconnected (and the initial state query) go out first.
        self._flush_outbox(device)
        while not self._stop.is_set():
            sock = device.socket
            if sock is None:
                raise ConnectionError("socket closed")
            wait = max(0.0, HEARTBEAT_INTERVAL - (time.monotonic() - last_heartbeat))
            readable, _, _ = select.select([sock, self._wake_recv], [], [], wait)

            if self._wake_recv in readable:
                try:
                    while self._wake_recv.recv(1024):
                        pass
                except (BlockingIOError, OSError):
                    pass
                self._flush_outbox(device)

            if sock in readable:
                payload = device.receive()
                if payload is None and device.socket is None:
                    raise ConnectionError("connection closed by controller")
                self._handle_payload(payload)

            if time.monotonic() - last_heartbeat >= HEARTBEAT_INTERVAL:
                device.heartbeat(nowait=True)
                last_heartbeat = time.monotonic()

    def _flush_outbox(self, device: tinytuya.Device) -> None:
        while True:
            try:
                frames = self._outbox.get_nowait()
            except queue.Empty:
                return
            for index, frame in enumerate(frames):
                if index:
                    time.sleep(FRAME_GAP)
                result = device.set_value(
                    int(protocol.DP_TRANSPARENT), protocol.encode_dp(frame), nowait=True
                )
                if isinstance(result, dict) and result.get("Err"):
                    raise ConnectionError(f"send failed: {result}")

    def _handle_payload(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        if payload.get("Err"):
            if payload.get("Err") in ("901", "905", "914"):
                raise ConnectionError(f"controller error: {payload}")
            _LOGGER.debug("Ignoring error payload %s", payload)
            return
        dps = payload.get("dps")
        if isinstance(dps, dict):
            update = protocol.parse_dps(dps)
            if update.layout is not None:
                self.layout = update.layout
            if update.effect is not None:
                self.effect = update.effect
            if update.rgbw is not None:
                self.colour = (*update.rgbw, 0)
            if update:
                self._notify(update)
