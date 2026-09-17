"""Light entity for a Gouly controller."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_RGBW_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import GoulyConfigEntry, protocol
from .const import CONF_DEVICE_ID, DOMAIN, MANUFACTURER


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GoulyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Gouly light."""
    async_add_entities([GoulyLight(entry)])


class GoulyLight(LightEntity):
    """A Gouly lighting controller, exposed as a single RGBW light."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_should_poll = False
    _attr_color_mode = ColorMode.RGBW
    _attr_supported_color_modes = {ColorMode.RGBW}

    def __init__(self, entry: GoulyConfigEntry) -> None:
        self._connection = entry.runtime_data
        device_id = entry.data[CONF_DEVICE_ID]
        self._attr_unique_id = device_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=entry.title,
            manufacturer=MANUFACTURER,
        )
        self._attr_is_on = None
        self._attr_brightness = None
        self._attr_rgbw_color = None

    @property
    def available(self) -> bool:
        return self._connection.available

    async def async_added_to_hass(self) -> None:
        def listener(update: protocol.StateUpdate | None) -> None:
            # Called from the connection thread.
            self.hass.loop.call_soon_threadsafe(self._handle_update, update)

        self.async_on_remove(self._connection.add_listener(listener))
        if self._connection.available:
            self._connection.send(protocol.query_state())

    @callback
    def _handle_update(self, update: protocol.StateUpdate | None) -> None:
        if update is not None:
            if update.is_on is not None:
                self._attr_is_on = update.is_on
            if update.brightness is not None:
                self._attr_brightness = update.brightness
            if update.rgbw is not None:
                self._attr_rgbw_color = update.rgbw
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        frames: list[bytes] = []
        if not self.is_on or not kwargs:
            frames += protocol.power(True)
            self._attr_is_on = True
        if (rgbw := kwargs.get(ATTR_RGBW_COLOR)) is not None:
            frames += protocol.solid_colour(*rgbw)
            self._attr_rgbw_color = tuple(rgbw)
        if (brightness := kwargs.get(ATTR_BRIGHTNESS)) is not None:
            frames += protocol.brightness(brightness)
            self._attr_brightness = brightness
        self._connection.send(frames)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._connection.send(protocol.power(False))
        self._attr_is_on = False
        self.async_write_ha_state()
