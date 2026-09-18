"""Light entity for a Gouly controller."""

from __future__ import annotations

import logging
import time
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ATTR_RGBW_COLOR,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import GoulyConfigEntry, protocol
from .const import (
    CONF_DEVICE_ID,
    CONF_FAVOURITES,
    CONF_PRESET_EFFECTS,
    DEFAULT_PRESET_EFFECTS,
    DOMAIN,
    MANUFACTURER,
    PRESET_EFFECTS_ALL,
    PRESET_EFFECTS_NONE,
)
from .effects import EFFECT_IDS, EFFECTS

_LOGGER = logging.getLogger(__name__)


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
    _attr_supported_features = LightEntityFeature.EFFECT

    def __init__(self, entry: GoulyConfigEntry) -> None:
        self._entry = entry
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
        self._attr_effect = None
        self._attr_effect_list = self._build_effect_list()
        # Effect echoes arrive after a preset is applied; don't let them relabel it.
        self._preset_applied_at = 0.0

    def _build_effect_list(self) -> list[str]:
        """Presets (favourites, all, or none) first, then the controller's own effects."""
        library = self._connection.presets
        mode = self._entry.options.get(CONF_PRESET_EFFECTS, DEFAULT_PRESET_EFFECTS)
        presets: list[str] = []
        if library is not None and mode != PRESET_EFFECTS_NONE:
            if mode == PRESET_EFFECTS_ALL:
                presets = [library.effect_name(p) for p in library.all_presets()]
            else:
                presets = [
                    library.effect_name(preset)
                    for folder, name in self._entry.options.get(CONF_FAVOURITES, [])
                    if (preset := library.find(folder, name)) is not None
                ]
        return presets + sorted(EFFECT_IDS)

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
                self._attr_effect = EFFECTS.get(0)
            if update.effect is not None and time.monotonic() - self._preset_applied_at > 5:
                self._attr_effect = EFFECTS.get(update.effect)
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        frames: list[bytes] = []
        if not self.is_on or not kwargs:
            frames += protocol.power(True)
            self._attr_is_on = True

        rgbw = kwargs.get(ATTR_RGBW_COLOR)
        if rgbw is not None:
            self._attr_rgbw_color = tuple(rgbw)
        effect = kwargs.get(ATTR_EFFECT)

        library = self._connection.presets
        preset = library.find_by_effect_name(effect) if (library and effect) else None
        if preset is not None:
            layout = self._connection.layout
            if layout is None:
                _LOGGER.warning("Gouly controller hasn't reported its LED layout yet")
            else:
                frames += library.frames(preset, layout)
                self._attr_effect = effect
                self._preset_applied_at = time.monotonic()
        elif effect is not None and effect in EFFECT_IDS:
            colour = (*(self._attr_rgbw_color or (255, 255, 255, 0)), 0)
            if frames:
                self._connection.send(frames)
                frames = []
            if not self._connection.apply_effect(EFFECT_IDS[effect], colour):
                _LOGGER.warning("Gouly controller hasn't reported its LED layout yet")
            else:
                self._attr_effect = effect
        elif rgbw is not None:
            frames += protocol.solid_colour(*rgbw)
            self._attr_effect = EFFECTS.get(0)

        if (brightness := kwargs.get(ATTR_BRIGHTNESS)) is not None:
            frames += protocol.brightness(brightness)
            self._attr_brightness = brightness
        self._connection.send(frames)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._connection.send(protocol.power(False))
        self._attr_is_on = False
        self.async_write_ha_state()
