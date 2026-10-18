"""Units sharing one outdoor unit, and the estimate inputs read from each of them."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant

from .const import (
    CONF_INDOOR_FAN_POWER,
    CONF_OUTDOOR_UNIT,
    CONF_POWER_CALIBRATION,
    DEFAULT_INDOOR_FAN_POWER,
    DEFAULT_POWER_CALIBRATION,
    DOMAIN,
)
from .estimation import COOL, FAN, HEAT, OFF, GroupEstimate, Member, estimate_group
from .protocol import MODE_COOL, MODE_DRY, MODE_ENERGY_SAVING, MODE_FAN, MODE_HEALTHY_DRY, MODE_HEAT


def _outdoor_unit(entry: ConfigEntry) -> str:
    return str(entry.options.get(CONF_OUTDOOR_UNIT, "")).strip().casefold()


def group_entries(hass: HomeAssistant, entry: ConfigEntry) -> list[ConfigEntry]:
    """Loaded entries on the same outdoor unit as `entry` (only itself when no outdoor unit is set)."""
    name = _outdoor_unit(entry)
    if not name:
        return [entry]
    # the unit itself is always included, even while it is still being set up
    return [
        e
        for e in hass.config_entries.async_entries(DOMAIN)
        if e is entry or (e.state is ConfigEntryState.LOADED and _outdoor_unit(e) == name)
    ]


def member(entry: ConfigEntry) -> Member:
    client = entry.runtime_data
    status, big = client.status, client.big
    mode = OFF
    if status is not None and status.power and client.available:
        if status.mode == MODE_HEAT:
            mode = HEAT
        elif status.mode in (MODE_COOL, MODE_DRY, MODE_HEALTHY_DRY, MODE_ENERGY_SAVING):
            mode = COOL
        elif status.mode == MODE_FAN:
            mode = FAN
        else:  # auto: the 4-way valve tells heating from cooling
            mode = HEAT if big is not None and big.four_way_valve == 1 else COOL
    t_outdoor = None
    if status is not None and status.outdoor_temperature > -64:
        t_outdoor = float(status.outdoor_temperature)
    elif big is not None and big.outdoor_in_air_temperature is not None:
        t_outdoor = float(big.outdoor_in_air_temperature)
    return Member(
        key=entry.entry_id,
        mode=mode,
        frequency=big.compressor_frequency if big is not None and client.available else None,
        t_outdoor=t_outdoor,
        indoor_coil=big.indoor_coil_temperature if big is not None else None,
        expansion_valve=big.expansion_valve if big is not None else None,
        fan_power=float(entry.options.get(CONF_INDOOR_FAN_POWER, DEFAULT_INDOOR_FAN_POWER)),
        calibration=float(entry.options.get(CONF_POWER_CALIBRATION, DEFAULT_POWER_CALIBRATION)),
    )


def estimate(hass: HomeAssistant, entry: ConfigEntry) -> GroupEstimate:
    return estimate_group([member(e) for e in group_entries(hass, entry)])
