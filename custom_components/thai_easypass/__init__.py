"""Thai Easy Pass integration."""

from dataclasses import dataclass

from aiohttp import CookieJar
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import EasyPassClient
from .const import CONF_PASSWORD, CONF_USERNAME, PLATFORMS
from .coordinator import EasyPassCoordinator


@dataclass(slots=True)
class EasyPassRuntimeData:
    """Runtime objects owned by a config entry."""

    client: EasyPassClient
    coordinator: EasyPassCoordinator


type EasyPassConfigEntry = ConfigEntry[EasyPassRuntimeData]


async def async_setup_entry(
    hass: HomeAssistant, entry: EasyPassConfigEntry
) -> bool:
    """Set up Thai Easy Pass from a config entry."""
    session = async_create_clientsession(
        hass,
        cookie_jar=CookieJar(),
        headers={
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
            ),
            "Accept-Language": "th,en;q=0.9",
        },
    )
    client = EasyPassClient(
        session,
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
    )
    coordinator = EasyPassCoordinator(hass, entry, client)
    entry.runtime_data = EasyPassRuntimeData(client, coordinator)

    try:
        await coordinator.async_config_entry_first_refresh()
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        session.detach()
        raise
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: EasyPassConfigEntry
) -> bool:
    """Unload a config entry and its private cookie session."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
