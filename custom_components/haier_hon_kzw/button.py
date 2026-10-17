"""Cleaning cycles of the indoor unit."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from . import HonKzwConfigEntry
from .client import CommandError
from .const import DOMAIN
from .entity import HonKzwEntity


async def async_setup_entry(hass: HomeAssistant, entry: HonKzwConfigEntry, async_add_entities) -> None:
    client = entry.runtime_data
    async_add_entities([HonKzwCleaning(client, entry, steri=False), HonKzwCleaning(client, entry, steri=True)])


class HonKzwCleaning(HonKzwEntity, ButtonEntity):
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, client, entry, *, steri: bool) -> None:
        super().__init__(client, entry)
        self._steri = steri
        self._attr_translation_key = "steri_cleaning" if steri else "self_cleaning"
        self._attr_unique_id = f"{client.mac}_{self._attr_translation_key}"

    async def async_press(self) -> None:
        try:
            await self._client.async_start_cleaning(steri=self._steri)
        except CommandError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err
