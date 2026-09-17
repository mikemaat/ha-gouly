"""Config flow for Gouly."""

from __future__ import annotations

import json
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from . import async_get_scan_networks
from .const import (
    CONF_DEVICE,
    CONF_DEVICE_ID,
    CONF_DEVICES_JSON,
    CONF_LOCAL_KEY,
    CONF_PROTOCOL_VERSION,
    DOMAIN,
)
from .discovery import discover, probe

DEFAULT_NAME = "Gouly Lights"

MANUAL_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_NAME): str,
        vol.Required(CONF_DEVICE_ID): str,
        vol.Required(CONF_LOCAL_KEY): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
        vol.Optional(CONF_HOST): str,
    }
)


class GoulyConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up a Gouly controller using its Tuya device ID and local key."""

    VERSION = 1

    def __init__(self) -> None:
        self._devices: list[dict[str, Any]] = []

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="user", menu_options=["paste", "manual"])

    async def async_step_paste(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Paste the gouly_devices.json produced by the gouly-keys tool."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                devices = _parse_devices_json(user_input[CONF_DEVICES_JSON])
            except ValueError:
                errors["base"] = "invalid_json"
            else:
                configured = self._async_current_ids()
                self._devices = [d for d in devices if d[CONF_DEVICE_ID] not in configured]
                if not self._devices:
                    return self.async_abort(reason="already_configured")
                if len(self._devices) == 1:
                    return await self._async_connect(self._devices[0])
                return await self.async_step_pick()

        return self.async_show_form(
            step_id="paste",
            data_schema=vol.Schema(
                {vol.Required(CONF_DEVICES_JSON): TextSelector(TextSelectorConfig(multiline=True))}
            ),
            errors=errors,
        )

    async def async_step_pick(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choose which controller to add when the file lists several."""
        if user_input is not None:
            device = next(d for d in self._devices if d[CONF_DEVICE_ID] == user_input[CONF_DEVICE])
            return await self._async_connect(device)

        options = [
            SelectOptionDict(value=d[CONF_DEVICE_ID], label=d.get(CONF_NAME) or d[CONF_DEVICE_ID])
            for d in self._devices
        ]
        return self.async_show_form(
            step_id="pick",
            data_schema=vol.Schema(
                {vol.Required(CONF_DEVICE): SelectSelector(SelectSelectorConfig(options=options))}
            ),
        )

    async def async_step_manual(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Enter the device ID and local key by hand."""
        errors: dict[str, str] = {}
        if user_input is not None:
            device = {
                CONF_NAME: user_input.get(CONF_NAME) or DEFAULT_NAME,
                CONF_DEVICE_ID: user_input[CONF_DEVICE_ID].strip(),
                CONF_LOCAL_KEY: user_input[CONF_LOCAL_KEY].strip(),
                CONF_HOST: (user_input.get(CONF_HOST) or "").strip() or None,
            }
            if len(device[CONF_LOCAL_KEY]) != 16:
                errors[CONF_LOCAL_KEY] = "invalid_local_key"
            else:
                return await self._async_connect(device, show_errors_on="manual")

        return self.async_show_form(
            step_id="manual",
            data_schema=self.add_suggested_values_to_schema(MANUAL_SCHEMA, user_input),
            errors=errors,
        )

    async def _async_connect(
        self, device: dict[str, Any], show_errors_on: str | None = None
    ) -> ConfigFlowResult:
        """Find/verify the controller on the network and create the entry."""
        device_id = device[CONF_DEVICE_ID]
        local_key = device[CONF_LOCAL_KEY]
        await self.async_set_unique_id(device_id)
        self._abort_if_unique_id_configured()

        found: tuple[str, float] | None = None
        if host := device.get(CONF_HOST):
            version = await self.hass.async_add_executor_job(probe, host, device_id, local_key)
            if version is not None:
                found = (host, version)
        if found is None:
            networks = await async_get_scan_networks(self.hass)
            found = await self.hass.async_add_executor_job(discover, device_id, local_key, networks)

        if found is None:
            if show_errors_on is None:
                return self.async_abort(reason="not_found")
            return self.async_show_form(
                step_id=show_errors_on,
                data_schema=self.add_suggested_values_to_schema(MANUAL_SCHEMA, device),
                errors={"base": "not_found"},
            )

        host, version = found
        return self.async_create_entry(
            title=device.get(CONF_NAME) or DEFAULT_NAME,
            data={
                CONF_HOST: host,
                CONF_DEVICE_ID: device_id,
                CONF_LOCAL_KEY: local_key,
                CONF_PROTOCOL_VERSION: version,
            },
        )


def _parse_devices_json(text: str) -> list[dict[str, Any]]:
    """Accept the gouly-keys output file (a list) or a single device object."""
    data = json.loads(text)
    if isinstance(data, dict):
        data = data.get("devices", [data])
    if not isinstance(data, list):
        raise ValueError("expected a list of devices")
    devices = []
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("expected device objects")
        device_id = item.get("device_id") or item.get("devId")
        local_key = item.get("local_key") or item.get("localKey")
        if not device_id or not local_key:
            raise ValueError("device is missing device_id or local_key")
        devices.append(
            {
                CONF_NAME: item.get("name"),
                CONF_DEVICE_ID: device_id,
                CONF_LOCAL_KEY: local_key,
                CONF_HOST: item.get("host") or item.get("ip"),
            }
        )
    return devices
