"""DataUpdateCoordinator for a single Felicity Solar local battery."""

from __future__ import annotations

import logging
import urllib.parse
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import FelicityLocalClient, FelicityLocalError
from .const import DEFAULT_TIMEOUT, DOMAIN, NEW_ISSUE_URL
from .profiles import BatteryProfile, select_profile

_LOGGER = logging.getLogger(__name__)


@dataclass
class FelicityBatteryData:
    """Latest snapshot for a battery: raw response, matched profile, and parsed values."""

    raw: dict[str, Any]
    profile: BatteryProfile
    data: dict[str, Any]


class FelicityLocalCoordinator(DataUpdateCoordinator[FelicityBatteryData]):
    """Coordinator that polls one battery over its local TCP/JSON endpoint."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        host: str,
        port: int,
        update_interval: int,
        persistent_connection: bool = False,
        invert_current_sign: bool = True,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN}_{host}",
            update_interval=timedelta(seconds=update_interval),
        )
        self.host = host
        self.port = port
        self.client = FelicityLocalClient(
            host, port, timeout=DEFAULT_TIMEOUT, persistent=persistent_connection
        )
        self._invert_current_sign = invert_current_sign
        self._tz_offset_minutes: int | None = None
        self._tz_offset_fetched = False
        self._reported_model: tuple[Any, Any] | None = None

    async def _async_update_data(self) -> FelicityBatteryData:
        try:
            raw = await self.client.async_get_data()
        except FelicityLocalError as err:
            raise UpdateFailed(
                f"Error communicating with battery at {self.host}:{self.port}: {err}"
            ) from err

        # The device's own UTC offset rarely changes (only across DST transitions), so
        # this is fetched once per coordinator lifetime rather than every poll - it's a
        # separate command from the main query above, but reuses the same connection in
        # persistent mode (see api.py) rather than opening a second one.
        if not self._tz_offset_fetched:
            self._tz_offset_minutes = await self.client.async_get_timezone_offset_minutes()
            self._tz_offset_fetched = True
        if self._tz_offset_minutes is not None:
            raw = {**raw, "timeZMin": self._tz_offset_minutes}

        profile = select_profile(raw)
        self._report_model(raw, profile)
        data = profile.parse(raw)
        if self._invert_current_sign:
            data = _invert_current_sign(data)
        return FelicityBatteryData(raw=raw, profile=profile, data=data)

    def _report_model(self, raw: dict[str, Any], profile: BatteryProfile) -> None:
        """Raise (or clear) a repair issue asking for an unrecognized model's profile.

        Most people with an unsupported battery already have this integration running on
        the generic fallback profile, so surfacing the request in Home Assistant itself -
        pointing at the diagnostics download, which needs no extra tooling - is what gets
        a complete payload into a profile request. Keyed by Type/SubType rather than config
        entry, so two packs of the same model share one issue.
        """
        model = (raw.get("Type"), raw.get("SubType"))
        if model == self._reported_model:
            return
        if self._reported_model is not None:
            # A different battery now answers on this host (e.g. swapped behind the same
            # IP) - drop the previous model's issue rather than leaving it stale.
            ir.async_delete_issue(self.hass, DOMAIN, _issue_id(self._reported_model))
        self._reported_model = model

        issue_id = _issue_id(model)
        if not profile.is_generic:
            # The issue isn't persistent, so a restart (which updating the integration
            # needs) already clears it; this covers a model becoming recognized within one
            # Home Assistant session.
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)
            return

        ir.async_create_issue(
            self.hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="unrecognized_model",
            translation_placeholders={"type": str(model[0]), "subtype": str(model[1])},
            learn_more_url=profile_request_url(raw),
        )


def _issue_id(model: tuple[Any, Any]) -> str:
    return f"unrecognized_model_{model[0]}_{model[1]}"


def profile_request_url(raw: dict[str, Any]) -> str:
    """Blank GitHub issue link, title prefilled with the model codes, for a profile request.

    Mirrors scripts/probe.py's new_issue_url(), which can't import this module;
    tests/test_probe.py checks the two stay identical.
    """
    title = f"[Battery profile] <model> (Type={raw.get('Type')}, SubType={raw.get('SubType')})"
    return f"{NEW_ISSUE_URL}?{urllib.parse.urlencode({'title': title})}"


def _invert_current_sign(data: dict[str, Any]) -> dict[str, Any]:
    """Flip current/power sign to match Home Assistant's battery convention.

    This battery reports current/power with the opposite sign of what Home Assistant
    expects (negative while charging, positive while discharging) - see const.py's
    DEFAULT_INVERT_CURRENT_SIGN.
    """
    current = data.get("current")
    power = data.get("power")
    return {
        **data,
        "current": -current if current is not None else None,
        "power": -power if power is not None else None,
    }
