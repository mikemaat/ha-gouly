"""Preset selectors for a Gouly controller (only when a preset library is installed)."""

from __future__ import annotations

import logging
from collections.abc import Callable

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import GoulyConfigEntry
from .const import CONF_DEVICE_ID, DOMAIN, MANUFACTURER
from .presets import PresetLibrary

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GoulyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the preset selectors if a preset library was loaded."""
    library = entry.runtime_data.presets
    if not library:
        return
    folder = GoulyFolderSelect(entry, library)
    async_add_entities([folder, GoulyPresetSelect(entry, library, folder)])


class _GoulyBaseSelect(SelectEntity):
    _attr_has_entity_name = True
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
        # The connection usually comes up after the entity is added; follow its updates so
        # availability doesn't stay stuck at its first value.
        def listener(_update) -> None:
            self.hass.loop.call_soon_threadsafe(self._handle_update)

        self.async_on_remove(self._connection.add_listener(listener))

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        return self._connection.available


class GoulyFolderSelect(_GoulyBaseSelect):
    """Which preset folder (Christmas, Halloween, ...) the preset list shows."""

    def __init__(self, entry: GoulyConfigEntry, library: PresetLibrary) -> None:
        super().__init__(entry, "preset_folder")
        self._library = library
        self._attr_options = library.folder_names
        self._attr_current_option = self._attr_options[0] if self._attr_options else None
        self._listeners: list[Callable[[str], None]] = []

    def add_listener(self, listener: Callable[[str], None]) -> None:
        self._listeners.append(listener)

    async def async_select_option(self, option: str) -> None:
        self._attr_current_option = option
        self.async_write_ha_state()
        for listener in self._listeners:
            listener(option)


class GoulyPresetSelect(_GoulyBaseSelect):
    """Applies a preset from the selected folder."""

    def __init__(
        self, entry: GoulyConfigEntry, library: PresetLibrary, folder: GoulyFolderSelect
    ) -> None:
        super().__init__(entry, "preset")
        self._library = library
        self._folder = folder
        self._attr_current_option = None
        self._attr_options = library.names_in(folder.current_option or "")
        folder.add_listener(self._folder_changed)

    @callback
    def _folder_changed(self, folder: str) -> None:
        self._attr_options = self._library.names_in(folder)
        self._attr_current_option = None
        self.async_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        folder = self._folder.current_option or ""
        preset = self._library.find(folder, option)
        layout = self._connection.layout
        if preset is None:
            _LOGGER.warning("Preset %r not found in folder %r", option, folder)
            return
        if layout is None:
            _LOGGER.warning("Gouly controller hasn't reported its LED layout yet")
            return
        self._connection.send(self._library.frames(preset, layout))
        self._connection.selected_preset = (folder, option)
        self._attr_current_option = option
        self.async_write_ha_state()
