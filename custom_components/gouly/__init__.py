"""The Gouly integration: local control of Gouly permanent/holiday lighting controllers."""

from __future__ import annotations

import ipaddress

from homeassistant.components import network
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant

from .connection import GoulyConnection
from .const import (
    CONF_DEVICE_ID,
    CONF_FAVOURITES,
    CONF_LOCAL_KEY,
    CONF_PROTOCOL_VERSION,
    DEFAULT_PROTOCOL_VERSION,
)
from .discovery import discover, networks_for_addresses
from .presets import load as load_presets
from .services import async_register as async_register_services

PLATFORMS: list[Platform] = [Platform.BUTTON, Platform.LIGHT, Platform.NUMBER, Platform.SELECT]

type GoulyConfigEntry = ConfigEntry[GoulyConnection]

# The options as they were when the entry was last set up, so an update can be told apart
# from the favourites simply having been restarred.
_last_options: dict[str, dict] = {}


async def async_get_scan_networks(hass: HomeAssistant) -> list[ipaddress.IPv4Network]:
    """Networks to scan for controllers, based on Home Assistant's enabled adapters."""
    addresses = [
        ipv4["address"]
        for adapter in await network.async_get_adapters(hass)
        if adapter["enabled"]
        for ipv4 in adapter["ipv4"]
    ]
    return networks_for_addresses(addresses)


async def async_setup_entry(hass: HomeAssistant, entry: GoulyConfigEntry) -> bool:
    """Set up a Gouly controller from a config entry."""
    device_id = entry.data[CONF_DEVICE_ID]
    local_key = entry.data[CONF_LOCAL_KEY]
    networks = await async_get_scan_networks(hass)

    def rediscover() -> str | None:
        """Runs in the connection thread when the controller stops answering."""
        found = discover(device_id, local_key, networks)
        if found is None:
            return None
        host, _version = found
        if host != entry.data[CONF_HOST]:
            hass.loop.call_soon_threadsafe(
                lambda: hass.config_entries.async_update_entry(
                    entry, data={**entry.data, CONF_HOST: host}
                )
            )
        return host

    connection = GoulyConnection(
        host=entry.data[CONF_HOST],
        device_id=device_id,
        local_key=local_key,
        version=entry.data.get(CONF_PROTOCOL_VERSION, DEFAULT_PROTOCOL_VERSION),
        rediscover=rediscover,
    )
    connection.presets = await hass.async_add_executor_job(load_presets, hass.config.config_dir)
    entry.runtime_data = connection
    connection.start()

    async_register_services(hass)
    _last_options[entry.entry_id] = dict(entry.options)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_options_updated(hass: HomeAssistant, entry: GoulyConfigEntry) -> None:
    """Reload when the options changed in a way setup has to act on.

    Starring a preset only changes the favourites, which the light reads straight from the
    options every time it writes its state, so having it write once is enough. Reloading for
    that would drop the connection and take every entity away and back again - which looks
    like the dialog reloading, with the selects briefly holding no value.
    """
    previous = _last_options.get(entry.entry_id)
    current = dict(entry.options)
    _last_options[entry.entry_id] = current

    if previous is not None and _only_favourites_changed(previous, current):
        entry.runtime_data.refresh_entities()
        return

    await hass.config_entries.async_reload(entry.entry_id)


def _only_favourites_changed(previous: dict, current: dict) -> bool:
    """True when the favourites moved and nothing else did.

    Unchanged options still reload: uploading a preset library leaves the options alone, and
    the reload is how the new library gets picked up.
    """
    def rest(options: dict) -> dict:
        return {key: value for key, value in options.items() if key != CONF_FAVOURITES}

    return (
        previous.get(CONF_FAVOURITES) != current.get(CONF_FAVOURITES)
        and rest(previous) == rest(current)
    )


async def async_unload_entry(hass: HomeAssistant, entry: GoulyConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await hass.async_add_executor_job(entry.runtime_data.stop)
        _last_options.pop(entry.entry_id, None)
    return unloaded
