"""End-to-end test: config entry setup produces the expected sensor entities."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.felicity_solar_local.const import (
    CONF_ENABLE_RAW_DATA_SENSOR,
    CONF_HOST,
    CONF_PORT,
    DOMAIN,
)

pytestmark = pytest.mark.asyncio

API_PATH = "custom_components.felicity_solar_local.coordinator.FelicityLocalClient.async_get_data"
TZ_PATH = (
    "custom_components.felicity_solar_local.coordinator.FelicityLocalClient"
    ".async_get_timezone_offset_minutes"
)


async def test_setup_entry_creates_sensors_with_correct_state(
    hass: HomeAssistant, sample_response: dict[str, Any]
) -> None:
    serial = sample_response["DevSN"]
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=serial,
        data={CONF_HOST: "192.168.1.50", CONF_PORT: 53970},
    )
    entry.add_to_hass(hass)

    with (
        patch(API_PATH, AsyncMock(return_value=sample_response)),
        patch(TZ_PATH, AsyncMock(return_value=60)),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    registry = er.async_get(hass)

    voltage_entity_id = registry.async_get_entity_id("sensor", DOMAIN, f"{serial}_voltage")
    assert voltage_entity_id is not None
    voltage_state = hass.states.get(voltage_entity_id)
    assert voltage_state is not None
    assert float(voltage_state.state) == 54.04

    # Per-cell voltage sensors are registered but disabled by default (16 of them would
    # otherwise clutter the entity list) - confirm registration without expecting a state.
    cell_entity_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{serial}_cell_1_voltage"
    )
    assert cell_entity_id is not None
    assert registry.entities[cell_entity_id].disabled is True


async def test_raw_data_sensor_absent_by_default(
    hass: HomeAssistant, sample_response: dict[str, Any]
) -> None:
    serial = sample_response["DevSN"]
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=serial,
        data={CONF_HOST: "192.168.1.50", CONF_PORT: 53970},
    )
    entry.add_to_hass(hass)

    with (
        patch(API_PATH, AsyncMock(return_value=sample_response)),
        patch(TZ_PATH, AsyncMock(return_value=60)),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    registry = er.async_get(hass)
    assert registry.async_get_entity_id("sensor", DOMAIN, f"{serial}_raw_data") is None


async def test_raw_data_sensor_present_when_enabled(
    hass: HomeAssistant, sample_response: dict[str, Any]
) -> None:
    serial = sample_response["DevSN"]
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=serial,
        data={CONF_HOST: "192.168.1.50", CONF_PORT: 53970},
        options={CONF_ENABLE_RAW_DATA_SENSOR: True},
    )
    entry.add_to_hass(hass)

    with (
        patch(API_PATH, AsyncMock(return_value=sample_response)),
        patch(TZ_PATH, AsyncMock(return_value=60)),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    registry = er.async_get(hass)
    raw_entity_id = registry.async_get_entity_id("sensor", DOMAIN, f"{serial}_raw_data")
    assert raw_entity_id is not None
    raw_state = hass.states.get(raw_entity_id)
    assert raw_state is not None
    assert raw_state.attributes["profile"] == "FLB48314TG1-H"
    assert raw_state.attributes["profile_confidence"] == "verified"
    assert raw_state.attributes["raw"]["DevSN"] == serial


async def test_setup_entry_creates_charging_state_sensor(
    hass: HomeAssistant, sample_response: dict[str, Any]
) -> None:
    serial = sample_response["DevSN"]
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=serial,
        data={CONF_HOST: "192.168.1.50", CONF_PORT: 53970},
    )
    entry.add_to_hass(hass)

    with (
        patch(API_PATH, AsyncMock(return_value=sample_response)),
        patch(TZ_PATH, AsyncMock(return_value=60)),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("sensor", DOMAIN, f"{serial}_charging_state")
    assert entity_id is not None
    assert registry.entities[entity_id].disabled is False

    state = hass.states.get(entity_id)
    assert state is not None
    # sample_response.json's Bstate (9152) has bit 13 set -> charging.
    assert state.state == "charging"
    assert state.attributes["options"] == ["charging", "discharging", "standby"]
    assert state.attributes["device_class"] == "enum"


async def test_unload_entry(hass: HomeAssistant, sample_response: dict[str, Any]) -> None:
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

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state.value == "not_loaded"


async def _setup(hass: HomeAssistant, response: dict[str, Any]) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=response["DevSN"],
        data={CONF_HOST: "192.168.1.50", CONF_PORT: 53970},
    )
    entry.add_to_hass(hass)

    with (
        patch(API_PATH, AsyncMock(return_value=response)),
        patch(TZ_PATH, AsyncMock(return_value=60)),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_cycle_count_sensor_created_when_firmware_reports_it(
    hass: HomeAssistant, fla48300_response: dict[str, Any]
) -> None:
    serial = fla48300_response["DevSN"]
    await _setup(hass, fla48300_response)

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("sensor", DOMAIN, f"{serial}_cycle_count")
    assert entity_id is not None
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "219"


async def test_cycle_count_sensor_skipped_when_firmware_omits_it(
    hass: HomeAssistant, sample_response: dict[str, Any]
) -> None:
    # sample_response.json comes from firmware that doesn't send BmsCnt (issue #58).
    assert "BmsCnt" not in sample_response
    serial = sample_response["DevSN"]
    await _setup(hass, sample_response)

    registry = er.async_get(hass)
    assert registry.async_get_entity_id("sensor", DOMAIN, f"{serial}_cycle_count") is None
    assert registry.async_get_entity_id("sensor", DOMAIN, f"{serial}_voltage") is not None


async def test_stale_cycle_count_entity_removed_when_firmware_omits_it(
    hass: HomeAssistant, sample_response: dict[str, Any]
) -> None:
    # Earlier versions always registered cycle_count, leaving it stuck at "unknown".
    serial = sample_response["DevSN"]
    registry = er.async_get(hass)
    registry.async_get_or_create("sensor", DOMAIN, f"{serial}_cycle_count")

    await _setup(hass, sample_response)

    assert registry.async_get_entity_id("sensor", DOMAIN, f"{serial}_cycle_count") is None


def _battery_device(hass: HomeAssistant, serial: str) -> dr.DeviceEntry | None:
    # Looked up through an entity rather than by identifier: device_registry's
    # async_get_device() is deprecated in newer Home Assistant releases.
    entity_id = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{serial}_voltage")
    assert entity_id is not None
    device_id = er.async_get(hass).entities[entity_id].device_id
    assert device_id is not None
    return dr.async_get(hass).async_get(device_id)


async def test_device_reports_firmware_version(
    hass: HomeAssistant, sample_response: dict[str, Any]
) -> None:
    await _setup(hass, sample_response)

    device = _battery_device(hass, sample_response["DevSN"])
    assert device is not None
    assert device.sw_version == "M1 203, M2 8, WiFi 2.10"


async def test_device_without_firmware_info(
    hass: HomeAssistant, sample_response: dict[str, Any], mock_basic_info: AsyncMock
) -> None:
    # Older WiFi modules may not answer the basic-info query at all.
    mock_basic_info.return_value = None
    await _setup(hass, sample_response)

    device = _battery_device(hass, sample_response["DevSN"])
    assert device is not None
    assert device.sw_version is None
