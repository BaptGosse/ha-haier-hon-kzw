# Haier hOn local: KZW-W002 Wi-Fi key (Thermor Nagano…)

Home Assistant integration to control Haier **air-to-air heat pumps** (reversible air conditioners:
heating and cooling) **locally, without any cloud**. It also works with Thermor models built by Haier,
such as the **Nagano** range. It uses the **original KZW-W002 Wi-Fi key**: no extra hardware, and
nothing is changed on the key.

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=BaptGosse&repository=ha-haier-hon-kzw&category=integration)

## Why this project

**Thermor Nagano** air-to-air heat pumps are Haier units. Their Wi-Fi key (part number
**0011800292K** or **0011800292M**, Haier KZW-W002 family) depended on the **Smart Clima** app.

- **Smart Clima was shut down.** Overnight, the heat pumps could no longer be controlled remotely.
- **Intelligent Air**, the replacement app, **does not support 292M and 292K keys**. Only 292X keys
  are compatible, and nothing is offered for the others.
- **HaierSmartAir2** does not work anymore either.
- The vendor apps cannot re-pair a key that lost its Wi-Fi configuration. Trying the migration to
  the new app can therefore leave the key unusable.

As a result, recent heat pumps in perfect working order were reduced to their infrared remote,
because the online service they depended on was withdrawn without any alternative.

This integration gives that control back, **locally**, with no account and no third-party server.
The heat pumps no longer depend on a service that a manufacturer can shut down overnight.

## How it works

Even without the cloud, the key stays on Wi-Fi and listens locally on **TCP port 56800**. It relays
the **hOn** protocol spoken by the indoor unit's control board, the same one as the ESPHome `haier`
component with `protocol: hon`. Frames are wrapped in an 80-byte header. The integration speaks
this protocol directly:

- **Real-time updates**: the key pushes the state as soon as it changes, including when the infrared
  remote is used.
- **Polling every 10 s**: the key drops an idle connection after about 17 s. Detailed data (power,
  compressor, coils) is read every 30 s.
- **Automatic reconnection** when the key restarts (power cut…). A command sent during a reconnection
  waits for the key instead of being lost, and a command the key did not answer is sent once more.
- **No change to the key**: no firmware update, no Wi-Fi reconfiguration.

## Compatibility

| Hardware | Status |
|-|-|
| Thermor Nagano (2021) + 0011800292K key | ✅ tested on 5 units |
| Other Haier hOn unit with a KZW-W002 key on Wi-Fi | should work, feedback welcome |
| Haier unit speaking SmartAir2 (older models) | ❌ see [ddnlv/haier-kzw-w002-local](https://github.com/ddnlv/haier-kzw-w002-local) |
| Key that lost its Wi-Fi configuration | put it back on Wi-Fi first with [haier-kzw-w002-wifi-tool](https://github.com/BaptGosse/haier-kzw-w002-wifi-tool), or replace it with an ESP32 running [ESPHome `haier`](https://esphome.io/components/climate/haier/) |

When a unit is added, the integration checks that the key really answers in hOn. An unsupported
unit is rejected with a clear message.

## Features

For each heat pump:

| Entity | Details |
|-|-|
| **Climate** | On/off, modes **Heat**, **Cool**, **Auto**, **Dry**, **Fan only**. Target from 16 to 30 °C. Presets **Sleep** and **Frost protection 10 °C** (heat mode). **Real action** (heating, cooling or idle), derived from the compressor. |
| **Fan** | **Quiet**, Auto, Low, Medium, High, **Turbo**. This covers the remote's "auto" variants. |
| **Swing** | Off, Vertical, Horizontal, Both. |
| **Louver position** | Vertical (highest to lowest, plus the "health" positions) and horizontal (far left to far right), set without swinging. |
| **Display** | Turns the indoor unit's display on or off, silently. No need for the remote after a power cut. |
| **Command beep** | Mutes the beep of commands sent by Home Assistant, handy at night. |
| **Ionizer** and **Remote control lock** | The unit's "health" ionizer, and locking of the infrared remote. |
| **Self cleaning** and **Steri cleaning 56 °C** | Buttons that start the indoor unit's cleaning cycles. |
| **Filter needs cleaning**, **Cleaning running**, **Compressor** | On/off states for alerts and automations. |
| **Temperatures** | Indoor, and outdoor (outdoor unit sensor). |
| **Power (W)** and **Energy (kWh)** | Live and cumulative consumption, ready for the Home Assistant **Energy** dashboard, **when the unit reports it**. Thermor Nagano units leave this field at 0. The integration detects it (compressor running, 0 W) and marks both sensors unavailable instead of showing a false 0. |
| **Estimated power, energy, thermal power and COP** | For units that don't report their consumption: a physical estimate from the compressor frequency and the coil temperatures, shared between the indoor units of a multi-split. See [Consumption estimate](#consumption-estimate). |
| **Diagnostics** | Compressor frequency and current, indoor and outdoor coil, defrost and compressor discharge temperatures, expansion valve opening, error code. |

Everything can be used in Home Assistant automations and scripts. For example, you can turn the
heating on at a set time, lower the target temperature at night, mute the beeps in the evening, or
get alerted when a unit reports an error code.

## Applying several settings at once

The **`haier_hon_kzw.apply_settings`** action sets any combination of mode, target temperature, fan,
preset, louver positions, display and ionizer in **a single command**, so the unit beeps once.
Settings that are left out (or empty) are not changed.

```yaml
action: haier_hon_kzw.apply_settings
target:
  entity_id: climate.living_room
data:
  hvac_mode: heat           # off, heat, cool, heat_cool, dry, fan_only
  temperature: 21
  fan_mode: turbo           # quiet, auto, low, medium, high, turbo
  vertical_position: swing  # max_up, up, center, down, max_down, health_up, health_down, swing
  horizontal_position: center
  preset_mode: none         # none, sleep, away (frost protection, heat mode only)
  display: false
```

### Schedules and daily curves

With [Scheduler](https://github.com/nielsfaber/scheduler-component) and its
[card](https://github.com/nielsfaber/scheduler-card), the action can be offered in the card. Each
timeslot then applies several settings at once. In **scheme mode**, the day becomes a timeline of
timeslots, which makes a curve: for example turbo fan from 6:30 to 7:00, then auto, and a target
temperature that goes up in the morning and down at night.

```yaml
type: custom:scheduler-card
include:
  - climate.living_room
customize:
  climate.living_room:  # or "climate" to pick several units in the same schedule
    actions:
      - service: haier_hon_kzw.apply_settings
        name: Settings
        icon: mdi:tune-variant
        variables:
          hvac_mode:
            name: Mode
            options: [{value: "off", name: "Off"}, {value: heat, name: Heat}, {value: cool, name: Cool}]
          temperature:  # a list rather than a number, so that it can stay empty
            name: Target
            options: [{value: "19", name: "19 °C"}, {value: "20", name: "20 °C"}, {value: "21", name: "21 °C"}]
          fan_mode:
            name: Fan
            options: [{value: quiet, name: Quiet}, {value: auto, name: Auto}, {value: turbo, name: Turbo}]
```

## Consumption estimate

Thermor Nagano units report neither their power nor their compressor current. The integration estimates them
from what the units do report, with a physical model of the outdoor unit. Each unit gets four sensors:

| Sensor | Meaning |
|-|-|
| **Estimated power** (W) | Electricity used for this room: its share of the outdoor unit, plus its indoor fan |
| **Estimated energy** (kWh) | The same, integrated over time. Add it to the **Energy** dashboard, with your price per kWh. |
| **Thermal power** (W) | Heat (or cooling) delivered to the room |
| **Estimated COP** | Heat delivered per unit of electricity, for the whole outdoor unit |

**Multi-split outdoor units.** In each unit's options (**Settings → Devices & services → Haier hOn local →
Configure**), give the same **outdoor unit** name to the units that share one outdoor unit, for example
`outdoor 2`. The compressor is then counted once and shared by expansion valve opening between the units that use
it, so nothing is counted twice. Leave it empty for a unit alone on its outdoor unit.

**How it works.** Electrical power and heat come from the same energy balance on the R32 refrigerant:

```
mass flow    m = f × D × ρ_suction(T_evap) × (1 − 0.02 × (pressure ratio − 1))
compressor   P = m × Δh_isentropic(T_evap, T_cond) / η(f)
heat         Q = m × (h_vapour − h_liquid) + 93 % of P        (heating)
outdoor unit P + outdoor fan + controller
```

- When heating, the **condensing temperature** is the indoor coil of the units that are heating. In a multi-split,
  the coil of a unit that is off reads hot discharge gas, and is ignored.
- No probe reads the **evaporating temperature** in steady state: the outdoor coil and defrost probes read the coil
  outlet, close to the outdoor air. So it is derived from the outdoor temperature and the heat taken from the air.
- The model is calibrated on the **Haier 2U50S2SM1FA** service manual (Thermor NAGANO BI 5000). It matches the
  nominal heating point (4.7 kW for 1.40 kW: model 1.38 kW), the minimum and maximum capacities within 8 %, the
  SCOP (4.0: model 3.96) and the nominal cooling point.
- Expected accuracy is about **±15 % when heating**. Cooling at low load is optimistic for now.

**Calibration.** If you can measure the real consumption once (a clamp meter on the outdoor unit, or your
electricity meter with everything else off), set **Power calibration** in the unit's options to
`current calibration × measured / estimated`. It applies to the compressor of that unit's share. Other outdoor
units than the 2U50S2SM1FA can be brought closer the same way.

## Installation

1. Click the **Open in HACS** button above, or in HACS → ⋮ → **Custom repositories** add
   `https://github.com/BaptGosse/ha-haier-hon-kzw`, category **Integration**.
2. Download **Haier hOn local (KZW-W002)**, then restart Home Assistant.
3. **Settings → Devices & services → Add integration → Haier hOn local**, then enter a name, the
   key's **IP address** and its **MAC address**. Both are listed among the devices in your router.

If Home Assistant is on the same network as the heat pumps, the keys are also **discovered
automatically**, and a new IP address is picked up on its own. Otherwise, use **Reconfigure** on the
integration entry.

### Tracking the cost of each heat pump

In **Settings → Dashboards → Energy**, add each unit's **Energy** sensor as a consumption source (or its
**Estimated energy** sensor if the unit does not report its consumption, like the Thermor Nagano), with a
price per kWh. The price can be a fixed number or, better, a number helper that you update
when your tariff changes. The Energy dashboard then shows kWh and cost per day, week, month or year.

## Tips

- **Never press the key's button** and never reset it.
- **One client at a time**: the key serves a single connection. Run **only one** Home Assistant
  instance against it, and remember to shut down any test setup.
- Reserve a **fixed IP address** (DHCP lease) for each key in your router.
- If possible, **block Internet access for the keys** in your router: a key firmware (2.5.14) has
  already removed local access for some users.

## Disclaimer

Unofficial project, not affiliated with Haier or Thermor. Provided as is, without warranty. Use at
your own risk.

## License

[MIT](LICENSE)

## Credits

- [ESPHome `haier` component](https://github.com/esphome/esphome/tree/dev/esphome/components/haier)
  and [HaierProtocol](https://github.com/paveldn/HaierProtocol) (paveldn): reference for the hOn protocol.
- [bstuff/haier-ac-remote](https://github.com/bstuff/haier-ac-remote): TCP header of the KZW-W002 keys.
- [ddnlv/haier-kzw-w002-local](https://github.com/ddnlv/haier-kzw-w002-local): starting point.
