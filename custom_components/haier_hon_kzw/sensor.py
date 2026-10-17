from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback

from . import HonKzwConfigEntry
from .client import HonKzwClient
from .entity import HonKzwEntity

MAX_INTEGRATION_GAP = 300  # s; longer gaps (outage, restart) are not integrated


@dataclass(frozen=True, kw_only=True)
class HonKzwSensorDescription(SensorEntityDescription):
    value: Callable[[HonKzwClient], float | int | None]
    big_data: bool = False
    needs_power: bool = False  # unavailable when the unit does not report its power


def _status(attr: str) -> Callable[[HonKzwClient], float | int | None]:
    return lambda c: getattr(c.status, attr) if c.status else None


def _big(attr: str) -> Callable[[HonKzwClient], float | int | None]:
    return lambda c: getattr(c.big, attr) if c.big else None


def _temperature(key: str, value, *, diagnostic: bool = False) -> HonKzwSensorDescription:
    return HonKzwSensorDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.DIAGNOSTIC if diagnostic else None,
        value=value,
        big_data=diagnostic,
    )


SENSORS = (
    _temperature("room_temperature", _status("room_temperature")),
    # raw 0 (-64 °C) means "no reading" (ESPHome ignores it too)
    _temperature(
        "outdoor_temperature",
        lambda c: c.status.outdoor_temperature if c.status and c.status.outdoor_temperature > -64 else None,
    ),
    HonKzwSensorDescription(
        key="power",
        translation_key="power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        value=_big("power"),
        big_data=True,
        needs_power=True,
    ),
    HonKzwSensorDescription(
        key="compressor_frequency",
        translation_key="compressor_frequency",
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=_big("compressor_frequency"),
        big_data=True,
    ),
    HonKzwSensorDescription(
        key="compressor_current",
        translation_key="compressor_current",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=_big("compressor_current"),
        big_data=True,
    ),
    _temperature("indoor_coil_temperature", _big("indoor_coil_temperature"), diagnostic=True),
    _temperature("outdoor_coil_temperature", _big("outdoor_coil_temperature"), diagnostic=True),
    # big data byte 3: called "outdoor out air" by ESPHome, but on the units tested it rises above the
    # indoor coil while heating and stays hot after the compressor stops: compressor discharge temperature
    _temperature("discharge_temperature", _big("outdoor_out_air_temperature"), diagnostic=True),
    _temperature("outdoor_defrost_temperature", _big("outdoor_defrost_temperature"), diagnostic=True),
    HonKzwSensorDescription(
        key="expansion_valve",
        translation_key="expansion_valve",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=_big("expansion_valve"),
        big_data=True,
    ),
    HonKzwSensorDescription(
        key="error_code",
        translation_key="error_code",
        entity_category=EntityCategory.DIAGNOSTIC,
        value=_status("error"),
    ),
)


async def async_setup_entry(hass: HomeAssistant, entry: HonKzwConfigEntry, async_add_entities) -> None:
    client = entry.runtime_data
    entities: list[SensorEntity] = [HonKzwSensor(client, entry, d) for d in SENSORS]
    entities.append(HonKzwEnergySensor(client, entry))
    async_add_entities(entities)


class HonKzwSensor(HonKzwEntity, SensorEntity):
    entity_description: HonKzwSensorDescription

    def __init__(self, client, entry, description: HonKzwSensorDescription) -> None:
        super().__init__(client, entry)
        self.entity_description = description
        self._attr_unique_id = f"{client.mac}_{description.key}"

    @property
    def available(self) -> bool:
        if self.entity_description.big_data and self._client.big is None:
            return False
        if self.entity_description.needs_power and self._client.power_reported is False:
            return False
        return super().available

    @property
    def native_value(self) -> float | int | None:
        return self.entity_description.value(self._client)


class HonKzwEnergySensor(HonKzwEntity, RestoreSensor):
    """Energy used by the unit, integrated from the reported power (trapezoidal rule)."""

    _attr_translation_key = "energy"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 2

    def __init__(self, client, entry) -> None:
        super().__init__(client, entry)
        self._attr_unique_id = f"{client.mac}_energy"
        self._energy = 0.0
        self._last: tuple[float, int] | None = None  # (monotonic time, watts)

    async def async_added_to_hass(self) -> None:
        if (last := await self.async_get_last_sensor_data()) is not None and last.native_value is not None:
            self._energy = float(last.native_value)
        self.async_on_remove(self._client.add_listener(self._on_update))

    @callback
    def _on_update(self) -> None:
        big = self._client.big
        now = time.monotonic()
        if not self._client.available or big is None:
            self._last = None
        else:
            if self._last is not None and big is not self._last_big:
                elapsed = now - self._last[0]
                if 0 < elapsed <= MAX_INTEGRATION_GAP:
                    self._energy += (self._last[1] + big.power) / 2 * elapsed / 3_600_000
            if self._last is None or big is not self._last_big:
                self._last = (now, big.power)
        self._last_big = big
        self.async_write_ha_state()

    _last_big = None

    @property
    def available(self) -> bool:
        if self._client.power_reported is False:
            return False
        return self._client.big is not None and super().available

    @property
    def native_value(self) -> float:
        return round(self._energy, 4)
