from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo, format_mac
from homeassistant.helpers.entity import Entity

from .client import HonKzwClient
from .const import DOMAIN


class HonKzwEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, client: HonKzwClient, entry: ConfigEntry) -> None:
        self._client = client
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, client.mac)},
            connections={(CONNECTION_NETWORK_MAC, format_mac(client.mac))},
            manufacturer="Haier",
            model="Air-to-air heat pump (hOn, KZW-W002 key)",
            name=entry.title,
        )

    @property
    def available(self) -> bool:
        return self._client.available and self._client.status is not None

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._client.add_listener(self.async_write_ha_state))
