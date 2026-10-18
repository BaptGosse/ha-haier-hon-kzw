"""Electrical power and heat output estimate for units that do not report their consumption.

Refrigerant-side model of the outdoor unit, calibrated on the Haier 2U50S2SM1FA service manual (sold by Thermor
as NAGANO BI 5000, R32 rotary compressor). Electrical power and heat come from the same energy balance:

    mass flow    m = f × D × ρ_suction(T_evap) × (1 − 0.02 × (pressure ratio − 1))
    compressor   P = m × Δh_isentropic(T_evap, T_cond) / η(f) × calibration
    evaporator   Q_evap = m × (h_vapour(T_evap) − h_liquid(T_cond))
    heating      Q = Q_evap + 93 % of P   (the rest is lost outdoors: compressor shell, inverter)
    outdoor unit P + outdoor fan (10 W + 30 W × f / 90, 40 W max) + controller (10 W)

Heating: T_cond is the indoor coil of the units that are heating (the coil of a unit that is off in a multi-split
sees hot discharge gas and is ignored). No probe reads the evaporating temperature in steady state (the outdoor
coil and defrost probes read the coil outlet, close to outdoor air), so T_evap = outdoor air − a_e × Q_evap.
Cooling: T_evap is the indoor coil of the units that are cooling, T_cond = outdoor air + a_c × heat rejected.

Calibration (Haier manual): heating 4.7 kW for 1.40 kW nominal (model 1.38 kW at 90 Hz), 1.8 kW at 30 Hz
(1.73), 6.6 kW at 118 Hz (6.08 kW for 2.16 kW, 9.1 A max running current), SCOP 4.0 (3.96); cooling 5 kW for
1.45 kW nominal (exact). Cooling at low load is optimistic (SEER 9 for 6.5 declared).
R32 properties: closed-form fits of CoolProp, within 0.5 % from -25 to 65 °C.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

# R32 fits: ln psat(kPa) = A − B / (T + C); suction state with 5 K superheat; liquid with 4 K subcooling
_PSAT_B, _PSAT_C = 2373.2947565505415, 272.06544086764626
_RHO = (6.992897623526712e-07, -8.999898560729264e-05, 0.03187580497499889, 3.0618752604991313)
_H_VAP = (-2.397733642022399e-05, -0.004214912770446225, 0.23316798601847613, 521.3718854380373)
_H_LIQ = (7.289560386079905e-05, -0.0021852161601835377, 1.8489177699180528, 191.9872202051941)
_DH_IS = (38.05647889545898, 0.005954644656000145, 3.2868685140415685, -0.021865088489594404,
          -0.01322396605751252, -0.0014655766822688522)

# Haier 2U50S2SM1FA calibration
DISPLACEMENT = 7.3395      # cm³, effective (displacement × volumetric efficiency at low pressure ratio)
EVAP_APPROACH = 2.2115     # K per kW taken from outdoor air (heating)
COND_APPROACH = 1.4        # K per kW rejected to outdoor air (cooling)
ETA_PEAK = 0.4936          # overall compressor efficiency (isentropic × motor × inverter) at its best
ETA_PEAK_HZ = 55.0
ETA_LOW = 0.1987           # quadratic drop below the best frequency
ETA_HIGH = 0.1820          # linear drop above it
COOLING_FACTOR = 1.0905    # the manual rates cooling slightly better than heating
SHELL_LOSS = 0.07
MAX_GROUP_POWER = 2150.0   # W, 9.1 A max running current


def _poly(coefs: tuple[float, ...], x: float) -> float:
    value = 0.0
    for c in coefs:
        value = value * x + c
    return value


def _cycle(t_evap: float, t_cond: float) -> tuple[float, float, float, float]:
    """Suction density (kg/m³), evaporator Δh, isentropic Δh (kJ/kg) and pressure ratio."""
    x = _PSAT_B / (t_evap + _PSAT_C) - _PSAT_B / (t_cond + _PSAT_C)  # ln(p_cond / p_evap)
    c = _DH_IS
    dh_is = x * (c[0] + c[1] * t_evap + c[2] * x + c[3] * t_evap * x + c[4] * x * x + c[5] * t_evap * t_evap)
    return math.exp(_poly(_RHO, t_evap)), _poly(_H_VAP, t_evap) - _poly(_H_LIQ, t_cond), dh_is, math.exp(x)


def compressor_efficiency(frequency: float) -> float:
    x = (frequency - ETA_PEAK_HZ) / ETA_PEAK_HZ
    k = 1 - ETA_LOW * x * x if x < 0 else 1 - ETA_HIGH * x
    return max(0.2, ETA_PEAK * k)


def outdoor_fan_power(frequency: float) -> float:
    return 10 + 30 * min(frequency / 90, 1) + 10


@dataclass
class Cycle:
    compressor: float  # W electrical, compressor only
    evaporator: float  # W taken by the evaporator (outdoor air when heating, indoor air when cooling)
    t_evap: float
    t_cond: float

    def heat(self, cooling: bool, calibration: float = 1.0) -> float:
        """W delivered indoors: the evaporator when cooling, evaporator + compressor heat when heating."""
        return self.evaporator if cooling else self.evaporator + (1 - SHELL_LOSS) * self.compressor * calibration


def heating_cycle(frequency: float, t_outdoor: float, t_cond: float, calibration: float = 1.0) -> Cycle:
    eta = compressor_efficiency(frequency)
    t_evap, p_comp, q_evap = t_outdoor - 3, 0.0, 0.0
    for _ in range(4):
        tc = max(t_cond, t_evap + 8)
        rho, dh_evap, dh_is, ratio = _cycle(t_evap, tc)
        flow = frequency * DISPLACEMENT * 1e-6 * rho * (1 - 0.02 * (ratio - 1))
        p_comp = flow * dh_is * 1000 / eta * calibration
        q_evap = flow * dh_evap * 1000
        t_evap = t_outdoor - EVAP_APPROACH * q_evap / 1000
    return Cycle(p_comp, q_evap, t_evap, max(t_cond, t_evap + 8))


def cooling_cycle(frequency: float, t_outdoor: float, t_evap: float, calibration: float = 1.0) -> Cycle:
    eta = compressor_efficiency(frequency) * COOLING_FACTOR
    t_evap = min(max(t_evap, -5), t_outdoor - 3)
    t_cond, p_comp, q_evap = t_outdoor + 10, 0.0, 0.0
    for _ in range(4):
        tc = max(t_cond, t_evap + 8)
        rho, dh_evap, dh_is, ratio = _cycle(t_evap, tc)
        flow = frequency * DISPLACEMENT * 1e-6 * rho * (1 - 0.02 * (ratio - 1))
        p_comp = flow * dh_is * 1000 / eta * calibration
        q_evap = flow * dh_evap * 1000
        t_cond = t_outdoor + COND_APPROACH * (q_evap + (1 - SHELL_LOSS) * p_comp) / 1000
    return Cycle(p_comp, q_evap, t_evap, max(t_cond, t_evap + 8))


# --- one outdoor unit shared by one or more indoor units -------------------------------------------------
HEAT, COOL, FAN, OFF = "heat", "cool", "fan", "off"


@dataclass
class Member:
    key: str
    mode: str                         # HEAT, COOL, FAN or OFF (what the unit is doing now)
    frequency: float | None           # compressor frequency reported by this unit (same for the group)
    t_outdoor: float | None
    indoor_coil: float | None
    expansion_valve: float | None
    fan_power: float = 25.0           # indoor fan and electronics while on (W)
    calibration: float = 1.0


@dataclass
class Share:
    power: float = 0.0
    heat: float = 0.0


@dataclass
class GroupEstimate:
    power: float = 0.0                # outdoor unit (compressor, fan, controller), W
    heat: float = 0.0                 # W delivered by all its indoor units
    cooling: bool = False
    shares: dict[str, Share] = field(default_factory=dict)

    @property
    def cop(self) -> float | None:
        indoor = sum(s.power for s in self.shares.values()) - self.power
        total = self.power + max(indoor, 0)
        return self.heat / total if total > 0 and self.heat > 0 else None


def estimate_group(members: list[Member]) -> GroupEstimate:
    """Split the outdoor unit between the indoor units that use it, by expansion valve opening.

    Shares always add up to 100 %, so a multi-split is never counted twice. A unit in fan only mode or off only
    counts its own fan (when on).
    """
    result = GroupEstimate(shares={m.key: Share() for m in members})
    for m in members:
        if m.mode != OFF:
            result.shares[m.key].power = m.fan_power
    frequency = max((m.frequency or 0) for m in members)
    if frequency <= 0:
        return result
    users = [m for m in members if m.mode in (HEAT, COOL)]
    cooling = any(m.mode == COOL for m in users)
    t_outdoor = next((m.t_outdoor for m in members if m.t_outdoor is not None), 10.0)
    coils = [m.indoor_coil for m in users if m.indoor_coil is not None and m.mode == (COOL if cooling else HEAT)]
    weights = {m.key: (m.expansion_valve or 0) for m in users}
    if not users or sum(weights.values()) <= 0:
        # no unit asks for the compressor (defrost, run-on) or the valves don't tell: equal split
        pool = users or members
        weights = {m.key: 1.0 for m in pool}
    total_weight = sum(weights.values())
    calibration = {m.key: m.calibration for m in members}
    cycle = (cooling_cycle(frequency, t_outdoor, min(coils) if coils else 10.0) if cooling
             else heating_cycle(frequency, t_outdoor, max(coils) if coils else t_outdoor + 20))
    result.cooling = cooling
    fan = outdoor_fan_power(frequency)
    for key, weight in weights.items():
        share = weight / total_weight
        cal = min(calibration[key], (MAX_GROUP_POWER - fan) / cycle.compressor) if cycle.compressor > 0 else 1.0
        power = (cycle.compressor * cal + fan) * share
        heat = cycle.heat(cooling, cal) * share
        result.shares[key].power += power
        result.shares[key].heat = heat
        result.power += power
        result.heat += heat
    return result
