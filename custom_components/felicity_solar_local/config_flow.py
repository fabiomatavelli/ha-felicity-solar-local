"""Config flow for the Felicity Solar Local integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .api import (
    FelicityConnectionError,
    FelicityLocalClient,
    FelicityProtocolError,
    FelicityTimeoutError,
)
from .const import (
    CONF_ENABLE_RAW_DATA_SENSOR,
    CONF_HOST,
    CONF_INVERT_CURRENT_SIGN,
    CONF_PERSISTENT_CONNECTION,
    CONF_PORT,
    CONF_UPDATE_INTERVAL,
    DEFAULT_ENABLE_RAW_DATA_SENSOR,
    DEFAULT_INVERT_CURRENT_SIGN,
    DEFAULT_PERSISTENT_CONNECTION,
    DEFAULT_PORT,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    MIN_UPDATE_INTERVAL,
    MIN_UPDATE_INTERVAL_PERSISTENT,
)
from .profiles import is_inverter_payload

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): selector.TextSelector(),
        vol.Required(CONF_PORT, default=DEFAULT_PORT): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=1, max=65535, mode=selector.NumberSelectorMode.BOX
            )
        ),
    }
)


class FelicityLocalConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Felicity Solar Local."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial setup step: host + port."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            port = int(user_input[CONF_PORT])

            client = FelicityLocalClient(host, port)
            try:
                raw = await client.async_get_data()
            except FelicityTimeoutError:
                errors["base"] = "timeout"
            except FelicityConnectionError:
                errors["base"] = "cannot_connect"
            except FelicityProtocolError:
                errors["base"] = "invalid_response"
            except Exception:
                _LOGGER.exception("Unexpected error validating Felicity Solar battery")
                errors["base"] = "unknown"
            else:
                if is_inverter_payload(raw):
                    return self.async_abort(reason="not_a_battery")
                serial_number = raw.get("DevSN")
                unique_id = serial_number or f"{host}:{port}"
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                title = f"Felicity Solar Battery {serial_number or host}"
                return self.async_create_entry(
                    title=title,
                    data={CONF_HOST: host, CONF_PORT: port},
                )
            finally:
                await client.async_close()

        return self.async_show_form(
            step_id="user",
            data_schema=DATA_SCHEMA,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> FelicityLocalOptionsFlow:
        """Get the options flow for this handler."""
        return FelicityLocalOptionsFlow()


class FelicityLocalOptionsFlow(config_entries.OptionsFlow):
    """Handle options for an existing Felicity Solar Local entry."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage the update interval and persistent-connection options."""
        errors: dict[str, str] = {}
        current_interval = self.config_entry.options.get(
            CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
        )
        current_persistent = self.config_entry.options.get(
            CONF_PERSISTENT_CONNECTION, DEFAULT_PERSISTENT_CONNECTION
        )
        current_raw_data = self.config_entry.options.get(
            CONF_ENABLE_RAW_DATA_SENSOR, DEFAULT_ENABLE_RAW_DATA_SENSOR
        )
        current_invert_sign = self.config_entry.options.get(
            CONF_INVERT_CURRENT_SIGN, DEFAULT_INVERT_CURRENT_SIGN
        )

        if user_input is not None:
            interval = int(user_input[CONF_UPDATE_INTERVAL])
            persistent = bool(user_input[CONF_PERSISTENT_CONNECTION])

            if not persistent and interval < MIN_UPDATE_INTERVAL:
                errors["base"] = "interval_too_low_for_one_shot"
            else:
                return self.async_create_entry(data=user_input)

            current_interval = interval
            current_persistent = persistent
            current_raw_data = bool(user_input[CONF_ENABLE_RAW_DATA_SENSOR])
            current_invert_sign = bool(user_input[CONF_INVERT_CURRENT_SIGN])

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_PERSISTENT_CONNECTION, default=current_persistent
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_UPDATE_INTERVAL, default=current_interval
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=MIN_UPDATE_INTERVAL_PERSISTENT,
                        max=3600,
                        unit_of_measurement="s",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_ENABLE_RAW_DATA_SENSOR, default=current_raw_data
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_INVERT_CURRENT_SIGN, default=current_invert_sign
                ): selector.BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
