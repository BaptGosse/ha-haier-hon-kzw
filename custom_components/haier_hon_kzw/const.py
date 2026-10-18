DOMAIN = "haier_hon_kzw"

# Options of each unit, for the consumption estimate
CONF_OUTDOOR_UNIT = "outdoor_unit"           # same name on the units that share one outdoor unit (multi-split)
CONF_INDOOR_FAN_POWER = "indoor_fan_power"   # W used by the indoor unit (fan, electronics) while it is on
CONF_POWER_CALIBRATION = "power_calibration" # multiplies the estimated compressor power
DEFAULT_INDOOR_FAN_POWER = 25
DEFAULT_POWER_CALIBRATION = 1.0

# Sent on every update of any unit: estimates depend on the other units of the same outdoor unit
SIGNAL_UPDATE = f"{DOMAIN}_update"
