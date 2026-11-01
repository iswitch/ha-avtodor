"""Константы интеграции Автодор."""

DOMAIN = "avtodor"
CONF_UPDATE_INTERVAL = "update_interval"
DEFAULT_UPDATE_INTERVAL = 5
MIN_UPDATE_INTERVAL = 5
MAX_UPDATE_INTERVAL = 1440

CABINET_URL = "https://lk.avtodor-tr.ru/"
API_URL = f"{CABINET_URL}api/client/extended"
AUTH_HOST = "auth-lkmp.avtodor-tr.ru"

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
