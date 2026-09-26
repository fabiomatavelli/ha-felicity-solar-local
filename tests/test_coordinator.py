"""Tests for FelicityLocalCoordinator."""

from __future__ import annotations

import urllib.parse
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.felicity_solar_local import profiles
from custom_components.felicity_solar_local.api import FelicityConnectionError
from custom_components.felicity_solar_local.const import CONF_HOST, CONF_PORT, DOMAIN
from custom_components.felicity_solar_local.coordinator import FelicityLocalCoordinator
from custom_components.felicity_solar_local.profiles import FLB48314TG1H_PROFILE

pytestmark = pytest.mark.asyncio

API_PATH = "custom_components.felicity_solar_local.coordinator.FelicityLocalClient.async_get_data"
TZ_PATH = (
    "custom_components.felicity_solar_local.coordinator.FelicityLocalClient"
    ".async_get_timezone_offset_minutes"
)


def _make_coordinator(
    hass: HomeAssistant,
    persistent_connection: bool = False,
    invert_current_sign: bool = True,
) -> FelicityLocalCoordinator:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="test-serial",
        data={CONF_HOST: "192.168.1.50", CONF_PORT: 53970},
    )
    entry.add_to_hass(hass)
    return FelicityLocalCoordinator(
        hass=hass,
        config_entry=entry,
        host="192.168.1.50",
        port=53970,
        update_interval=30,
        persistent_connection=persistent_connection,
        invert_current_sign=invert_current_sign,
    )


async def test_update_data_selects_profile_and_parses(
    hass: HomeAssistant, sample_response: dict[str, Any]
) -> None:
    coordinator = _make_coordinator(hass)

    with (
        patch(API_PATH, AsyncMock(return_value=sample_response)),
        patch(TZ_PATH, AsyncMock(return_value=None)),
    ):
        result = await coordinator._async_update_data()

    assert result.raw == sample_response
    assert result.profile is FLB48314TG1H_PROFILE
    assert result.data["voltage"] == 54.04


async def test_update_data_fetches_timezone_offset_once_and_merges_it(
    hass: HomeAssistant, sample_response: dict[str, Any]
) -> None:
    coordinator = _make_coordinator(hass)
    tz_mock = AsyncMock(return_value=60)

    with (
        patch(API_PATH, AsyncMock(return_value=sample_response)),
        patch(TZ_PATH, tz_mock),
    ):
        first = await coordinator._async_update_data()
        second = await coordinator._async_update_data()

    assert first.raw["timeZMin"] == 60
    assert second.raw["timeZMin"] == 60
    # sample_response.json's "date" is "20260712121556" - at a merged +60min offset.
    assert first.data["device_timestamp"].utcoffset().total_seconds() == 60 * 60
    # The offset rarely changes (DST only), so it's fetched once per coordinator
    # lifetime, not on every poll.
    assert tz_mock.call_count == 1


async def test_update_data_does_not_retry_timezone_offset_after_a_failed_fetch(
    hass: HomeAssistant, sample_response: dict[str, Any]
) -> None:
    coordinator = _make_coordinator(hass)
    tz_mock = AsyncMock(return_value=None)

    with (
        patch(API_PATH, AsyncMock(return_value=sample_response)),
        patch(TZ_PATH, tz_mock),
    ):
        first = await coordinator._async_update_data()
        second = await coordinator._async_update_data()

    assert "timeZMin" not in first.raw
    assert "timeZMin" not in second.raw
    assert tz_mock.call_count == 1


async def test_update_data_raises_update_failed_on_client_error(
    hass: HomeAssistant,
) -> None:
    coordinator = _make_coordinator(hass)

    with (
        patch(API_PATH, AsyncMock(side_effect=FelicityConnectionError("boom"))),
        pytest.raises(UpdateFailed),
    ):
        await coordinator._async_update_data()


async def test_persistent_connection_flag_passed_to_client(hass: HomeAssistant) -> None:
    assert _make_coordinator(hass, persistent_connection=False).client.persistent is False
    assert _make_coordinator(hass, persistent_connection=True).client.persistent is True


async def test_invert_current_sign_flips_current_and_power_by_default(
    hass: HomeAssistant, sample_response: dict[str, Any]
) -> None:
    coordinator = _make_coordinator(hass)
    raw_data = FLB48314TG1H_PROFILE.parse(sample_response)

    with (
        patch(API_PATH, AsyncMock(return_value=sample_response)),
        patch(TZ_PATH, AsyncMock(return_value=None)),
    ):
        result = await coordinator._async_update_data()

    assert result.data["current"] == -raw_data["current"]
    assert result.data["power"] == -raw_data["power"]


async def test_invert_current_sign_disabled_keeps_raw_sign(
    hass: HomeAssistant, sample_response: dict[str, Any]
) -> None:
    coordinator = _make_coordinator(hass, invert_current_sign=False)
    raw_data = FLB48314TG1H_PROFILE.parse(sample_response)

    with (
        patch(API_PATH, AsyncMock(return_value=sample_response)),
        patch(TZ_PATH, AsyncMock(return_value=None)),
    ):
        result = await coordinator._async_update_data()

    assert result.data["current"] == raw_data["current"]
    assert result.data["power"] == raw_data["power"]


async def test_invert_current_sign_is_null_safe(
    hass: HomeAssistant, sample_response: dict[str, Any]
) -> None:
    coordinator = _make_coordinator(hass)
    modified = {**sample_response, "BattList": [[54040, 65535], [-1, -1]]}

    with (
        patch(API_PATH, AsyncMock(return_value=modified)),
        patch(TZ_PATH, AsyncMock(return_value=None)),
    ):
        result = await coordinator._async_update_data()

    assert result.data["current"] is None
    assert result.data["power"] is None


async def test_unrecognized_model_raises_repair_issue(
    hass: HomeAssistant, sample_response: dict[str, Any]
) -> None:
    coordinator = _make_coordinator(hass)
    unknown = {**sample_response, "SubType": 9999}

    with (
        patch(API_PATH, AsyncMock(return_value=unknown)),
        patch(TZ_PATH, AsyncMock(return_value=None)),
    ):
        result = await coordinator._async_update_data()

    assert result.profile.is_generic
    issue = ir.async_get(hass).async_get_issue(DOMAIN, "unrecognized_model_112_9999")
    assert issue is not None
    assert issue.translation_key == "unrecognized_model"
    assert issue.translation_placeholders == {"type": "112", "subtype": "9999"}
    # Blank issue with the model codes in the title - not the battery_profile.yml form,
    # since the user attaches a diagnostics file rather than filling in fields.
    assert issue.learn_more_url is not None
    query = urllib.parse.parse_qs(urllib.parse.urlparse(issue.learn_more_url).query)
    assert "template" not in query
    assert query["title"] == ["[Battery profile] <model> (Type=112, SubType=9999)"]
    assert "192.168.1.50" not in issue.learn_more_url


async def test_recognized_model_raises_no_repair_issue(
    hass: HomeAssistant, sample_response: dict[str, Any]
) -> None:
    coordinator = _make_coordinator(hass)

    with (
        patch(API_PATH, AsyncMock(return_value=sample_response)),
        patch(TZ_PATH, AsyncMock(return_value=None)),
    ):
        await coordinator._async_update_data()

    assert not [
        issue_id for (domain, issue_id) in ir.async_get(hass).issues if domain == DOMAIN
    ]


async def test_repair_issue_cleared_once_model_is_recognized(
    hass: HomeAssistant, sample_response: dict[str, Any]
) -> None:
    coordinator = _make_coordinator(hass)
    issue_id = f"unrecognized_model_{sample_response['Type']}_{sample_response['SubType']}"

    # Simulate an older release that didn't know this model yet.
    with (
        patch(API_PATH, AsyncMock(return_value=sample_response)),
        patch(TZ_PATH, AsyncMock(return_value=None)),
        patch.object(profiles, "PROFILES", ()),
    ):
        await coordinator._async_update_data()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None

    fresh = _make_coordinator(hass)
    with (
        patch(API_PATH, AsyncMock(return_value=sample_response)),
        patch(TZ_PATH, AsyncMock(return_value=None)),
    ):
        await fresh._async_update_data()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_repair_issue_not_recreated_on_every_poll(
    hass: HomeAssistant, sample_response: dict[str, Any]
) -> None:
    coordinator = _make_coordinator(hass)
    unknown = {**sample_response, "SubType": 9999}

    with (
        patch(API_PATH, AsyncMock(return_value=unknown)),
        patch(TZ_PATH, AsyncMock(return_value=None)),
        patch(
            "custom_components.felicity_solar_local.coordinator.ir.async_create_issue"
        ) as create_issue,
    ):
        for _ in range(3):
            await coordinator._async_update_data()

    assert create_issue.call_count == 1
