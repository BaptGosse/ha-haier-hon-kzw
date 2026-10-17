"""Filter, cleaning and compressor states."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant

from . import HonKzwConfigEntry
from .client import HonKzwClient
from .entity import HonKzwEntity


@dataclass(frozen=True, kw_only=True)
class HonKzwBinaryDescription(BinarySensorEntityDescription):
    value: Callable[[HonKzwClient], bool | None]
    big_data: bool = False


BINARY_SENSORS = (
    HonKzwBinaryDescription(
        key="filter",
        translation_key="filter",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value=lambda c: c.status.change_filter if c.status else None,
    ),
    HonKzwBinaryDescription(
        key="cleaning",
        translation_key="cleaning",
        device_class=BinarySensorDeviceClass.RUNNING,
        value=lambda c: (c.status.self_cleaning or c.status.steri_cleaning) if c.status else None,
    ),
    HonKzwBinaryDescription(
        key="compressor",
        translation_key="compressor",
        device_class=BinarySensorDeviceClass.RUNNING,
        value=lambda c: c.big.compressor_frequency > 0 if c.big else None,
        big_data=True,
    ),
)


async def async_setup_entry(hass: HomeAssistant, entry: HonKzwConfigEntry, async_add_entities) -> None:
    async_add_entities(HonKzwBinarySensor(entry.runtime_data, entry, d) for d in BINARY_SENSORS)


class HonKzwBinarySensor(HonKzwEntity, BinarySensorEntity):
    entity_description: HonKzwBinaryDescription

    def __init__(self, client, entry, description: HonKzwBinaryDescription) -> None:
        super().__init__(client, entry)
        self.entity_description = description
        self._attr_unique_id = f"{client.mac}_{description.key}"

    @property
    def available(self) -> bool:
        if self.entity_description.big_data and self._client.big is None:
            return False
        return super().available

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value(self._client)
