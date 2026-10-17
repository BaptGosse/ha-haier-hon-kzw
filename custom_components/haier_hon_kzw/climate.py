from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.climate import (
    ATTR_FAN_MODE,
    ATTR_HVAC_MODE,
    ATTR_PRESET_MODE,
    FAN_AUTO,
    FAN_HIGH,
    FAN_LOW,
    FAN_MEDIUM,
    PRESET_AWAY,
    PRESET_NONE,
    PRESET_SLEEP,
    SWING_BOTH,
    SWING_HORIZONTAL,
    SWING_OFF,
    SWING_VERTICAL,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, PRECISION_HALVES, PRECISION_WHOLE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_platform

from . import HonKzwConfigEntry
from .client import CommandError
from .const import DOMAIN
from .entity import HonKzwEntity
from .protocol import (
    FAN_AUTO as HON_FAN_AUTO,
    FAN_HIGH as HON_FAN_HIGH,
    FAN_LOW as HON_FAN_LOW,
    FAN_MID as HON_FAN_MID,
    MAX_TEMP,
    MIN_TEMP,
    MODE_AUTO,
    MODE_COOL,
    MODE_DRY,
    MODE_ENERGY_SAVING,
    MODE_FAN,
    MODE_HEALTHY_DRY,
    MODE_HEAT,
)
from .select import LOUVERS, SWING

HVAC_TO_HON = {
    HVACMode.HEAT_COOL: MODE_AUTO,
    HVACMode.COOL: MODE_COOL,
    HVACMode.HEAT: MODE_HEAT,
    HVACMode.DRY: MODE_DRY,
    HVACMode.FAN_ONLY: MODE_FAN,
}
HON_TO_HVAC = {
    MODE_AUTO: HVACMode.HEAT_COOL,
    MODE_COOL: HVACMode.COOL,
    MODE_DRY: HVACMode.DRY,
    MODE_HEALTHY_DRY: HVACMode.DRY,
    MODE_HEAT: HVACMode.HEAT,
    MODE_ENERGY_SAVING: HVACMode.COOL,
    MODE_FAN: HVACMode.FAN_ONLY,
}
FAN_TO_HON = {FAN_AUTO: HON_FAN_AUTO, FAN_LOW: HON_FAN_LOW, FAN_MEDIUM: HON_FAN_MID, FAN_HIGH: HON_FAN_HIGH}
HON_TO_FAN = {v: k for k, v in FAN_TO_HON.items()}
# The remote's "auto" variants: quiet (silent) and auto with an up arrow (turbo)
FAN_QUIET = "quiet"
FAN_TURBO = "turbo"
FAN_MODES = [FAN_QUIET, FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH, FAN_TURBO]
LOUVER_POSITIONS = {louver.key: louver.positions for louver in LOUVERS}  # vertical_position, horizontal_position

SERVICE_APPLY_SETTINGS = "apply_settings"
ATTR_DISPLAY = "display"
ATTR_HEALTH = "health"
# Every setting is optional; an empty value (None, as sent by schedulers for unset fields) means unchanged
APPLY_SETTINGS_SCHEMA = {
    vol.Optional(ATTR_HVAC_MODE): vol.Any(None, vol.In(["off", "heat", "cool", "heat_cool", "dry", "fan_only"])),
    vol.Optional(ATTR_TEMPERATURE): vol.Any(
        None, vol.All(vol.Coerce(float), vol.Range(min=MIN_TEMP, max=MAX_TEMP))
    ),
    vol.Optional(ATTR_FAN_MODE): vol.Any(None, vol.In(FAN_MODES)),
    vol.Optional(ATTR_PRESET_MODE): vol.Any(None, vol.In([PRESET_NONE, PRESET_SLEEP, PRESET_AWAY])),
    **{vol.Optional(key): vol.Any(None, vol.In(list(positions))) for key, positions in LOUVER_POSITIONS.items()},
    vol.Optional(ATTR_DISPLAY): vol.Any(None, cv.boolean),
    vol.Optional(ATTR_HEALTH): vol.Any(None, cv.boolean),
}


def _fan_changes(fan_mode: str) -> dict[str, Any]:
    if fan_mode == FAN_QUIET:
        return {"fan": HON_FAN_AUTO, "quiet": True, "turbo": False}
    if fan_mode == FAN_TURBO:
        return {"fan": HON_FAN_AUTO, "quiet": False, "turbo": True}
    return {"fan": FAN_TO_HON[fan_mode], "quiet": False, "turbo": False}


async def async_setup_entry(hass: HomeAssistant, entry: HonKzwConfigEntry, async_add_entities) -> None:
    async_add_entities([HonKzwClimate(entry.runtime_data, entry)])
    entity_platform.async_get_current_platform().async_register_entity_service(
        SERVICE_APPLY_SETTINGS, APPLY_SETTINGS_SCHEMA, "async_apply_settings"
    )


class HonKzwClimate(HonKzwEntity, ClimateEntity):
    _attr_name = None
    _attr_translation_key = "air_conditioner"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_precision = PRECISION_HALVES
    _attr_target_temperature_step = PRECISION_WHOLE
    _attr_min_temp = MIN_TEMP
    _attr_max_temp = MAX_TEMP
    _attr_hvac_modes = [
        HVACMode.OFF,
        HVACMode.HEAT,
        HVACMode.COOL,
        HVACMode.HEAT_COOL,
        HVACMode.DRY,
        HVACMode.FAN_ONLY,
    ]
    _attr_swing_modes = [SWING_OFF, SWING_VERTICAL, SWING_HORIZONTAL, SWING_BOTH]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.FAN_MODE
        | ClimateEntityFeature.SWING_MODE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(self, client, entry) -> None:
        super().__init__(client, entry)
        self._attr_unique_id = client.mac

    @property
    def preset_modes(self) -> list[str]:
        # 10 °C frost protection only exists in heat mode
        if self._client.status and self._client.status.mode == MODE_HEAT:
            return [PRESET_NONE, PRESET_SLEEP, PRESET_AWAY]
        return [PRESET_NONE, PRESET_SLEEP]

    @property
    def preset_mode(self) -> str | None:
        status = self._client.status
        if status is None:
            return None
        if status.ten_degree:
            return PRESET_AWAY
        if status.sleep:
            return PRESET_SLEEP
        return PRESET_NONE

    @property
    def hvac_mode(self) -> HVACMode | None:
        status = self._client.status
        if status is None:
            return None
        if not status.power:
            return HVACMode.OFF
        return HON_TO_HVAC.get(status.mode, HVACMode.HEAT_COOL)

    @property
    def hvac_action(self) -> HVACAction | None:
        status, big = self._client.status, self._client.big
        if status is None or big is None:
            return None  # unit without big data: no reliable action
        if not status.power:
            return HVACAction.OFF
        if status.mode == MODE_FAN:
            return HVACAction.FAN
        if big.compressor_frequency == 0:
            return HVACAction.IDLE
        if status.mode in (MODE_DRY, MODE_HEALTHY_DRY):
            return HVACAction.DRYING
        if status.mode == MODE_HEAT:
            return HVACAction.HEATING
        if status.mode == MODE_AUTO:
            # the 4-way valve reverses the cycle when heating
            return HVACAction.HEATING if big.four_way_valve == 1 else HVACAction.COOLING
        return HVACAction.COOLING

    @property
    def current_temperature(self) -> float | None:
        status = self._client.status
        return status.room_temperature if status else None

    @property
    def target_temperature(self) -> float | None:
        status = self._client.status
        return status.target_temperature if status else None

    @property
    def fan_modes(self) -> list[str]:
        if self._client.status and self._client.status.mode == MODE_FAN:
            # no auto, quiet or turbo in fan-only mode
            return [FAN_LOW, FAN_MEDIUM, FAN_HIGH]
        return FAN_MODES

    @property
    def fan_mode(self) -> str | None:
        status = self._client.status
        if status is None:
            return None
        if status.fast:
            return FAN_TURBO
        if status.quiet:
            return FAN_QUIET
        return HON_TO_FAN.get(status.fan)

    @property
    def swing_mode(self) -> str | None:
        status = self._client.status
        if status is None:
            return None
        if status.vertical_swing_on and status.horizontal_swing_on:
            return SWING_BOTH
        if status.vertical_swing_on:
            return SWING_VERTICAL
        if status.horizontal_swing_on:
            return SWING_HORIZONTAL
        return SWING_OFF

    async def _run(self, coro) -> None:
        try:
            await coro
        except CommandError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err

    async def async_turn_on(self) -> None:
        await self._run(self._client.async_set_power(True))

    async def async_turn_off(self) -> None:
        await self._run(self._client.async_set_power(False))

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self.async_turn_off()
            return
        await self._run(self._client.async_control(power=True, mode=HVAC_TO_HON[hvac_mode]))

    async def async_set_temperature(self, **kwargs: Any) -> None:
        changes: dict[str, Any] = {}
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is not None:
            changes["target_temperature"] = float(temperature)
        if (hvac_mode := kwargs.get(ATTR_HVAC_MODE)) is not None:
            if hvac_mode == HVACMode.OFF:
                changes["power"] = False
            else:
                changes["power"] = True
                changes["mode"] = HVAC_TO_HON[hvac_mode]
        if changes:
            await self._run(self._client.async_control(**changes))

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        await self._run(self._client.async_control(preset=preset_mode))

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        await self._run(self._client.async_control(**_fan_changes(fan_mode)))

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        await self._run(
            self._client.async_control(
                vertical_swing=swing_mode in (SWING_VERTICAL, SWING_BOTH),
                horizontal_swing=swing_mode in (SWING_HORIZONTAL, SWING_BOTH),
            )
        )

    async def async_apply_settings(self, **kwargs: Any) -> None:
        """Apply several settings at once: a single command, so a single beep."""
        changes: dict[str, Any] = {}
        if (hvac_mode := kwargs.get(ATTR_HVAC_MODE)) is not None:
            changes["power"] = hvac_mode != HVACMode.OFF
            if hvac_mode != HVACMode.OFF:
                changes["mode"] = HVAC_TO_HON[HVACMode(hvac_mode)]
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is not None:
            changes["target_temperature"] = temperature
        if (fan_mode := kwargs.get(ATTR_FAN_MODE)) is not None:
            changes.update(_fan_changes(fan_mode))
        if (preset_mode := kwargs.get(ATTR_PRESET_MODE)) is not None:
            changes["preset"] = preset_mode
        for key, positions in LOUVER_POSITIONS.items():
            if (option := kwargs.get(key)) is not None:
                axis = key.removesuffix("_position")
                if option == SWING:
                    changes[f"{axis}_swing"] = True
                else:
                    changes[f"{axis}_position"] = positions[option]
        if (display := kwargs.get(ATTR_DISPLAY)) is not None:
            changes["display"] = display
        if (health := kwargs.get(ATTR_HEALTH)) is not None:
            changes["health"] = health
        if not changes:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_settings")
        await self._run(self._client.async_control(**changes))
