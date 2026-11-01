"""Настройка аккаунта Автодора через интерфейс Home Assistant."""

from collections.abc import Mapping
from typing import Any

import probatio
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import AvtodorAuthError, AvtodorClient, AvtodorConnectionError
from .const import (
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    MAX_UPDATE_INTERVAL,
    MIN_UPDATE_INTERVAL,
)

AUTH_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_USERNAME): TextSelector(),
        probatio.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
    }
)


class AvtodorConfigFlow(ConfigFlow, domain=DOMAIN):
    """Вход, изменение учётных данных и повторная авторизация."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> AvtodorOptionsFlow:
        return AvtodorOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._async_credentials("user", user_input)

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._async_credentials("reauth_confirm", user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._async_credentials("reconfigure", user_input)

    async def _async_credentials(
        self, step_id: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        entry = None
        if step_id == "reauth_confirm":
            entry = self._get_reauth_entry()
        elif step_id == "reconfigure":
            entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {
                CONF_USERNAME: user_input[CONF_USERNAME].strip(),
                CONF_PASSWORD: user_input[CONF_PASSWORD],
            }
            client = AvtodorClient(self.hass, data[CONF_USERNAME], data[CONF_PASSWORD])
            try:
                result = await client.async_get_data()
            except AvtodorAuthError:
                errors["base"] = "invalid_auth"
            except AvtodorConnectionError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(result["client_id"])
                if entry is not None:
                    # Повторный вход не должен незаметно подменять счета другим аккаунтом.
                    self._abort_if_unique_id_mismatch(reason="wrong_account")
                    return self.async_update_reload_and_abort(entry, data_updates=data)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="Автодор", data=data)
            finally:
                client.close()

        suggested = {CONF_USERNAME: entry.data[CONF_USERNAME]} if entry else {}
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(AUTH_SCHEMA, suggested),
            errors=errors,
        )


class AvtodorOptionsFlow(OptionsFlowWithReload):
    """Настройка периода обновления."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=probatio.Schema(
                {
                    probatio.Required(
                        CONF_UPDATE_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
                        ),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_UPDATE_INTERVAL,
                            max=MAX_UPDATE_INTERVAL,
                            step=1,
                            mode=NumberSelectorMode.BOX,
                            unit_of_measurement="min",
                        )
                    )
                }
            ),
        )
