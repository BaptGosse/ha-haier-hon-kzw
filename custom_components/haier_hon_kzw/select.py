"""Louver position selects (vertical and horizontal), "swing" restarts the sweep."""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from . import HonKzwConfigEntry
from .client import CommandError
from .const import DOMAIN
from .entity import HonKzwEntity
from .protocol import (
    SWING_H_AUTO,
    SWING_H_CENTER,
    SWING_H_LEFT,
    SWING_H_MAX_LEFT,
    SWING_H_MAX_RIGHT,
    SWING_H_RIGHT,
    SWING_V_AUTO,
    SWING_V_AUTO_SPECIAL,
    SWING_V_CENTER,
    SWING_V_DOWN,
    SWING_V_HEALTH_DOWN,
    SWING_V_HEALTH_UP,
    SWING_V_MAX_DOWN,
    SWING_V_MAX_UP,
    SWING_V_UP,
)

SWING = "swing"


@dataclass(frozen=True, kw_only=True)
class LouverDescription(SelectEntityDescription):
    positions: dict[str, int]  # option -> raw value, in display order
    vertical: bool


LOUVERS = (
    LouverDescription(
        key="vertical_position",
        translation_key="vertical_position",
        vertical=True,
        positions={
            "max_up": SWING_V_MAX_UP,
            "up": SWING_V_UP,
            "center": SWING_V_CENTER,
            "down": SWING_V_DOWN,
            "max_down": SWING_V_MAX_DOWN,
            "health_up": SWING_V_HEALTH_UP,
            "health_down": SWING_V_HEALTH_DOWN,
            SWING: SWING_V_AUTO,
        },
    ),
    LouverDescription(
        key="horizontal_position",
        translation_key="horizontal_position",
        vertical=False,
        positions={
            "max_left": SWING_H_MAX_LEFT,
            "left": SWING_H_LEFT,
            "center": SWING_H_CENTER,
            "right": SWING_H_RIGHT,
            "max_right": SWING_H_MAX_RIGHT,
            SWING: SWING_H_AUTO,
        },
    ),
)


async def async_setup_entry(hass: HomeAssistant, entry: HonKzwConfigEntry, async_add_entities) -> None:
    async_add_entities(HonKzwLouver(entry.runtime_data, entry, description) for description in LOUVERS)


class HonKzwLouver(HonKzwEntity, SelectEntity):
    entity_description: LouverDescription

    def __init__(self, client, entry, description: LouverDescription) -> None:
        super().__init__(client, entry)
        self.entity_description = description
        self._attr_unique_id = f"{client.mac}_{description.key}"
        self._attr_options = list(description.positions)
        self._by_value = {value: option for option, value in description.positions.items()}

    @property
    def current_option(self) -> str | None:
        status = self._client.status
        if status is None:
            return None
        if self.entity_description.vertical:
            if status.vertical_swing in (SWING_V_AUTO, SWING_V_AUTO_SPECIAL):
                return SWING
            return self._by_value.get(status.vertical_swing)
        return self._by_value.get(status.horizontal_swing)

    async def async_select_option(self, option: str) -> None:
        axis = "vertical" if self.entity_description.vertical else "horizontal"
        if option == SWING:
            changes = {f"{axis}_swing": True}
        else:
            changes = {f"{axis}_position": self.entity_description.positions[option]}
        try:
            await self._client.async_control(**changes)
        except CommandError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err
