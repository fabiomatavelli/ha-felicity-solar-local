"""Diagnostics must not leak the device serial or the host address."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.diagnostics import REDACTED
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.felicity_solar_local.const import CONF_HOST, CONF_PORT, DOMAIN
from custom_components.felicity_solar_local.diagnostics import (
    async_get_config_entry_diagnostics,
)

pytestmark = pytest.mark.asyncio

API_PATH = "custom_components.felicity_solar_local.coordinator.FelicityLocalClient.async_get_data"
TZ_PATH = (
    "custom_components.felicity_solar_local.coordinator.FelicityLocalClient"
    ".async_get_timezone_offset_minutes"
)


async def _setup_entry(
    hass: HomeAssistant, sample_response: dict[str, Any]
) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=sample_response["DevSN"],
        data={CONF_HOST: "192.168.1.50", CONF_PORT: 53970},
    )
    entry.add_to_hass(hass)

    with (
        patch(API_PATH, AsyncMock(return_value=sample_response)),
        patch(TZ_PATH, AsyncMock(return_value=60)),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    return entry


async def test_diagnostics_redacts_serial_in_every_section(
    hass: HomeAssistant, sample_response: dict[str, Any]
) -> None:
    """The serial appears in raw_data as DevSN and in parsed_data as serial_number."""
    serial = sample_response["DevSN"]
    entry = await _setup_entry(hass, sample_response)

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["raw_data"]["DevSN"] == REDACTED
    assert diagnostics["parsed_data"]["serial_number"] == REDACTED
    assert serial not in str(diagnostics)


async def test_diagnostics_redacts_host(
    hass: HomeAssistant, sample_response: dict[str, Any]
) -> None:
    entry = await _setup_entry(hass, sample_response)

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["entry_data"][CONF_HOST] == REDACTED
    assert "192.168.1.50" not in str(diagnostics)


async def test_diagnostics_keeps_non_sensitive_readings(
    hass: HomeAssistant, sample_response: dict[str, Any]
) -> None:
    """Redaction must not gut the payload the diagnostics exist to show."""
    entry = await _setup_entry(hass, sample_response)

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["parsed_data"]["voltage"] == 54.04
    assert diagnostics["parsed_data"]["soc"] is not None
    assert diagnostics["profile_confidence"] == "verified"
