"""Константы интеграции Автодор."""

DOMAIN = "avtodor"
CONF_UPDATE_INTERVAL = "update_interval"
DEFAULT_UPDATE_INTERVAL = 5
MIN_UPDATE_INTERVAL = 5
MAX_UPDATE_INTERVAL = 1440

API_BASE_URL = "https://lkmp.russianhighways.ru/"
API_URL = f"{API_BASE_URL}api/client/extended"

# Идентификаторы сверены со справочниками device_statuses и iop_statuses Автодора.
DEVICE_STATUSES = {
    1: "requested",
    2: "produced",
    3: "valid",
    4: "orange_list",
    5: "blocked",
    6: "deleted",
    7: "terminated",
}
IOP_STATUSES = {1: "not_connected", 2: "connected", 3: "not_supported"}
