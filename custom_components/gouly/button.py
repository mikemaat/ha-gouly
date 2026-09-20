"""Add the selected preset to the light's effect list."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import GoulyConfigEntry
from .const import CONF_DEVICE_ID, CONF_FAVOURITES, DOMAIN, MANUFACTURER

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GoulyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the favourite button when a preset library is available."""
    if not entry.runtime_data.presets:
        return
    async_add_entities([GoulyFavouriteButton(entry)])


class GoulyFavouriteButton(ButtonEntity):
    """Adds the preset currently chosen in the Preset select to the favourites.

    The Gouly card has a star on every preset; this is the way to do it without the card.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "add_favourite"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_should_poll = False

    def __init__(self, entry: GoulyConfigEntry) -> None:
        self._entry = entry
        self._connection = entry.runtime_data
        device_id = entry.data[CONF_DEVICE_ID]
        self._attr_unique_id = f"{device_id}_add_favourite"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=entry.title,
            manufacturer=MANUFACTURER,
        )

    async def async_added_to_hass(self) -> None:
        def listener(_update) -> None:
            self.hass.loop.call_soon_threadsafe(self._handle_update)

        self.async_on_remove(self._connection.add_listener(listener))

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        return self._connection.available

    async def async_press(self) -> None:
        selected = self._connection.selected_preset
        if selected is None:
            raise HomeAssistantError(
                "Choose a preset first: pick a Preset folder, then a Preset, then press this."
            )
        folder, name = selected
        favourites = [list(f) for f in self._entry.options.get(CONF_FAVOURITES, [])]
        if [folder, name] in favourites:
            _LOGGER.debug("%s / %s is already a favourite", folder, name)
            return
        favourites.append([folder, name])
        self.hass.config_entries.async_update_entry(
            self._entry, options={**self._entry.options, CONF_FAVOURITES: favourites}
        )
