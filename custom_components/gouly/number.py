"""Effect speed control for a Gouly controller."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import GoulyConfigEntry
from .const import CONF_DEVICE_ID, DOMAIN, MANUFACTURER


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GoulyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Gouly effect speed number."""
    async_add_entities([GoulyEffectSpeed(entry)])


class GoulyEffectSpeed(NumberEntity):
    """Speed used when an effect is applied. Re-applies the current effect when changed."""

    _attr_has_entity_name = True
    _attr_translation_key = "effect_speed"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = 1
    _attr_native_max_value = 255
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER
    _attr_should_poll = False

    def __init__(self, entry: GoulyConfigEntry) -> None:
        self._connection = entry.runtime_data
        device_id = entry.data[CONF_DEVICE_ID]
        self._attr_unique_id = f"{device_id}_effect_speed"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=entry.title,
            manufacturer=MANUFACTURER,
        )

    async def async_added_to_hass(self) -> None:
        # The connection usually comes up after the entity is added; follow its updates so
        # availability and the current value don't stay stuck at their first value.
        def listener(_update) -> None:
            self.hass.loop.call_soon_threadsafe(self._handle_update)

        self.async_on_remove(self._connection.add_listener(listener))

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        return self._connection.available

    @property
    def native_value(self) -> float:
        return self._connection.effect_speed

    async def async_set_native_value(self, value: float) -> None:
        self._connection.effect_speed = max(1, min(255, int(value)))
        self._connection.apply_effect()
        self.async_write_ha_state()
