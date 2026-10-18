"""Local control of Haier hOn air conditioners through their KZW-W002 Wi-Fi key."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_MAC, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .client import HonKzwClient
from .const import DOMAIN, SIGNAL_UPDATE

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
    # units of one outdoor unit share its estimate: any update refreshes them all
    entry.async_on_unload(client.add_listener(lambda: async_dispatcher_send(hass, SIGNAL_UPDATE)))
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_options_updated(hass: HomeAssistant, entry: HonKzwConfigEntry) -> None:
    async_dispatcher_send(hass, SIGNAL_UPDATE)


async def async_unload_entry(hass: HomeAssistant, entry: HonKzwConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
