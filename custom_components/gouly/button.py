"""Buttons: add the selected preset to the favourites, save the lights as a custom preset."""

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
from .services import async_save_custom_preset

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GoulyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the buttons; the favourite one only when there are presets to pick from."""
    buttons: list[ButtonEntity] = [GoulySaveCustomPresetButton(entry)]
    if entry.runtime_data.presets:
        buttons.append(GoulyFavouriteButton(entry))
    async_add_entities(buttons)


class _GoulyBaseButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_should_poll = False

    def __init__(self, entry: GoulyConfigEntry, key: str) -> None:
        self._entry = entry
        self._connection = entry.runtime_data
        device_id = entry.data[CONF_DEVICE_ID]
        self._attr_unique_id = f"{device_id}_{key}"
        self._attr_translation_key = key
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


class GoulyFavouriteButton(_GoulyBaseButton):
    """Adds the preset currently chosen in the Preset select to the favourites.

    The Gouly card has a star on every preset; this is the way to do it without the card.
    """

    def __init__(self, entry: GoulyConfigEntry) -> None:
        super().__init__(entry, "add_favourite")

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


class GoulySaveCustomPresetButton(_GoulyBaseButton):
    """Saves what the lights are showing as a custom preset, named by the Custom preset name text.

    Make a scene in the Gouly app, send it to the lights, then press this to keep it in Home
    Assistant. Saving under a name that already exists replaces that preset.
    """

    def __init__(self, entry: GoulyConfigEntry) -> None:
        super().__init__(entry, "save_custom_preset")

    async def async_press(self) -> None:
        name = self._connection.custom_preset_name
        if not name.strip():
            raise HomeAssistantError("Type a name in Custom preset name first, then press this.")
        saved = await async_save_custom_preset(self.hass, self._entry, name)
        _LOGGER.info("Saved the lights as %s", saved)
