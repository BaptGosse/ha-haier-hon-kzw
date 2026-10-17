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
- **Automatic reconnection** when the key restarts (power cut…).
- **No change to the key**: no firmware update, no Wi-Fi reconfiguration.

## Compatibility

| Hardware | Status |
|---|---|
| Thermor Nagano (2021) + 0011800292K key | ✅ tested on 5 units |
| Other Haier hOn unit with a KZW-W002 key on Wi-Fi | should work, feedback welcome |
| Haier unit speaking SmartAir2 (older models) | ❌ see [ddnlv/haier-kzw-w002-local](https://github.com/ddnlv/haier-kzw-w002-local) |
| Key that lost its Wi-Fi configuration | put it back on Wi-Fi first with [haier-kzw-w002-wifi-tool](https://github.com/BaptGosse/haier-kzw-w002-wifi-tool), or replace it with an ESP32 running [ESPHome `haier`](https://esphome.io/components/climate/haier/) |

When a unit is added, the integration checks that the key really answers in hOn. An unsupported
unit is rejected with a clear message.

## Features

For each heat pump:

| Entity | Details |
|---|---|
| **Climate** | On/off, modes **Heat**, **Cool**, **Auto**, **Dry**, **Fan only**. Target from 16 to 30 °C. **Real action** (heating, cooling or idle), derived from the compressor. |
| **Fan** | **Quiet**, Auto, Low, Medium, High, **Turbo**. This covers the remote's "auto" variants. |
| **Swing** | Off, Vertical, Horizontal, Both. |
| **Louver position** | Vertical (highest to lowest, plus the "health" positions) and horizontal (far left to far right), set without swinging. |
| **Display** | Turns the indoor unit's display on or off. No need for the remote after a power cut. |
| **Command beep** | Mutes the beep of commands sent by Home Assistant, handy at night. |
| **Temperatures** | Indoor, and outdoor (outdoor unit sensor). |
| **Power (W)** and **Energy (kWh)** | Live and cumulative consumption, ready for the Home Assistant **Energy** dashboard. |
| **Diagnostics** | Compressor frequency and current, coil, defrost and exhaust air temperatures, expansion valve opening, error code. Some of these entities are disabled by default. |

Everything can be used in Home Assistant automations and scripts. For example, you can turn the
heating on at a set time, lower the target temperature at night, mute the beeps in the evening, or
get alerted when a unit reports an error code.

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

In **Settings → Dashboards → Energy**, add each unit's **Energy** sensor as a consumption source,
with a price per kWh. The price can be a fixed number or, better, a number helper that you update
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
