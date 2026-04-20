"""The PositionGuard integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import PositionGuardClient
from .const import CONF_BASE_URL, CONF_GROUP_IDS, DEFAULT_BASE_URL, DOMAIN
from .coordinator import PositionGuardCoordinator

_LOGGER = logging.getLogger(__name__)

# Which entity platforms this integration provides. For V1 we ship
# device_tracker only. binary_sensor comes in V0.2.
PLATFORMS: list[Platform] = [Platform.DEVICE_TRACKER]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up PositionGuard from a config entry.

    Called when HA starts (for existing entries) and when the user completes
    the config flow (for new entries). Must return True on success.
    """
    _LOGGER.debug("Setting up PositionGuard integration for entry %s", entry.entry_id)

    # Build the API client from config entry data.
    session = async_get_clientsession(hass)
    client = PositionGuardClient(
        session=session,
        api_key=entry.data[CONF_API_KEY],
        base_url=entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL),
    )

    # Create the coordinator and do the first fetch.
    coordinator = PositionGuardCoordinator(
        hass=hass,
        client=client,
        group_ids=entry.data.get(CONF_GROUP_IDS, []),
    )
    await coordinator.async_config_entry_first_refresh()

    # Stash the coordinator so entity platforms can reach it.
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Forward setup to the entity platforms (device_tracker, etc.)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Listen for options changes (user clicks 'Configure' and picks new groups).
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry.

    Called when the user removes the integration. Must clean up everything
    async_setup_entry created.
    """
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options updates (from the 'Configure' button).

    We just reload the entry — coordinator re-inits with fresh config.
    """
    await hass.config_entries.async_reload(entry.entry_id)