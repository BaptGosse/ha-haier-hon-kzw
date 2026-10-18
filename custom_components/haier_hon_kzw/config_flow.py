"""Config flow: manual (IP + MAC), DHCP discovery and IP reconfiguration."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo

from .client import async_probe
from .const import (
    CONF_INDOOR_FAN_POWER,
    CONF_OUTDOOR_UNIT,
    CONF_POWER_CALIBRATION,
    DEFAULT_INDOOR_FAN_POWER,
    DEFAULT_POWER_CALIBRATION,
    DOMAIN,
)
from .protocol import ProtocolError, normalize_mac


async def _probe_error(host: str, mac: str) -> str | None:
    try:
        await async_probe(host, mac)
    except (OSError, TimeoutError):
        return "cannot_connect"
    except ProtocolError:
        return "not_hon"
    return None


class HonKzwConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return HonKzwOptionsFlow()

    def __init__(self) -> None:
        self._discovered: dict[str, str] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                mac = normalize_mac(user_input[CONF_MAC])
            except ValueError:
                errors[CONF_MAC] = "invalid_mac"
            else:
                await self.async_set_unique_id(mac)
                self._abort_if_unique_id_configured(updates={CONF_HOST: user_input[CONF_HOST]})
                if (error := await _probe_error(user_input[CONF_HOST], mac)) is None:
                    return self.async_create_entry(
                        title=user_input[CONF_NAME],
                        data={CONF_HOST: user_input[CONF_HOST], CONF_MAC: mac},
                    )
                errors["base"] = error
        schema = vol.Schema(
            {
                vol.Required(CONF_NAME): str,
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_MAC): str,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input or {}),
            errors=errors,
        )

    async def async_step_dhcp(self, discovery_info: DhcpServiceInfo) -> ConfigFlowResult:
        mac = normalize_mac(discovery_info.macaddress)
        await self.async_set_unique_id(mac)
        # A known key that changed IP is updated (and reloaded) here
        self._abort_if_unique_id_configured(updates={CONF_HOST: discovery_info.ip})
        # Haier MAC prefixes are shared with other appliances: only offer real keys
        if await _probe_error(discovery_info.ip, mac) is not None:
            return self.async_abort(reason="not_hon")
        self._discovered = {CONF_HOST: discovery_info.ip, CONF_MAC: mac}
        self.context["title_placeholders"] = {"host": discovery_info.ip}
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title=user_input[CONF_NAME], data=self._discovered)
        return self.async_show_form(
            step_id="discovery_confirm",
            data_schema=vol.Schema({vol.Required(CONF_NAME): str}),
            description_placeholders={
                "host": self._discovered[CONF_HOST],
                "mac": format_mac(self._discovered[CONF_MAC]),
            },
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            if (error := await _probe_error(user_input[CONF_HOST], entry.data[CONF_MAC])) is None:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_HOST: user_input[CONF_HOST]}
                )
            errors["base"] = error
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema({vol.Required(CONF_HOST, default=entry.data[CONF_HOST]): str}),
            errors=errors,
        )


class HonKzwOptionsFlow(OptionsFlow):
    """Consumption estimate: shared outdoor unit, indoor fan power and calibration."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            user_input[CONF_OUTDOOR_UNIT] = user_input.get(CONF_OUTDOOR_UNIT, "").strip()
            return self.async_create_entry(data=user_input)
        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_OUTDOOR_UNIT,
                    description={"suggested_value": options.get(CONF_OUTDOOR_UNIT, "")},
                ): selector.TextSelector(),
                vol.Required(
                    CONF_INDOOR_FAN_POWER, default=options.get(CONF_INDOOR_FAN_POWER, DEFAULT_INDOOR_FAN_POWER)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=100, step=1, unit_of_measurement="W",
                                                  mode=selector.NumberSelectorMode.BOX)
                ),
                vol.Required(
                    CONF_POWER_CALIBRATION,
                    default=options.get(CONF_POWER_CALIBRATION, DEFAULT_POWER_CALIBRATION),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0.5, max=1.5, step=0.01, mode=selector.NumberSelectorMode.BOX)
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
