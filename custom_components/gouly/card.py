"""Serve the Gouly card that ships with the integration, and add it to the dashboard resources."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

URL_BASE = f"/{DOMAIN}"
CARD_FILE = "gouly-card.js"
CARD_URL = f"{URL_BASE}/{CARD_FILE}"
WWW_DIR = Path(__file__).parent / "www"


_SERVED = f"{DOMAIN}_card_served"


async def async_register_card(hass: HomeAssistant) -> None:
    """Serve the card from the integration's own folder and load it on every dashboard.

    Safe to call again: the card is served once, and the resource is only added if it's missing.
    """
    if not hass.data.get(_SERVED):
        await hass.http.async_register_static_paths(
            [StaticPathConfig(URL_BASE, str(WWW_DIR), cache_headers=False)]
        )
        hass.data[_SERVED] = True

    # The version in the query makes browsers fetch the card again after an update.
    version = (await async_get_integration(hass, DOMAIN)).version
    url = f"{CARD_URL}?v={version}"

    resources = _storage_resources(hass)
    if resources is None:
        # Dashboards in YAML mode keep their resources in configuration.yaml, which can't be
        # changed from here, so the card is loaded on every page instead.
        if not hass.data.get(f"{_SERVED}_js"):
            add_extra_js_url(hass, url)
            hass.data[f"{_SERVED}_js"] = True
        return

    await resources.async_get_info()  # loads the collection from storage
    ours = [item for item in resources.async_items() if _is_ours(item["url"])]
    if not ours:
        await resources.async_create_item({"res_type": "module", "url": url})
        _LOGGER.debug("Added %s to the dashboard resources", url)
        return
    if ours[0]["url"] != url:
        await resources.async_update_item(ours[0]["id"], {"res_type": "module", "url": url})
    for duplicate in ours[1:]:
        await resources.async_delete_item(duplicate["id"])


async def async_unregister_card(hass: HomeAssistant) -> None:
    """Take the card back out of the dashboard resources, once the last controller is removed."""
    if (resources := _storage_resources(hass)) is None:
        return
    await resources.async_get_info()
    for item in resources.async_items():
        if _is_ours(item["url"]):
            await resources.async_delete_item(item["id"])


def _storage_resources(hass: HomeAssistant):
    """The dashboard resource collection when it can be edited (storage mode), else None."""
    lovelace = hass.data.get("lovelace")
    if lovelace is None:
        return None
    # Renamed from `mode` to `resource_mode` in later Home Assistant versions.
    mode = getattr(lovelace, "resource_mode", None) or getattr(lovelace, "mode", None)
    if mode != "storage":
        return None
    return lovelace.resources


def _is_ours(url: str) -> bool:
    return url.split("?", 1)[0] == CARD_URL
