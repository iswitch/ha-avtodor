"""Баланс лицевого счёта Автодора."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant

from .api import AvtodorClient
from .coordinator import AvtodorCoordinator

type AvtodorConfigEntry = ConfigEntry[AvtodorCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: AvtodorConfigEntry) -> bool:
    """Подключить аккаунт и загрузить сенсоры."""
    client = AvtodorClient(hass, entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD])
    coordinator = AvtodorCoordinator(hass, entry, client)
    try:
        await coordinator.async_config_entry_first_refresh()
        entry.runtime_data = coordinator
        await hass.config_entries.async_forward_entry_setups(entry, [Platform.SENSOR])
    except BaseException:
        client.close()
        raise
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AvtodorConfigEntry) -> bool:
    """Остановить обновления и закрыть соединения."""
    if unloaded := await hass.config_entries.async_unload_platforms(
        entry, [Platform.SENSOR]
    ):
        entry.runtime_data.client.close()
    return unloaded
