"""Battery model profiles: field mapping/scaling per Felicity Solar battery model.

The local WiFi protocol (see api.py) returns the same *shape* of JSON across the Felicity
battery family, but exact scaling/meaning has been verified against real hardware for three
models: the FLB48314TG1-H (Type=112, SubType=7353), cross-checked field-by-field against the
same battery's readings from Felicity's cloud API; the FLA24100 (Type=112, SubType=6100),
whose temperature mapping was cross-checked live against the vendor app; and the FLA48300
(Type=112, SubType=7300), cross-checked live against the vendor app. See the project README
for the full verification table.

Profiles are looked up by the device's self-reported ``Type``/``SubType`` codes, so adding
support for another verified model later is a matter of adding one more ``BatteryProfile``
to ``PROFILES`` - no changes needed in coordinator.py or sensor.py.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import homeassistant.util.dt as dt_util
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.helpers.entity import EntityCategory

# Sentinel values the firmware uses to mean "this channel is not populated".
_SENTINELS = (None, 65535, -1, 32767)

CELL_COUNT = 16


def _path(data: dict[str, Any], key: str, row: int, col: int) -> Any:
    """Safely pull data[key][row][col], returning None if missing/short/wrong shape."""
    try:
        value = data[key][row][col]
    except (KeyError, IndexError, TypeError):
        return None
    return None if value in _SENTINELS else value


def _scaled(data: dict[str, Any], key: str, row: int, col: int, divisor: float) -> float | None:
    value = _path(data, key, row, col)
    if value is None:
        return None
    return round(value / divisor, 3)


def _raw(data: dict[str, Any], key: str) -> Any:
    value = data.get(key)
    return None if value in _SENTINELS else value


# Bstate bitmask flags. Bit 14 (heating) is a separate flag and intentionally not
# decoded here.
_BSTATE_DISCHARGING_BIT = 1 << 12
_BSTATE_CHARGING_BIT = 1 << 13


def _charging_state(bstate: Any) -> str | None:
    """Decode charging/discharging/standby from the Bstate bitmask register.

    Bit 13 set -> charging. Bit 12 set (with bit 13 clear) -> discharging. Neither set ->
    standby. Returns None if Bstate itself is missing/sentinel (see _raw()).
    """
    if not isinstance(bstate, int):
        return None
    if bstate & _BSTATE_CHARGING_BIT:
        return "charging"
    if bstate & _BSTATE_DISCHARGING_BIT:
        return "discharging"
    return "standby"


def _device_timestamp(raw: dict[str, Any]) -> datetime | None:
    """Parse the device's self-reported ``date`` field (``YYYYMMDDHHMMSS``, e.g.

    ``"20260712121556"``). The main query carries no timezone for this field, so the
    coordinator separately queries ``wifilocalMonitor:get Date`` once (not every poll)
    for the device's actual UTC offset (its ``timeZMin`` field) and merges it into
    ``raw`` as ``timeZMin`` before calling parse() - see coordinator.py. Falls back to
    Home Assistant's configured timezone if that offset isn't available (e.g. the
    separate query hasn't succeeded yet).
    """
    date_value = raw.get("date")
    if not isinstance(date_value, str) or len(date_value) != 14 or not date_value.isdigit():
        return None
    try:
        naive = datetime.strptime(date_value, "%Y%m%d%H%M%S")
    except ValueError:
        return None

    offset_minutes = raw.get("timeZMin")
    tzinfo = (
        timezone(timedelta(minutes=offset_minutes))
        if isinstance(offset_minutes, int)
        else dt_util.DEFAULT_TIME_ZONE
    )
    return naive.replace(tzinfo=tzinfo)


def parse_common(raw: dict[str, Any]) -> dict[str, Any]:
    """Parse the fields verified against the FLB48314TG1-H.

    Primary sensors are sourced from this pack's own per-pack readings (the ``*List``
    fields, ``BLVolCu``, ``BMaxMin``, ``BTemp``) rather than the ``Batt``/``Batsoc``/
    ``LVolCur`` bank-level aggregates, whose exact combination semantics (e.g. current
    doesn't cleanly sum/double the way voltage and static limits do) weren't fully
    resolved during live validation.

    ``BmsCnt`` (charge cycle count) is only present on newer firmware - see issue #42,
    where it was confirmed against the vendor app on a battery running the latest
    firmware. Older firmware simply omits the key, so ``cycle_count`` reads as
    unavailable there rather than wrong.
    """
    voltage = _scaled(raw, "BattList", 0, 0, 1000)
    current = _scaled(raw, "BattList", 1, 0, 10)
    bstate = _raw(raw, "Bstate")
    temperature_1 = _scaled(raw, "BTemp", 0, 0, 10)
    temperature_2 = _scaled(raw, "BTemp", 0, 1, 10)
    temperature_3 = _scaled(raw, "BTemp", 1, 0, 10)
    temperature_4 = _scaled(raw, "BTemp", 1, 1, 10)
    temperatures = [
        t for t in (temperature_1, temperature_2, temperature_3, temperature_4) if t is not None
    ]

    data: dict[str, Any] = {
        "voltage": voltage,
        "current": current,
        "power": round(voltage * current, 2) if voltage is not None and current is not None else None,
        "charging_state": _charging_state(bstate),
        "soc": _scaled(raw, "BatsocList", 0, 0, 100),
        "soh": _scaled(raw, "BatsocList", 0, 1, 10),
        "capacity": _scaled(raw, "BatsocList", 0, 2, 1000),
        "cycle_count": _raw(raw, "BmsCnt"),
        "max_cell_voltage": _scaled(raw, "BMaxMin", 0, 0, 1000),
        "min_cell_voltage": _scaled(raw, "BMaxMin", 0, 1, 1000),
        "max_cell_number": _path(raw, "BMaxMin", 1, 0),
        "min_cell_number": _path(raw, "BMaxMin", 1, 1),
        "temperature_1": temperature_1,
        "temperature_2": temperature_2,
        "temperature_3": temperature_3,
        "temperature_4": temperature_4,
        "temperature_max": max(temperatures) if temperatures else None,
        "temperature_min": min(temperatures) if temperatures else None,
        "charge_voltage_limit": _scaled(raw, "BLVolCu", 0, 0, 10),
        "discharge_voltage_limit": _scaled(raw, "BLVolCu", 0, 1, 10),
        "charge_current_limit": _scaled(raw, "BLVolCu", 1, 0, 10),
        "discharge_current_limit": _scaled(raw, "BLVolCu", 1, 1, 10),
        "serial_number": _raw(raw, "DevSN"),
        "device_timestamp": _device_timestamp(raw),
        "estate": _raw(raw, "Estate"),
        "state": bstate,
        "fault": _raw(raw, "Bfault"),
        "warning": _raw(raw, "Bwarn"),
        "bms_fault": _raw(raw, "BBfault"),
        "bms_warning": _raw(raw, "BBwarn"),
    }

    for i in range(CELL_COUNT):
        data[f"cell_{i + 1}_voltage"] = _scaled(raw, "BatcelList", 0, i, 1000)

    return data


def parse_fla24100(raw: dict[str, Any]) -> dict[str, Any]:
    """Parse for the FLA24100 (Type=112, SubType=6100) - a 24 V, 8-cell pack.

    Identical to ``parse_common`` except for the temperature mapping. On this model
    ``BTemp[1]`` is not a temperature pair: the only values observed on these battery readings
    are 256 to 259 and 512, this field doesn't follow ambient changes like the app values.
    The vendor app shows 26°C while the scaling of ``BTemp[1][1] == 512`` produced 51.2°C.
    The actual probes are the first four ``BtemList`` slots.
    Unpopulated slots hold the usual 32767/65535 sentinels, which ``_path`` already filters out).
    """
    data = parse_common(raw)
    temperatures: list[float] = []
    for i in range(4):
        value = _scaled(raw, "BtemList", 0, i, 10)
        data[f"temperature_{i + 1}"] = value
        if value is not None:
            temperatures.append(value)
    data["temperature_max"] = max(temperatures) if temperatures else None
    data["temperature_min"] = min(temperatures) if temperatures else None
    return data


_DIAGNOSTIC_INT_SENSORS: tuple[SensorEntityDescription, ...] = tuple(
    SensorEntityDescription(
        key=key,
        translation_key=key,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    )
    for key in ("estate", "state", "fault", "warning", "bms_fault", "bms_warning")
)

_COMMON_SENSORS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="voltage",
        translation_key="voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="current",
        translation_key="current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="power",
        translation_key="power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="charging_state",
        translation_key="charging_state",
        device_class=SensorDeviceClass.ENUM,
        options=["charging", "discharging", "standby"],
    ),
    SensorEntityDescription(
        key="soc",
        translation_key="soc",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="soh",
        translation_key="soh",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="capacity",
        translation_key="capacity",
        native_unit_of_measurement="Ah",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="cycle_count",
        translation_key="cycle_count",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="max_cell_voltage",
        translation_key="max_cell_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="min_cell_voltage",
        translation_key="min_cell_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="max_cell_number",
        translation_key="max_cell_number",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    SensorEntityDescription(
        key="min_cell_number",
        translation_key="min_cell_number",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    SensorEntityDescription(
        key="temperature_max",
        translation_key="temperature_max",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="temperature_min",
        translation_key="temperature_min",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    *(
        SensorEntityDescription(
            key=f"temperature_{i + 1}",
            translation_key="temperature",
            translation_placeholders={"index": str(i + 1)},
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
            entity_registry_enabled_default=False,
        )
        for i in range(4)
    ),
    SensorEntityDescription(
        key="charge_voltage_limit",
        translation_key="charge_voltage_limit",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    SensorEntityDescription(
        key="discharge_voltage_limit",
        translation_key="discharge_voltage_limit",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    SensorEntityDescription(
        key="charge_current_limit",
        translation_key="charge_current_limit",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    SensorEntityDescription(
        key="discharge_current_limit",
        translation_key="discharge_current_limit",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    SensorEntityDescription(
        key="serial_number",
        translation_key="serial_number",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="device_timestamp",
        translation_key="device_timestamp",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    *(
        SensorEntityDescription(
            key=f"cell_{i + 1}_voltage",
            translation_key="cell_voltage",
            translation_placeholders={"index": str(i + 1)},
            device_class=SensorDeviceClass.VOLTAGE,
            native_unit_of_measurement=UnitOfElectricPotential.VOLT,
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=3,
            entity_category=EntityCategory.DIAGNOSTIC,
            entity_registry_enabled_default=False,
        )
        for i in range(CELL_COUNT)
    ),
    *_DIAGNOSTIC_INT_SENSORS,
)


@dataclass(frozen=True)
class BatteryProfile:
    """A named field mapping for one Felicity Solar battery model."""

    name: str
    confidence: str  # "verified" (checked against real hardware) or "best_effort"
    type_code: int | None
    subtype_code: int | None
    sensors: tuple[SensorEntityDescription, ...] = _COMMON_SENSORS
    parse: Callable[[dict[str, Any]], dict[str, Any]] = field(default=parse_common)

    def matches(self, raw: dict[str, Any]) -> bool:
        """Return True if this profile applies to the given raw response."""
        if self.type_code is None:
            return True
        return raw.get("Type") == self.type_code and raw.get("SubType") == self.subtype_code


FLB48314TG1H_PROFILE = BatteryProfile(
    name="FLB48314TG1-H",
    confidence="verified",
    type_code=112,
    subtype_code=7353,
)

FLA24100_PROFILE = BatteryProfile(
    name="FLA24100",
    confidence="verified",
    type_code=112,
    subtype_code=6100,
    parse=parse_fla24100,
)

# Reported in issue #42, where the field shape/scaling was cross-checked live against the
# vendor app (including BmsCnt/cycle_count, added above) and confirmed 100% correct.
FLA48300_PROFILE = BatteryProfile(
    name="FLA48300",
    confidence="verified",
    type_code=112,
    subtype_code=7300,
)

# Fallback for any Felicity battery reporting a Type/SubType we haven't verified yet.
# Same field shape/scaling as the verified profile (the protocol is believed to be shared
# across the Felicity WiFi-battery family) but not confirmed against real hardware - treat
# these values as best-effort and always check the raw_data diagnostic sensor.
DEFAULT_PROFILE = BatteryProfile(
    name="Generic Felicity Solar Battery",
    confidence="best_effort",
    type_code=None,
    subtype_code=None,
)

PROFILES: tuple[BatteryProfile, ...] = (FLB48314TG1H_PROFILE, FLA24100_PROFILE, FLA48300_PROFILE)


def select_profile(raw: dict[str, Any]) -> BatteryProfile:
    """Pick the best matching profile for a raw device response."""
    for profile in PROFILES:
        if profile.matches(raw):
            return profile
    return DEFAULT_PROFILE
