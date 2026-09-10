"""Tests for battery profile matching and field parsing/scaling."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import homeassistant.util.dt as dt_util
import pytest

from custom_components.felicity_solar_local.profiles import (
    DEFAULT_PROFILE,
    FLA24100_PROFILE,
    FLA48300_PROFILE,
    FLB48314TG1H_PROFILE,
    select_profile,
)


def test_select_profile_matches_flb48314tg1h(sample_response: dict[str, Any]) -> None:
    assert select_profile(sample_response) is FLB48314TG1H_PROFILE


def test_select_profile_falls_back_to_default_for_unknown_model(
    sample_response: dict[str, Any],
) -> None:
    unknown = {**sample_response, "Type": 999, "SubType": 1}
    assert select_profile(unknown) is DEFAULT_PROFILE


def test_parse_scales_verified_fields_correctly(sample_response: dict[str, Any]) -> None:
    data = FLB48314TG1H_PROFILE.parse(sample_response)

    assert data["voltage"] == 54.04
    assert data["current"] == 34.2
    assert data["power"] == round(54.04 * 34.2, 2)
    assert data["soc"] == 96.0
    assert data["soh"] == 100.0
    assert data["capacity"] == 350.0
    assert data["cycle_count"] is None
    assert data["max_cell_voltage"] == 3.38
    assert data["min_cell_voltage"] == 3.376
    assert data["max_cell_number"] == 8
    assert data["min_cell_number"] == 0
    assert data["temperature_1"] == 26.0
    assert data["temperature_2"] == 26.0
    assert data["temperature_3"] == 25.6
    assert data["temperature_4"] == 25.6
    assert data["temperature_max"] == 26.0
    assert data["temperature_min"] == 25.6
    assert data["charge_voltage_limit"] == 57.6
    assert data["discharge_voltage_limit"] == 48.0
    assert data["charge_current_limit"] == 32.0
    assert data["discharge_current_limit"] == 160.0
    assert data["serial_number"] == "075704831426060274"
    assert data["fault"] == 0
    assert data["warning"] == 0


def test_parse_extracts_all_16_cell_voltages(sample_response: dict[str, Any]) -> None:
    data = FLB48314TG1H_PROFILE.parse(sample_response)

    for i in range(16):
        assert data[f"cell_{i + 1}_voltage"] is not None

    assert data["cell_1_voltage"] == 3.376
    assert data["cell_9_voltage"] == 3.38  # matches BMaxMin's reported max


def test_parse_is_null_safe(sample_response: dict[str, Any]) -> None:
    # Batt[2][0] is observed as a JSON null on real hardware; parsing must not crash
    # even though this profile doesn't currently read from the Batt aggregate field.
    assert sample_response["Batt"][2][0] is None
    data = FLB48314TG1H_PROFILE.parse(sample_response)
    assert data["voltage"] is not None


def test_parse_treats_sentinels_as_missing(sample_response: dict[str, Any]) -> None:
    modified = {**sample_response, "BattList": [[54040, 65535], [-1, -1]]}
    data = FLB48314TG1H_PROFILE.parse(modified)
    assert data["current"] is None


def test_parse_temperature_max_min_are_none_when_all_probes_sentinel(
    sample_response: dict[str, Any],
) -> None:
    modified = {**sample_response, "BTemp": [[65535, 65535], [65535, 65535]]}
    data = FLB48314TG1H_PROFILE.parse(modified)
    assert data["temperature_max"] is None
    assert data["temperature_min"] is None


def test_parse_temperature_max_min_skip_missing_probes(sample_response: dict[str, Any]) -> None:
    modified = {**sample_response, "BTemp": [[260, 65535], [256, 256]]}
    data = FLB48314TG1H_PROFILE.parse(modified)
    assert data["temperature_max"] == 26.0
    assert data["temperature_min"] == 25.6


def test_default_profile_uses_same_shape(sample_response: dict[str, Any]) -> None:
    data = DEFAULT_PROFILE.parse(sample_response)
    assert data["voltage"] == 54.04
    assert DEFAULT_PROFILE.confidence == "best_effort"
    assert FLB48314TG1H_PROFILE.confidence == "verified"


@pytest.mark.parametrize(
    ("bstate", "expected"),
    [
        (320, "standby"),  # bits 6,8 only - neither 12 nor 13 set
        (832, "standby"),  # bits 6,8,9 - neither 12 nor 13 set
        (4416, "discharging"),  # bit 12 set, bit 13 clear
        (4928, "discharging"),
        (5056, "discharging"),
        (9024, "charging"),  # bit 13 set
        (9152, "charging"),  # tests/fixtures/sample_response.json's actual value
        (0, "standby"),
    ],
)
def test_parse_decodes_charging_state_from_bstate_bitmask(
    sample_response: dict[str, Any], bstate: int, expected: str
) -> None:
    modified = {**sample_response, "Bstate": bstate}
    data = FLB48314TG1H_PROFILE.parse(modified)
    assert data["charging_state"] == expected


def test_parse_charging_state_is_none_when_bstate_is_sentinel(
    sample_response: dict[str, Any],
) -> None:
    modified = {**sample_response, "Bstate": 65535}
    data = FLB48314TG1H_PROFILE.parse(modified)
    assert data["state"] is None
    assert data["charging_state"] is None


def test_parse_decodes_device_timestamp(sample_response: dict[str, Any]) -> None:
    # sample_response.json's "date" is "20260712121556".
    data = FLB48314TG1H_PROFILE.parse(sample_response)
    assert data["device_timestamp"] == datetime(
        2026, 7, 12, 12, 15, 56, tzinfo=dt_util.DEFAULT_TIME_ZONE
    )


@pytest.mark.parametrize(
    "date_value",
    [None, "", "not-a-date", "2026071212155", 20260712121556],
)
def test_parse_device_timestamp_is_none_for_missing_or_malformed_date(
    sample_response: dict[str, Any], date_value: Any
) -> None:
    modified = {**sample_response, "date": date_value}
    data = FLB48314TG1H_PROFILE.parse(modified)
    assert data["device_timestamp"] is None


def test_select_profile_matches_fla24100(fla24100_response: dict[str, Any]) -> None:
    assert select_profile(fla24100_response) is FLA24100_PROFILE
    assert FLA24100_PROFILE.confidence == "verified"


def test_fla24100_temperatures_come_from_btemlist_not_btemp(
    fla24100_response: dict[str, Any],
) -> None:
    assert fla24100_response["BTemp"][1] == [256, 512]
    data = FLA24100_PROFILE.parse(fla24100_response)
    assert data["temperature_1"] == 25.0
    assert data["temperature_2"] == 25.0
    assert data["temperature_3"] == 25.0
    assert data["temperature_4"] == 25.0
    assert data["temperature_max"] == 25.0
    assert data["temperature_min"] == 25.0


def test_fla24100_temperature_sentinel_slots_are_missing(
    fla24100_response: dict[str, Any],
) -> None:
    modified = {
        **fla24100_response,
        "BtemList": [[250, 240, 32767, 65535, 32767, 32767, 32767, 32767]],
    }
    data = FLA24100_PROFILE.parse(modified)
    assert data["temperature_1"] == 25.0
    assert data["temperature_2"] == 24.0
    assert data["temperature_3"] is None
    assert data["temperature_4"] is None
    assert data["temperature_max"] == 25.0
    assert data["temperature_min"] == 24.0


def test_fla24100_temperature_max_min_are_none_when_all_probes_sentinel(
    fla24100_response: dict[str, Any],
) -> None:
    modified = {
        **fla24100_response,
        "BtemList": [[32767, 32767, 32767, 32767, 32767, 32767, 32767, 32767]],
    }
    data = FLA24100_PROFILE.parse(modified)
    assert data["temperature_max"] is None
    assert data["temperature_min"] is None


def test_fla24100_core_fields_scale_like_common_profile(
    fla24100_response: dict[str, Any],
) -> None:
    data = FLA24100_PROFILE.parse(fla24100_response)

    assert data["voltage"] == 27.41
    assert data["current"] == 0.0
    assert data["power"] == 0.0
    assert data["soc"] == 100.0
    assert data["soh"] == 100.0
    assert data["capacity"] == 100.0
    assert data["cycle_count"] is None
    assert data["max_cell_voltage"] == 3.429
    assert data["min_cell_voltage"] == 3.415
    assert data["cell_1_voltage"] == 3.428
    assert data["cell_8_voltage"] == 3.429
    assert data["charging_state"] == "standby"
    assert data["warning"] == 4
    assert data["serial_number"] == "074502400000000000"


def test_select_profile_matches_fla48300(fla48300_response: dict[str, Any]) -> None:
    assert select_profile(fla48300_response) is FLA48300_PROFILE
    assert FLA48300_PROFILE.confidence == "verified"


def test_fla48300_uses_common_parsing(fla48300_response: dict[str, Any]) -> None:
    # No custom parse() override - the raw data reported in issue #42 lines up with the
    # common field shape/scaling as-is (capacity matches the "300" in FLA48300, cell
    # voltages/min/max/count all agree), so this profile relies on parse_common directly.
    assert FLA48300_PROFILE.parse is not FLA24100_PROFILE.parse
    data = FLA48300_PROFILE.parse(fla48300_response)

    assert data["voltage"] == 56.16
    assert data["current"] == -0.2
    assert data["power"] == -11.23
    assert data["soc"] == 100.0
    assert data["soh"] == 100.0
    assert data["capacity"] == 300.0
    # Confirmed against the vendor app in issue #42.
    assert data["cycle_count"] == 219
    assert data["max_cell_voltage"] == 3.587
    assert data["min_cell_voltage"] == 3.443
    assert data["max_cell_number"] == 15
    assert data["min_cell_number"] == 8
    assert data["cell_1_voltage"] == 3.569
    assert data["cell_16_voltage"] == 3.587
    assert data["charging_state"] == "standby"
    assert data["warning"] == 4
    assert data["serial_number"] == "072604830025153540"
    assert data["temperature_1"] == 31.0
    assert data["temperature_2"] == 30.0
    assert data["temperature_3"] == 25.6
    assert data["temperature_4"] == 25.7
    assert data["temperature_max"] == 31.0
    assert data["temperature_min"] == 25.6
    assert data["charge_voltage_limit"] == 57.6
    assert data["discharge_voltage_limit"] == 48.0
    assert data["charge_current_limit"] == 0.0
    assert data["discharge_current_limit"] == 150.0
