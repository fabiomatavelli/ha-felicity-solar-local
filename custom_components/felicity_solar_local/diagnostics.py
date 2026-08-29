"""Diagnostics support for Felicity Solar Local."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import FelicityLocalConfigEntry
from .const import CONF_HOST

# "DevSN"/"wifiSN" are the raw payload keys; "serial_number" is the parsed alias
# profiles.parse_common() derives from "DevSN". Diagnostics get pasted into public
# issue threads, so every spelling of the serial has to be covered.
TO_REDACT = {CONF_HOST, "DevSN", "wifiSN", "serial_number"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: FelicityLocalConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data

    return {
        "entry_data": async_redact_data(dict(entry.data), TO_REDACT),
        "entry_options": dict(entry.options),
        "profile": coordinator.data.profile.name,
        "profile_confidence": coordinator.data.profile.confidence,
        "parsed_data": async_redact_data(coordinator.data.data, TO_REDACT),
        "raw_data": async_redact_data(coordinator.data.raw, TO_REDACT),
    }
