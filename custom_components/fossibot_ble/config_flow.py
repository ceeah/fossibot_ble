"""Config flow for the FossiBOT custom integration."""

from __future__ import annotations

import logging
from typing import Optional

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.core import callback

from .const import CONF_DEVICE_NAME, CONF_MAC, DOMAIN

LOGGER = logging.getLogger(__name__)
DEVICE_PREFIX = "POWER-"

class FossibotConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the configuration flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovery_mac: Optional[str] = None
        self._discovery_name: Optional[str] = None

    async def async_step_user(self, user_input: Optional[dict] = None):
        """Abort manual setup; bluetooth discovery handles onboarding."""
        return self.async_abort(reason="bluetooth_only")

    async def async_step_bluetooth(self, discovery_info: BluetoothServiceInfoBleak):
        """Handle bluetooth discovery from the HA bluetooth integration."""
        mac = discovery_info.address
        await self.async_set_unique_id(mac)
        self._abort_if_unique_id_configured()
        self._discovery_mac = mac
        self._discovery_name = discovery_info.name or mac
        self.context["title_placeholders"] = {"name": self._discovery_name}
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(self, user_input: Optional[dict] = None):
        """Confirm adding a device discovered over bluetooth."""
        if user_input is None:
            return self.async_show_form(
                step_id="discovery_confirm",
                description_placeholders={"name": self._discovery_name or self._discovery_mac or ""},
                data_schema=vol.Schema({}),
            )

        if not self._discovery_mac:
            return self.async_abort(reason="unknown")

        data = {CONF_MAC: self._discovery_mac}
        if self._discovery_name:
            data[CONF_DEVICE_NAME] = self._discovery_name
        return self.async_create_entry(title=self._discovery_name or self._discovery_mac, data=data)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return FossibotOptionsFlowHandler(config_entry)


class FossibotOptionsFlowHandler(config_entries.OptionsFlow):
    """Placeholder options flow (no configurable options yet)."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self._entry = entry

    async def async_step_init(self, user_input: Optional[dict] = None):
        """Present empty options to comply with HA UI expectations."""
        if user_input is not None:
            return self.async_create_entry(title="", data={})
        return self.async_show_form(step_id="init", data_schema=vol.Schema({}))
