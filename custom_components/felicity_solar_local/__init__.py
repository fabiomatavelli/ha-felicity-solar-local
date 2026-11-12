"""The Felicity Solar Local integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import (
    CONF_HOST,
    CONF_INVERT_CURRENT_SIGN,
    CONF_PERSISTENT_CONNECTION,
    CONF_PORT,
    CONF_UPDATE_INTERVAL,
    DEFAULT_INVERT_CURRENT_SIGN,
    DEFAULT_PERSISTENT_CONNECTION,
    DEFAULT_UPDATE_INTERVAL,
)
from .coordinator import FelicityLocalCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]

type FelicityLocalConfigEntry = ConfigEntry[FelicityLocalCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: FelicityLocalConfigEntry) -> bool:
    """Set up Felicity Solar Local from a config entry."""
    host = entry.data[CONF_HOST]
    port = entry.data[CONF_PORT]
    update_interval = entry.options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
    persistent_connection = entry.options.get(
        CONF_PERSISTENT_CONNECTION, DEFAULT_PERSISTENT_CONNECTION
    )
    invert_current_sign = entry.options.get(CONF_INVERT_CURRENT_SIGN, DEFAULT_INVERT_CURRENT_SIGN)

    coordinator = FelicityLocalCoordinator(
        hass=hass,
        config_entry=entry,
        host=host,
        port=port,
        update_interval=update_interval,
        persistent_connection=persistent_connection,
        invert_current_sign=invert_current_sign,
    )
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: FelicityLocalConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    await entry.runtime_data.client.async_close()
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: FelicityLocalConfigEntry) -> None:
    """Reload the entry when its options change (e.g. update_interval)."""
    await hass.config_entries.async_reload(entry.entry_id)
