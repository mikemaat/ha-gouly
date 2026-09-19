"""Services for managing favourite presets.

Favourites are stored in the config entry's options and shown in the light's effect list.
Presets are named "Folder / Preset", the same way they appear as effects.
"""

from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_registry as er

from .const import CONF_FAVOURITES, DOMAIN

SERVICE_APPLY_PRESET = "apply_preset"
SERVICE_ADD_FAVOURITE = "add_favourite"
SERVICE_REMOVE_FAVOURITE = "remove_favourite"
SERVICE_SET_FAVOURITES = "set_favourites"

ATTR_PRESET = "preset"
ATTR_PRESETS = "presets"

PRESET_SCHEMA = vol.Schema(
    {vol.Required("entity_id"): cv.entity_ids, vol.Required(ATTR_PRESET): cv.string}
)
PRESETS_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_ids,
        vol.Required(ATTR_PRESETS): vol.All(cv.ensure_list, [cv.string]),
    }
)


def _split(preset: str) -> list[str]:
    """'Folder / Preset' -> ['Folder', 'Preset']."""
    folder, _, name = preset.partition(" / ")
    if not name:
        raise ServiceValidationError(
            f"{preset!r} isn't a preset name. Use 'Folder / Preset', "
            "for example 'Christmas 1 / Christmas-static'."
        )
    return [folder, name]


def _entry_for(hass: HomeAssistant, call: ServiceCall) -> ConfigEntry:
    """The Gouly config entry behind the targeted entity."""
    registry = er.async_get(hass)
    for entity_id in call.data["entity_id"]:
        entity = registry.async_get(entity_id)
        entry = (
            hass.config_entries.async_get_entry(entity.config_entry_id)
            if entity and entity.config_entry_id
            else None
        )
        if entry and entry.domain == DOMAIN:
            return entry
    raise ServiceValidationError("Target a Gouly entity, for example its light.")


def _preset_for(hass: HomeAssistant, entry: ConfigEntry, name: str):
    """Look a preset up in the library, by its 'Folder / Preset' name."""
    connection = entry.runtime_data
    library = getattr(connection, "presets", None)
    if library is None:
        raise ServiceValidationError(
            "No preset library is installed. Add gouly_presets.json in the integration's "
            "Configure screen."
        )
    folder, preset_name = _split(name)
    preset = library.find(folder, preset_name)
    if preset is None:
        raise ServiceValidationError(f"No preset called {name!r} in the library.")
    return library, preset, connection


def _save(hass: HomeAssistant, entry: ConfigEntry, favourites: list[list[str]]) -> None:
    """Store favourites; the update listener reloads the entry and rebuilds the effect list."""
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_FAVOURITES: favourites}
    )


def async_register(hass: HomeAssistant) -> None:
    """Register the favourite services once."""
    if hass.services.has_service(DOMAIN, SERVICE_APPLY_PRESET):
        return

    async def apply_preset(call: ServiceCall) -> None:
        entry = _entry_for(hass, call)
        library, preset, connection = _preset_for(hass, entry, call.data[ATTR_PRESET])
        if connection.layout is None:
            raise ServiceValidationError(
                "The controller hasn't reported how many LEDs it drives yet; try again shortly."
            )
        connection.send(library.frames(preset, connection.layout))

    async def add_favourite(call: ServiceCall) -> None:
        entry = _entry_for(hass, call)
        favourite = _split(call.data[ATTR_PRESET])
        favourites = [list(f) for f in entry.options.get(CONF_FAVOURITES, [])]
        if favourite not in favourites:
            favourites.append(favourite)
            _save(hass, entry, favourites)

    async def remove_favourite(call: ServiceCall) -> None:
        entry = _entry_for(hass, call)
        favourite = _split(call.data[ATTR_PRESET])
        favourites = [
            list(f) for f in entry.options.get(CONF_FAVOURITES, []) if list(f) != favourite
        ]
        _save(hass, entry, favourites)

    async def set_favourites(call: ServiceCall) -> None:
        """Replace the whole list, which is also how the card reorders it."""
        entry = _entry_for(hass, call)
        _save(hass, entry, [_split(preset) for preset in call.data[ATTR_PRESETS]])

    hass.services.async_register(DOMAIN, SERVICE_APPLY_PRESET, apply_preset, schema=PRESET_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_ADD_FAVOURITE, add_favourite, schema=PRESET_SCHEMA)
    hass.services.async_register(
        DOMAIN, SERVICE_REMOVE_FAVOURITE, remove_favourite, schema=PRESET_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SET_FAVOURITES, set_favourites, schema=PRESETS_SCHEMA
    )
