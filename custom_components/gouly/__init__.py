"""The Gouly integration: local control of Gouly permanent/holiday lighting controllers."""

from __future__ import annotations

import ipaddress

from homeassistant.components import network
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant

from .connection import GoulyConnection
from .const import CONF_DEVICE_ID, CONF_LOCAL_KEY, CONF_PROTOCOL_VERSION, DEFAULT_PROTOCOL_VERSION
from .discovery import discover, networks_for_addresses

PLATFORMS: list[Platform] = [Platform.LIGHT]

type GoulyConfigEntry = ConfigEntry[GoulyConnection]


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
    entry.runtime_data = connection
    connection.start()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GoulyConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await hass.async_add_executor_job(entry.runtime_data.stop)
    return unloaded
