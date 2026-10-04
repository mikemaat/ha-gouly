"""The name the Custom preset save from lights button saves under."""

from __future__ import annotations

from homeassistant.components.text import TextEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import GoulyConfigEntry
from .const import CONF_DEVICE_ID, DOMAIN, MANUFACTURER


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GoulyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the custom preset name."""
    async_add_entities([GoulyCustomPresetName(entry)])


class GoulyCustomPresetName(TextEntity, RestoreEntity):
    """Name for the next custom preset. Kept, so re-saving after a tweak in the app updates it."""

    _attr_has_entity_name = True
    _attr_translation_key = "custom_preset_name"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_should_poll = False
    _attr_native_max = 64

    def __init__(self, entry: GoulyConfigEntry) -> None:
        self._connection = entry.runtime_data
        device_id = entry.data[CONF_DEVICE_ID]
        self._attr_unique_id = f"{device_id}_custom_preset_name"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=entry.title,
            manufacturer=MANUFACTURER,
        )

    async def async_added_to_hass(self) -> None:
        if (last := await self.async_get_last_state()) is not None and last.state not in (
            "unknown",
            "unavailable",
        ):
            self._connection.custom_preset_name = last.state

    @property
    def native_value(self) -> str:
        return self._connection.custom_preset_name

    async def async_set_value(self, value: str) -> None:
        self._connection.custom_preset_name = value
        self.async_write_ha_state()
