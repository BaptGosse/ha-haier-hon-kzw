"""Display (screen light) and command beeper switches."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_OFF, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.restore_state import RestoreEntity

from . import HonKzwConfigEntry
from .client import CommandError
from .const import DOMAIN
from .entity import HonKzwEntity


async def async_setup_entry(hass: HomeAssistant, entry: HonKzwConfigEntry, async_add_entities) -> None:
    client = entry.runtime_data
    async_add_entities([HonKzwDisplay(client, entry), HonKzwBeeper(client, entry)])


class HonKzwDisplay(HonKzwEntity, SwitchEntity):
    _attr_translation_key = "display"

    def __init__(self, client, entry) -> None:
        super().__init__(client, entry)
        self._attr_unique_id = f"{client.mac}_display"

    @property
    def is_on(self) -> bool | None:
        status = self._client.status
        return status.display if status else None

    async def _set(self, on: bool) -> None:
        try:
            await self._client.async_control(display=on)
        except CommandError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)


class HonKzwBeeper(HonKzwEntity, SwitchEntity, RestoreEntity):
    """Whether commands sent by Home Assistant make the unit beep (kept by HA)."""

    _attr_translation_key = "beeper"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, client, entry) -> None:
        super().__init__(client, entry)
        self._attr_unique_id = f"{client.mac}_beeper"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            self._client.beeper = last.state != STATE_OFF

    @property
    def is_on(self) -> bool:
        return self._client.beeper

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._client.beeper = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._client.beeper = False
        self.async_write_ha_state()
