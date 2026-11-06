"""Tests for the Felicity Solar Local config and options flows."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.felicity_solar_local.api import (
    FelicityConnectionError,
    FelicityProtocolError,
    FelicityTimeoutError,
)
from custom_components.felicity_solar_local.const import (
    CONF_ENABLE_RAW_DATA_SENSOR,
    CONF_HOST,
    CONF_INVERT_CURRENT_SIGN,
    CONF_PERSISTENT_CONNECTION,
    CONF_PORT,
    CONF_UPDATE_INTERVAL,
    DOMAIN,
)

pytestmark = pytest.mark.asyncio

API_PATH = "custom_components.felicity_solar_local.config_flow.FelicityLocalClient.async_get_data"
TZ_PATH = (
    "custom_components.felicity_solar_local.config_flow.FelicityLocalClient"
    ".async_get_timezone_offset_minutes"
)


async def test_user_flow_success(
    hass: HomeAssistant, sample_response: dict[str, Any]
) -> None:
    # CREATE_ENTRY triggers a real async_setup_entry, which spins up a coordinator that
    # polls immediately - FelicityLocalClient is the same class regardless of which
    # module imported it, so this also covers the coordinator's client.
    with (
        patch(API_PATH, AsyncMock(return_value=sample_response)),
        patch(TZ_PATH, AsyncMock(return_value=None)),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "192.168.1.50", CONF_PORT: 53970}
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_HOST: "192.168.1.50", CONF_PORT: 53970}
    assert sample_response["DevSN"] in result["title"]


@pytest.mark.parametrize(
    ("exception", "expected_error"),
    [
        (FelicityConnectionError("boom"), "cannot_connect"),
        (FelicityTimeoutError("boom"), "timeout"),
        (FelicityProtocolError("boom"), "invalid_response"),
    ],
)
async def test_user_flow_errors(
    hass: HomeAssistant, exception: Exception, expected_error: str
) -> None:
    with patch(API_PATH, AsyncMock(side_effect=exception)):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "192.168.1.50", CONF_PORT: 53970}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected_error}


async def test_user_flow_aborts_for_inverter(
    hass: HomeAssistant, inverter_type81_response: dict[str, Any]
) -> None:
    with patch(API_PATH, AsyncMock(return_value=inverter_type81_response)):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "192.168.1.50", CONF_PORT: 53970}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_a_battery"
    assert not hass.config_entries.async_entries(DOMAIN)


async def test_user_flow_aborts_on_duplicate(
    hass: HomeAssistant, sample_response: dict[str, Any]
) -> None:
    existing = MockConfigEntry(
        domain=DOMAIN,
        unique_id=sample_response["DevSN"],
        data={CONF_HOST: "192.168.1.50", CONF_PORT: 53970},
    )
    existing.add_to_hass(hass)

    with patch(API_PATH, AsyncMock(return_value=sample_response)):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "192.168.1.50", CONF_PORT: 53970}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure_flow_success(
    hass: HomeAssistant, sample_response: dict[str, Any]
) -> None:
    # A successful reconfigure re-validates the new address, confirms it's still the
    # same battery (matching serial), updates the entry data and reloads it.
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=sample_response["DevSN"],
        data={CONF_HOST: "192.168.1.50", CONF_PORT: 53970},
    )
    entry.add_to_hass(hass)

    with (
        patch(API_PATH, AsyncMock(return_value=sample_response)),
        patch(TZ_PATH, AsyncMock(return_value=None)),
    ):
        result = await entry.start_reconfigure_flow(hass)
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "reconfigure"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "192.168.1.99", CONF_PORT: 53970}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data == {CONF_HOST: "192.168.1.99", CONF_PORT: 53970}


@pytest.mark.parametrize(
    ("exception", "expected_error"),
    [
        (FelicityConnectionError("boom"), "cannot_connect"),
        (FelicityTimeoutError("boom"), "timeout"),
        (FelicityProtocolError("boom"), "invalid_response"),
    ],
)
async def test_reconfigure_flow_errors(
    hass: HomeAssistant,
    sample_response: dict[str, Any],
    exception: Exception,
    expected_error: str,
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=sample_response["DevSN"],
        data={CONF_HOST: "192.168.1.50", CONF_PORT: 53970},
    )
    entry.add_to_hass(hass)

    with patch(API_PATH, AsyncMock(side_effect=exception)):
        result = await entry.start_reconfigure_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "192.168.1.99", CONF_PORT: 53970}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected_error}
    # The original address is kept on error.
    assert entry.data[CONF_HOST] == "192.168.1.50"


async def test_reconfigure_flow_allows_host_change_without_serial(
    hass: HomeAssistant, sample_response: dict[str, Any]
) -> None:
    # A battery that reports no serial can only be identified by its address, so
    # the identity check is skipped and a host change must still go through.
    no_serial = {k: v for k, v in sample_response.items() if k != "DevSN"}
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="192.168.1.50:53970",
        data={CONF_HOST: "192.168.1.50", CONF_PORT: 53970},
    )
    entry.add_to_hass(hass)

    with (
        patch(API_PATH, AsyncMock(return_value=no_serial)),
        patch(TZ_PATH, AsyncMock(return_value=None)),
    ):
        result = await entry.start_reconfigure_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "192.168.1.99", CONF_PORT: 53970}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data == {CONF_HOST: "192.168.1.99", CONF_PORT: 53970}


async def test_reconfigure_flow_aborts_for_wrong_device(
    hass: HomeAssistant, sample_response: dict[str, Any]
) -> None:
    # Pointing the entry at a different battery (serial mismatch) is refused.
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="a-different-serial",
        data={CONF_HOST: "192.168.1.50", CONF_PORT: 53970},
    )
    entry.add_to_hass(hass)

    with patch(API_PATH, AsyncMock(return_value=sample_response)):
        result = await entry.start_reconfigure_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "192.168.1.99", CONF_PORT: 53970}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_device"
    assert entry.data[CONF_HOST] == "192.168.1.50"


async def test_reconfigure_flow_aborts_for_inverter(
    hass: HomeAssistant,
    sample_response: dict[str, Any],
    inverter_type81_response: dict[str, Any],
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=sample_response["DevSN"],
        data={CONF_HOST: "192.168.1.50", CONF_PORT: 53970},
    )
    entry.add_to_hass(hass)

    with patch(API_PATH, AsyncMock(return_value=inverter_type81_response)):
        result = await entry.start_reconfigure_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "192.168.1.99", CONF_PORT: 53970}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_a_battery"
    assert entry.data[CONF_HOST] == "192.168.1.50"


async def test_options_flow_updates_interval(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="test-serial",
        data={CONF_HOST: "192.168.1.50", CONF_PORT: 53970},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_UPDATE_INTERVAL: 60,
            CONF_PERSISTENT_CONNECTION: False,
            CONF_ENABLE_RAW_DATA_SENSOR: False,
            CONF_INVERT_CURRENT_SIGN: True,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        CONF_UPDATE_INTERVAL: 60,
        CONF_PERSISTENT_CONNECTION: False,
        CONF_ENABLE_RAW_DATA_SENSOR: False,
        CONF_INVERT_CURRENT_SIGN: True,
    }


async def test_options_flow_rejects_low_interval_in_one_shot_mode(
    hass: HomeAssistant,
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="test-serial",
        data={CONF_HOST: "192.168.1.50", CONF_PORT: 53970},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_UPDATE_INTERVAL: 5,
            CONF_PERSISTENT_CONNECTION: False,
            CONF_ENABLE_RAW_DATA_SENSOR: False,
            CONF_INVERT_CURRENT_SIGN: True,
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "interval_too_low_for_one_shot"}


async def test_options_flow_allows_low_interval_when_persistent(
    hass: HomeAssistant,
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="test-serial",
        data={CONF_HOST: "192.168.1.50", CONF_PORT: 53970},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_UPDATE_INTERVAL: 5,
            CONF_PERSISTENT_CONNECTION: True,
            CONF_ENABLE_RAW_DATA_SENSOR: False,
            CONF_INVERT_CURRENT_SIGN: True,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        CONF_UPDATE_INTERVAL: 5,
        CONF_PERSISTENT_CONNECTION: True,
        CONF_ENABLE_RAW_DATA_SENSOR: False,
        CONF_INVERT_CURRENT_SIGN: True,
    }


async def test_options_flow_enables_raw_data_sensor(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="test-serial",
        data={CONF_HOST: "192.168.1.50", CONF_PORT: 53970},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_UPDATE_INTERVAL: 5,
            CONF_PERSISTENT_CONNECTION: True,
            CONF_ENABLE_RAW_DATA_SENSOR: True,
            CONF_INVERT_CURRENT_SIGN: True,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_ENABLE_RAW_DATA_SENSOR] is True


async def test_options_flow_disables_invert_current_sign(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="test-serial",
        data={CONF_HOST: "192.168.1.50", CONF_PORT: 53970},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_UPDATE_INTERVAL: 5,
            CONF_PERSISTENT_CONNECTION: True,
            CONF_ENABLE_RAW_DATA_SENSOR: False,
            CONF_INVERT_CURRENT_SIGN: False,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_INVERT_CURRENT_SIGN] is False


async def test_options_flow_defaults_to_persistent_five_seconds(
    hass: HomeAssistant,
) -> None:
    # Locks in the "new install picks up 5s/persistent automatically" behavior: a fresh
    # entry (no options set yet) must show these as the form's defaults.
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="test-serial",
        data={CONF_HOST: "192.168.1.50", CONF_PORT: 53970},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    defaults = {key.schema: key.default() for key in result["data_schema"].schema}
    assert defaults[CONF_PERSISTENT_CONNECTION] is True
    assert defaults[CONF_UPDATE_INTERVAL] == 5
    assert defaults[CONF_ENABLE_RAW_DATA_SENSOR] is False
    assert defaults[CONF_INVERT_CURRENT_SIGN] is True
