"""Периодическое обновление счетов Автодора."""

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import AvtodorAuthError, AvtodorClient, AvtodorConnectionError
from .const import CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class AvtodorCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Одно обновление API обслуживает все сенсоры аккаунта."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: AvtodorClient
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                minutes=entry.options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
            ),
        )
        self.client = client
        self.last_success = None

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            data = await self.client.async_get_data()
        except AvtodorAuthError as err:
            raise ConfigEntryAuthFailed("Authentication failed") from err
        except AvtodorConnectionError as err:
            raise UpdateFailed(str(err)) from err
        if data["client_id"] != self.config_entry.unique_id:
            raise ConfigEntryAuthFailed("Account has changed")
        self.last_success = dt_util.utcnow()
        return data
