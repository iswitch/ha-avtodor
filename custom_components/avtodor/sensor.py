"""Баланс, бонусы, транспондеры и задолженность по госномерам."""

from decimal import Decimal
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import AvtodorConfigEntry
from .const import DEVICE_STATUSES, DOMAIN, IOP_STATUSES
from .coordinator import AvtodorCoordinator

ACCOUNT_SENSORS = (
    SensorEntityDescription(
        key="balance",
        translation_key="balance",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="RUB",
        suggested_display_precision=2,
        icon="mdi:wallet",
    ),
    SensorEntityDescription(
        key="loyalty_member_balance",
        translation_key="bonus_points",
        suggested_display_precision=0,
        icon="mdi:star-circle",
    ),
)
TRANSPONDER_SENSORS = (
    SensorEntityDescription(
        key="status",
        translation_key="transponder_status",
        device_class=SensorDeviceClass.ENUM,
        options=list(DEVICE_STATUSES.values()),
        icon="mdi:contactless-payment",
    ),
    SensorEntityDescription(
        key="interoperability",
        translation_key="interoperability",
        device_class=SensorDeviceClass.ENUM,
        options=list(IOP_STATUSES.values()),
        icon="mdi:highway",
    ),
)
VEHICLE_SENSORS = (
    SensorEntityDescription(
        key="plate",
        translation_key="license_plate",
        icon="mdi:card-text-outline",
    ),
    SensorEntityDescription(
        key="debt",
        translation_key="debt",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="RUB",
        suggested_display_precision=2,
        icon="mdi:car-info",
    ),
    SensorEntityDescription(
        key="violations_count",
        translation_key="violations_count",
        suggested_display_precision=0,
        icon="mdi:alert-circle-outline",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AvtodorConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Добавлять новые счета, транспондеры и госномера при обновлении API."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def discover_entities() -> None:
        entities: list[SensorEntity] = []
        for account_id, contract in coordinator.data["contracts"].items():
            entities.extend(
                AvtodorAccountSensor(coordinator, account_id, description)
                for description in ACCOUNT_SENSORS
            )
            for device_id in contract.get("devices") or {}:
                entities.extend(
                    AvtodorTransponderSensor(
                        coordinator, account_id, device_id, description
                    )
                    for description in TRANSPONDER_SENSORS
                )
        entities.extend(
            AvtodorVehicleSensor(coordinator, vehicle_id, description)
            for vehicle_id in coordinator.data.get("vehicles") or {}
            for description in VEHICLE_SENSORS
        )
        new_entities = [entity for entity in entities if entity.unique_id not in known]
        if new_entities:
            known.update(entity.unique_id for entity in new_entities)
            async_add_entities(new_entities)

    discover_entities()
    entry.async_on_unload(coordinator.async_add_listener(discover_entities))


class AvtodorAccountSensor(CoordinatorEntity[AvtodorCoordinator], SensorEntity):
    """Баланс и бонусы лицевого счёта."""

    _attr_has_entity_name = True
    # Остаток средств и бонусов не является накопительным счётчиком.

    def __init__(
        self,
        coordinator: AvtodorCoordinator,
        account_id: str,
        description: SensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._account_id = account_id
        self._attr_unique_id = (
            f"{coordinator.data['client_id']}_{account_id}_{description.key}"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{coordinator.data['client_id']}_{account_id}")},
            name="Автодор",
            manufacturer="Автодор — Платные Дороги",
            model="Лицевой счёт",
            configuration_url="https://lk.avtodor-tr.ru/account/",
        )

    @property
    def available(self) -> bool:
        contract = self.coordinator.data["contracts"].get(self._account_id, {})
        return (
            super().available and contract.get(self.entity_description.key) is not None
        )

    @property
    def native_value(self) -> Decimal | int | None:
        contract = self.coordinator.data["contracts"].get(self._account_id, {})
        return contract.get(self.entity_description.key)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.key != "balance":
            return None
        contract = self.coordinator.data["contracts"].get(self._account_id, {})
        return {
            "account_id": self._account_id,
            "contract_number": contract.get("number"),
            "loyalty_member_balance": contract.get("loyalty_member_balance"),
            "account_balance_dt": contract.get("account_balance_dt"),
            "last_success": self.coordinator.last_success,
        }


class AvtodorTransponderSensor(CoordinatorEntity[AvtodorCoordinator], SensorEntity):
    """Статус и интероперабельность отдельного транспондера."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AvtodorCoordinator,
        account_id: str,
        device_id: str,
        description: SensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._account_id = account_id
        self._device_id = device_id
        client_id = coordinator.data["client_id"]
        self._attr_unique_id = f"{client_id}_transponder_{device_id}_{description.key}"
        device = coordinator.data["contracts"][account_id]["devices"][device_id]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{client_id}_transponder_{device_id}")},
            name=f"Транспондер {device['pan']}",
            manufacturer="Автодор — Платные Дороги",
            model="Транспондер",
            serial_number=device["pan"],
            via_device=(DOMAIN, f"{client_id}_{account_id}"),
            configuration_url="https://lk.avtodor-tr.ru/account/devices",
        )

    @property
    def available(self) -> bool:
        contract = self.coordinator.data["contracts"].get(self._account_id, {})
        return super().available and self._device_id in (contract.get("devices") or {})

    @property
    def native_value(self) -> str | None:
        contract = self.coordinator.data["contracts"].get(self._account_id, {})
        device = (contract.get("devices") or {}).get(self._device_id, {})
        return device.get(self.entity_description.key)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        contract = self.coordinator.data["contracts"].get(self._account_id, {})
        device = (contract.get("devices") or {}).get(self._device_id, {})
        return {
            "transponder_number": device.get("pan"),
            "status_id": device.get(
                "status_id"
                if self.entity_description.key == "status"
                else "iop_status_id"
            ),
        }


class AvtodorVehicleSensor(CoordinatorEntity[AvtodorCoordinator], SensorEntity):
    """Госномер, долг и нарушения автомобиля из личного кабинета."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AvtodorCoordinator,
        vehicle_id: str,
        description: SensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._vehicle_id = vehicle_id
        client_id = coordinator.data["client_id"]
        # UUID сохраняет привязку сущностей при изменении текста госномера.
        self._attr_unique_id = f"{client_id}_vehicle_{vehicle_id}_{description.key}"
        vehicle = coordinator.data["vehicles"][vehicle_id]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{client_id}_vehicle_{vehicle_id}")},
            name=f"Автодор {vehicle['plate']}",
            manufacturer="Автодор — Платные Дороги",
            model="Госномер",
            configuration_url="https://lk.avtodor-tr.ru/account/grn",
        )

    @property
    def available(self) -> bool:
        vehicle = (self.coordinator.data.get("vehicles") or {}).get(
            self._vehicle_id, {}
        )
        return (
            super().available and vehicle.get(self.entity_description.key) is not None
        )

    @property
    def native_value(self) -> Decimal | str | int | None:
        vehicle = (self.coordinator.data.get("vehicles") or {}).get(
            self._vehicle_id, {}
        )
        return vehicle.get(self.entity_description.key)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        vehicle = (self.coordinator.data.get("vehicles") or {}).get(
            self._vehicle_id, {}
        )
        return {
            "license_plate": vehicle.get("plate"),
            "country_code": vehicle.get("country"),
            "violations_count": vehicle.get("violations_count"),
        }
