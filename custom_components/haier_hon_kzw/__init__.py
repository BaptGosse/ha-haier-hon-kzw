"""Local control of Haier hOn air conditioners through their KZW-W002 Wi-Fi key."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_MAC, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .client import HonKzwClient
from .const import DOMAIN

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CLIMATE,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

type HonKzwConfigEntry = ConfigEntry[HonKzwClient]


async def async_setup_entry(hass: HomeAssistant, entry: HonKzwConfigEntry) -> bool:
    client = HonKzwClient(entry.data[CONF_HOST], entry.data[CONF_MAC])
    entry.async_create_background_task(hass, client.run(), f"{DOMAIN} {client.host}")
    try:
        await client.wait_ready(15)
    except TimeoutError as err:
        await client.stop()
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="not_ready",
            translation_placeholders={"host": client.host},
        ) from err
    entry.runtime_data = client
    entry.async_on_unload(client.stop)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HonKzwConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
