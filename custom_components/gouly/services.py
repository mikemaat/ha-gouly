"""Services for applying presets and managing favourite and custom presets.

Favourites are stored in the config entry's options and published as the light's
favourite_presets attribute.
Presets are named "Folder / Preset", the same way they appear as effects.
Custom presets are scenes saved from the lights; see presets.py.
"""

from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_registry as er

from . import presets
from .const import CONF_FAVOURITES, DOMAIN

SERVICE_APPLY_PRESET = "apply_preset"
SERVICE_ADD_FAVOURITE = "add_favourite"
SERVICE_REMOVE_FAVOURITE = "remove_favourite"
SERVICE_SET_FAVOURITES = "set_favourites"
SERVICE_SAVE_CUSTOM_PRESET = "save_custom_preset"
SERVICE_DELETE_CUSTOM_PRESET = "delete_custom_preset"

ATTR_PRESET = "preset"
ATTR_PRESETS = "presets"
ATTR_NAME = "name"

PRESET_SCHEMA = vol.Schema(
    {vol.Required("entity_id"): cv.entity_ids, vol.Required(ATTR_PRESET): cv.string}
)
PRESETS_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_ids,
        vol.Required(ATTR_PRESETS): vol.All(cv.ensure_list, [cv.string]),
    }
)
SAVE_CUSTOM_SCHEMA = vol.Schema(
    {vol.Required("entity_id"): cv.entity_ids, vol.Required(ATTR_NAME): cv.string}
)
DELETE_CUSTOM_SCHEMA = vol.Schema({vol.Required(ATTR_NAME): cv.string})


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
    """Store favourites. The light republishes them; the entry is not reloaded for this."""
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_FAVOURITES: favourites}
    )


def _custom_name(name: str) -> str:
    """A custom preset's own name, whether given as 'Custom / Name' or just 'Name'."""
    folder, _, rest = name.strip().partition(" / ")
    name = (rest if folder == presets.CUSTOM_FOLDER and rest else name).strip()
    if not name:
        raise ServiceValidationError("Give the custom preset a name.")
    return name


async def async_save_custom_preset(hass: HomeAssistant, entry: ConfigEntry, name: str) -> str:
    """Save the scene the lights were last sent as a custom preset. Returns its full name."""
    name = _custom_name(name)
    connection = entry.runtime_data
    segments = connection.scene.segments
    if not segments:
        raise ServiceValidationError(
            "Home Assistant hasn't seen a scene sent to these lights yet. Load it from the Gouly "
            "app (or apply a preset) while Home Assistant is connected, then save it."
        )
    total = connection.layout.total if connection.layout else max(s.end for s in segments)
    zones = presets.zones_from_segments(segments)
    custom = await hass.async_add_executor_job(
        presets.save_custom, hass.config.config_dir, name, total, zones
    )
    _async_update_custom(hass, custom)
    return f"{presets.CUSTOM_FOLDER} / {name}"


async def async_delete_custom_preset(hass: HomeAssistant, name: str) -> None:
    """Delete a custom preset."""
    name = _custom_name(name)
    custom = await hass.async_add_executor_job(presets.delete_custom, hass.config.config_dir, name)
    if custom is None:
        raise ServiceValidationError(f"There's no custom preset called {name!r}.")
    _async_update_custom(hass, custom)


def _async_update_custom(hass: HomeAssistant, custom: list[dict]) -> None:
    """Show the new custom presets on every controller (they're shared between them)."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is not ConfigEntryState.LOADED:
            continue
        connection = entry.runtime_data
        if connection.presets is None:
            # No library was loaded, so there are no preset controls yet; setup adds them.
            hass.config_entries.async_schedule_reload(entry.entry_id)
            continue
        connection.presets.set_custom(custom)
        connection.refresh_entities()


def async_register(hass: HomeAssistant) -> None:
    """Register the services once."""
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

    async def save_custom_preset(call: ServiceCall) -> None:
        await async_save_custom_preset(hass, _entry_for(hass, call), call.data[ATTR_NAME])

    async def delete_custom_preset(call: ServiceCall) -> None:
        await async_delete_custom_preset(hass, call.data[ATTR_NAME])

    hass.services.async_register(DOMAIN, SERVICE_APPLY_PRESET, apply_preset, schema=PRESET_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_ADD_FAVOURITE, add_favourite, schema=PRESET_SCHEMA)
    hass.services.async_register(
        DOMAIN, SERVICE_REMOVE_FAVOURITE, remove_favourite, schema=PRESET_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SET_FAVOURITES, set_favourites, schema=PRESETS_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SAVE_CUSTOM_PRESET, save_custom_preset, schema=SAVE_CUSTOM_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_DELETE_CUSTOM_PRESET, delete_custom_preset, schema=DELETE_CUSTOM_SCHEMA
    )
