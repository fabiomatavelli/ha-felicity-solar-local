"""Battery model profiles: field mapping/scaling per Felicity Solar battery model.

The local WiFi protocol (see api.py) returns the same *shape* of JSON across the Felicity
battery family, but exact scaling/meaning is only trusted once verified against real hardware.
The reference model is the FLB48314TG1-H (Type=112, SubType=7353), cross-checked
field-by-field against the same battery's readings from Felicity's cloud API; every other
verified model, with the issue it was reported in and its caveats, is listed in the project
README's "Battery model support" table.

Profiles are looked up by the device's self-reported ``Type``/``SubType`` codes, so adding
support for another verified model later is a matter of adding one more ``BatteryProfile``
to ``PROFILES`` - no changes needed in coordinator.py or sensor.py.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
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
    except KeyError, IndexError, TypeError:
        return None
    return None if value in _SENTINELS else value


def _cell_number(data: dict[str, Any], col: int) -> int | None:
    """1-based cell number from BMaxMin[1][col], matching the cell_N_voltage sensors.

    The battery reports the max/min cell as a 0-based index into BatcelList.
    """
    value = _path(data, "BMaxMin", 1, col)
    return None if value is None else value + 1


def _scaled(data: dict[str, Any], key: str, row: int, col: int, divisor: float) -> float | None:
    value = _path(data, key, row, col)
    if value is None:
        return None
    return round(value / divisor, 3)


def _raw(data: dict[str, Any], key: str) -> Any:
    value = data.get(key)
    return None if value in _SENTINELS else value


# Sensors backed by a field only some firmware versions send (see parse_common()). sensor.py
# only creates these when the first reading actually carries a value, rather than leaving an
# entity stuck at "unknown" forever on firmware that never reports it.
FIRMWARE_DEPENDENT_SENSORS = frozenset({"cycle_count"})


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


# Firmware version fields from the basic-info query (see const.BASIC_INFO_QUERY_COMMAND),
# with the label each gets in the device's software version. "version" is the WiFi
# module's own firmware; M1/M2/D are the device's firmware slots as the payload names them.
_FIRMWARE_FIELDS = (("M1SwVer", "M1"), ("M2SwVer", "M2"), ("DSwVer", "D"), ("version", "WiFi"))


def firmware_version(basic_info: dict[str, Any] | None) -> str | None:
    """Summarize the basic-info payload's firmware versions, e.g. ``M1 203, M2 8, WiFi 2.10``.

    Unpopulated slots (65535 etc.) are left out; None if no version is known at all.
    """
    if not basic_info:
        return None
    parts = [
        f"{label} {value}"
        for key, label in _FIRMWARE_FIELDS
        if (value := _raw(basic_info, key)) is not None and value != ""
    ]
    return ", ".join(parts) or None


def parse_common(raw: dict[str, Any]) -> dict[str, Any]:
    """Parse the fields verified against the FLB48314TG1-H.

    Primary sensors are sourced from this pack's own per-pack readings (the ``*List``
    fields, ``BLVolCu``, ``BMaxMin``) rather than the ``Batt``/``Batsoc``/``LVolCur``
    bank-level aggregates, whose exact combination semantics (e.g. current doesn't cleanly
    sum/double the way voltage and static limits do) weren't fully resolved during live
    validation.

    Temperatures come from the first four ``BtemList`` slots, the pack's own probes, which
    matched the vendor app on every model cross-checked so far. ``BTemp`` is not used: it
    behaves like another bank-level aggregate. In every capture so far ``BTemp[0]`` holds
    the bank's max/min temperature (two packs at 23 and 24 °C both reported ``[240, 230]``),
    and ``BTemp[1]`` is not a temperature at all but where those extremes are (the pack's
    ``modID`` in the high byte, the probe in the low byte, e.g. 512 = pack 2, probe 0),
    which reads as a bogus 25.6 to 76.9 °C once scaled. Unpopulated ``BtemList`` slots hold
    the usual 32767/65535 sentinels, which ``_path`` already filters out.

    ``capacity`` (``BatsocList[0][2]``) is the capacity the BMS reports, not necessarily
    the nameplate rating. It matches the capacity class the ``SubType`` seems to encode
    (7353 -> 350 Ah, 7500 -> 500 Ah, 7204 -> 200 Ah, and likewise for 7100, 7250, 7300
    and 6100), which can be larger than the model's nameplate: the 314 Ah FLB48314TG1-H
    reports 350 Ah. There's no nameplate field in the payload to use instead.

    ``BmsCnt`` (charge cycle count) is only present on newer firmware - see issue #42,
    where it was confirmed against the vendor app on a battery running the latest
    firmware. Older firmware simply omits the key (issue #58), so ``cycle_count`` parses
    as None there rather than wrong - and see ``FIRMWARE_DEPENDENT_SENSORS``.
    """
    voltage = _scaled(raw, "BattList", 0, 0, 1000)
    current = _scaled(raw, "BattList", 1, 0, 10)
    bstate = _raw(raw, "Bstate")
    probes = [_scaled(raw, "BtemList", 0, i, 10) for i in range(4)]
    temperatures = [t for t in probes if t is not None]

    data: dict[str, Any] = {
        "voltage": voltage,
        "current": current,
        "power": round(voltage * current, 2)
        if voltage is not None and current is not None
        else None,
        "charging_state": _charging_state(bstate),
        "soc": _scaled(raw, "BatsocList", 0, 0, 100),
        "soh": _scaled(raw, "BatsocList", 0, 1, 10),
        "capacity": _scaled(raw, "BatsocList", 0, 2, 1000),
        "cycle_count": _raw(raw, "BmsCnt"),
        "max_cell_voltage": _scaled(raw, "BMaxMin", 0, 0, 1000),
        "min_cell_voltage": _scaled(raw, "BMaxMin", 0, 1, 1000),
        "max_cell_number": _cell_number(raw, 0),
        "min_cell_number": _cell_number(raw, 1),
        "temperature_1": probes[0],
        "temperature_2": probes[1],
        "temperature_3": probes[2],
        "temperature_4": probes[3],
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
    # Disabled by default: it changes on every poll, so it would write a new state to the
    # recorder every few seconds for little day-to-day use.
    SensorEntityDescription(
        key="device_timestamp",
        translation_key="device_timestamp",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
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

    @property
    def is_generic(self) -> bool:
        """True for the catch-all fallback used when no model-specific profile matches."""
        return self.type_code is None

    def matches(self, raw: dict[str, Any]) -> bool:
        """Return True if this profile applies to the given raw response."""
        if self.type_code is None:
            return True
        return raw.get("Type") == self.type_code and raw.get("SubType") == self.subtype_code


# A 24 V, 8-cell pack. BTemp[1] only ever reported 256 to 259 and 512 and didn't follow
# ambient changes: the vendor app showed 26 °C where BTemp[1][1] == 512 scaled to 51.2 °C.
# The BtemList temperature mapping was cross-checked live against the vendor app.
FLA24100_PROFILE = BatteryProfile(
    name="FLA24100",
    confidence="verified",
    type_code=112,
    subtype_code=6100,
)

# Reported in issue #103: a 24 V/460 Ah, 8-cell pack. BTemp[1] reported [256, 258] (a bogus
# 25.8 °C max) while the vendor app showed 33 °C, matching BtemList. Voltage, current, SOC,
# limits, cell voltages and the BtemList temperature mapping were cross-checked against the
# vendor app. Its firmware (M1 522) doesn't send BmsCnt, so cycle_count stays unavailable.
# Known caveat (same as the FLA48460TG2): BatsocList[0][2] (capacity) reads 500000
# (500.0 Ah), the BMS-reported capacity, while the vendor app and nameplate say 460 Ah.
FLA24460_EU_PROFILE = BatteryProfile(
    name="FLA24460-EU",
    confidence="verified",
    type_code=112,
    subtype_code=6500,
)

# Reported in issue #69: a 51.2 V/171 Ah, 16-cell pack. BTemp[1] reported [256, 256] (a
# bogus 25.6 °C max) while the vendor app showed 20 °C, matching BtemList. Voltage, current,
# SOC, cycle count, limits, max/min cell and the BtemList temperature mapping were
# cross-checked against the vendor app.
# Known caveat (same as the FLA48460TG2): BatsocList[0][2] (capacity) reads 200000
# (200.0 Ah), the BMS-reported capacity, while the vendor app and nameplate say 171 Ah.
FLA48171_EU_PROFILE = BatteryProfile(
    name="FLA48171-EU",
    confidence="verified",
    type_code=112,
    subtype_code=7204,
)

# Reported in issue #42 as an FLA48300; the reporter later confirmed the label model is
# LUX-Y-48300LG01. The field shape/scaling was cross-checked live against the vendor app
# (including BmsCnt/cycle_count, added above) and confirmed 100% correct.
FLA48300_PROFILE = BatteryProfile(
    name="LUX-Y-48300LG01",
    confidence="verified",
    type_code=112,
    subtype_code=7300,
)

# Reported in issue #50: a 48 V, 16-cell pack. BTemp[1] reports a fixed 256/257 regardless
# of the actual temperature (same issue as the FLA24100); the BtemList temperature mapping
# was cross-checked live against the vendor app and confirmed correct.
# Known caveat: BatsocList[0][2] (capacity) reads 500000 (500.0 Ah) against the 460 Ah
# nameplate: the BMS reports the capacity class of its SubType (500 Ah for 7500), not the
# nameplate rating; see parse_common().
FLA48460TG2_PROFILE = BatteryProfile(
    name="FLA48460TG2 (GT2)",
    confidence="verified",
    type_code=112,
    subtype_code=7500,
)

# The reference model. On firmware M1 203, two packs in one bank both reported BTemp
# [[240, 230], [512, 256]] (a bogus 51.2 °C max under the old BTemp mapping) while the vendor
# app showed 23 °C and 24 °C, matching each pack's own BtemList.
FLB48314TG1H_PROFILE = BatteryProfile(
    name="FLB48314TG1-H",
    confidence="verified",
    type_code=112,
    subtype_code=7353,
)

# Reported in issue #59 (Felicity LUX-E series): a 48 V/100 Ah, 16-cell pack. BTemp[1]
# reported [769, 256] (a bogus 76.9 °C max) while the vendor app showed 20-21 °C, matching
# BtemList. Voltage, current, SOC and the BtemList temperature mapping were cross-checked
# against the vendor app.
LUX_E_48100LG03_PROFILE = BatteryProfile(
    name="LUX-E-48100LG03",
    confidence="verified",
    type_code=112,
    subtype_code=7100,
)

# Reported in issue #73 (Felicity LUX-E series): a 48 V/250 Ah, 16-cell pack. BTemp[1] reported
# [256, 256] (a bogus 25.6 °C max) while the vendor app showed 20 °C on all four probes,
# matching BtemList. Voltage, current, SOC, capacity, limits, cell voltages, charging state
# and the BtemList temperature mapping were cross-checked against the vendor app. Its
# firmware (M1 519) doesn't send BmsCnt, so cycle_count stays unavailable.
LUX_E_48250LG03_PROFILE = BatteryProfile(
    name="LUX-E-48250LG03",
    confidence="verified",
    type_code=112,
    subtype_code=7250,
)


# Felicity LUX-Y-48100 high-voltage stack (five modules observed).
# Type=119, SubType=201, cross-checked against Felicity Shine and local
# observations. This is a BEST-EFFORT / PARTIAL mapping, not a full 80-cell
# bank monitor or a source for charging/discharging safety decisions.
#
# The payload layout differs from the Type=112 low-voltage profiles; see
# tests/fixtures/lux_y_48100hg01_response.json for a real payload.
def _hv119_location(
    raw: dict[str, Any], key: str, col: int, *, max_position: int
) -> tuple[int, int] | None:
    """Decode packed Type 119/201 module and cell/probe position.

    The high byte is the zero-based module index, the low byte is the
    zero-based cell/probe index. Codes 12 and 258 are 1/13 and 2/3.
    Confirmed against Felicity Shine on 2026-11-13: BTemp[1] codes
    1 and 769 correspond to Module 1 / Probe 2 and Module 4 / Probe 2.
    """
    code = _path(raw, key, 1, col)
    if type(code) is not int or not 0 <= code <= 65534:
        return None
    module_index, within_module_index = divmod(code, 256)
    if module_index >= 5 or within_module_index >= max_position:
        return None
    return module_index + 1, within_module_index + 1


def parse_lux_y_48100hg01(raw: dict[str, Any]) -> dict[str, Any]:
    """Best-effort HV local bank extrema and one partial 16-cell sample.

    There are five 16-cell modules, but BatcelList[1] in the observed
    local response exposes only 16 individual values, not all 80.
    """
    if raw.get("Type") != 119 or raw.get("SubType") != 201:
        raise ValueError("LUX-Y HV profile requires Type=119, SubType=201")
    data = parse_common(raw)

    maximum = _scaled(raw, "BTemp", 0, 0, 10)
    minimum = _scaled(raw, "BTemp", 0, 1, 10)
    data["temperature_max"] = maximum
    data["temperature_min"] = minimum
    # BtemList contains unrelated fields for the HV model.
    for i in range(4):
        data[f"temperature_{i + 1}"] = None

    for label, col in (("max", 0), ("min", 1)):
        location = (
            _hv119_location(raw, "BTemp", col, max_position=4)
            if (maximum if label == "max" else minimum) is not None
            else None
        )
        data[f"temperature_{label}_module"] = location[0] if location else None
        data[f"temperature_{label}_probe"] = location[1] if location else None

    # Operator confirmed BatcelList[0][0:5] as five physical module voltages.
    # Do not infer cell-by-cell telemetry for modules 2..5 from this row.
    for i in range(5):
        voltage = _scaled(raw, "BatcelList", 0, i, 100)
        data[f"hv_module_{i + 1}_voltage"] = voltage

    for i in range(CELL_COUNT):
        value = _scaled(raw, "BatcelList", 1, i, 1000)
        data[f"cell_{i + 1}_voltage"] = value

    maximum_cell = _scaled(raw, "BMaxMin", 0, 0, 1000)
    minimum_cell = _scaled(raw, "BMaxMin", 0, 1, 1000)
    data["max_cell_voltage"] = maximum_cell
    data["min_cell_voltage"] = minimum_cell
    for label, col in (("max", 0), ("min", 1)):
        location = (
            _hv119_location(raw, "BMaxMin", col, max_position=16)
            if (maximum_cell if label == "max" else minimum_cell) is not None
            else None
        )
        data[f"{label}_cell_module"] = location[0] if location else None
        data[f"{label}_cell_index"] = location[1] if location else None
        # The legacy cell-number sensor expects the same absolute bank-wide
        # ordinal for every model; flatten the module-major 5x16 positions.
        data[f"{label}_cell_number"] = (location[0] - 1) * 16 + location[1] if location else None

    # The reported 100 A in BLVolCu is not a verified continuous safe limit.
    data["charge_current_limit"] = None
    data["discharge_current_limit"] = None
    return data


_HV_119_201_MODULE_SENSORS: tuple[SensorEntityDescription, ...] = tuple(
    SensorEntityDescription(
        key=f"hv_module_{i}_voltage",
        translation_key="hv_module_voltage",
        translation_placeholders={"index": str(i)},
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
    )
    for i in range(1, 6)
)

_HV_119_201_POSITION_SENSORS: tuple[SensorEntityDescription, ...] = tuple(
    SensorEntityDescription(
        key=f"{prefix}_{suffix}",
        translation_key=f"{prefix}_{suffix}",
        entity_category=EntityCategory.DIAGNOSTIC,
    )
    for prefix, suffixes in (
        ("max_cell", ("module", "index")),
        ("min_cell", ("module", "index")),
        ("temperature_max", ("module", "probe")),
        ("temperature_min", ("module", "probe")),
    )
    for suffix in suffixes
)

# Preserve the stable cell_N_voltage entity keys while making clear that they
# describe module 1's 16 cells, not every cell across the entire HV stack.
_HV_119_201_CELL_SENSORS: tuple[SensorEntityDescription, ...] = tuple(
    replace(
        desc,
        translation_key="module_1_cell_voltage",
    )
    if desc.key.startswith("cell_") and desc.key.endswith("_voltage")
    else desc
    for desc in _COMMON_SENSORS
    if desc.key
    not in {
        "charge_current_limit",
        "discharge_current_limit",
        *(f"temperature_{i}" for i in range(1, 5)),
    }
)


LUX_Y_48100HG01_PROFILE = BatteryProfile(
    name="LUX-Y-48100HG01",
    confidence="best_effort",
    type_code=119,
    subtype_code=201,
    sensors=_HV_119_201_CELL_SENSORS + _HV_119_201_POSITION_SENSORS + _HV_119_201_MODULE_SENSORS,
    parse=parse_lux_y_48100hg01,
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

PROFILES: tuple[BatteryProfile, ...] = (
    FLA24100_PROFILE,
    FLA24460_EU_PROFILE,
    FLA48171_EU_PROFILE,
    FLA48300_PROFILE,
    FLA48460TG2_PROFILE,
    FLB48314TG1H_PROFILE,
    LUX_E_48100LG03_PROFILE,
    LUX_E_48250LG03_PROFILE,
    LUX_Y_48100HG01_PROFILE,
)


# Keys only Felicity *inverters* send on the same port (issue #64: a Type=81 three-phase
# hybrid inverter), versus the per-pack keys every supported battery sends.
_INVERTER_KEYS = ("ACin", "ACout", "PV", "pFlow", "busVp")
_BATTERY_PACK_KEYS = ("BattList", "BatsocList")


def is_inverter_payload(raw: dict[str, Any]) -> bool:
    """True if the response comes from a Felicity inverter rather than a battery.

    Inverters answer the same local query with AC/PV/bus fields and no per-pack battery
    fields, so every battery sensor would parse as None - no battery profile can fix that.
    """
    if any(key in raw for key in _BATTERY_PACK_KEYS):
        return False
    return any(key in raw for key in _INVERTER_KEYS)


def select_profile(raw: dict[str, Any]) -> BatteryProfile:
    """Pick the best matching profile for a raw device response."""
    for profile in PROFILES:
        if profile.matches(raw):
            return profile
    return DEFAULT_PROFILE
