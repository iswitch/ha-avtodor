"""Авторизация и чтение данных через мобильный API Автодора."""

import json
import logging
import math
from decimal import Decimal, InvalidOperation
from time import monotonic
from typing import Any

from aiohttp import ClientError, ClientTimeout, DummyCookieJar
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from yarl import URL

from .const import API_BASE_URL, API_URL, DEVICE_STATUSES, IOP_STATUSES

_LOGGER = logging.getLogger(__name__)


class AvtodorError(Exception):
    """Ошибка сервиса Автодор."""


class AvtodorAuthError(AvtodorError):
    """Учётные данные отклонены."""


class AvtodorConnectionError(AvtodorError):
    """Сервис недоступен или вернул некорректный ответ."""


class AvtodorClient:
    """Одна изолированная HTTP-сессия на аккаунт."""

    def __init__(self, hass: HomeAssistant, username: str, password: str) -> None:
        self._username = username
        self._password = password
        # Токены принадлежат одному аккаунту и не сохраняются в конфигурации или логах.
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._token_expires_at = 0.0
        self._session = async_create_clientsession(
            hass,
            cookie_jar=DummyCookieJar(),
            timeout=ClientTimeout(total=30),
            # Заголовки основного HTTP-клиента Android-приложения Автодор 2.2.4.
            headers={
                "User-Agent": "okhttp/4.4.0",
                "X-Device": "android",
                "Accept-Language": "ru",
                "Accept": "application/json",
            },
        )

    def close(self) -> None:
        """Освободить сессию, оставив общий коннектор под управлением HA."""
        self._session.detach()

    async def _async_request(
        self,
        url: str,
        data: dict[str, str] | None = None,
        access_token: str | None = None,
    ) -> tuple[int, Any]:
        target = URL(url)
        # Мобильный API не требует редиректов: пароль и токены остаются на одном узле.
        if (
            target.scheme != "https"
            or target.host != URL(API_BASE_URL).host
            or target.port != 443
            or target.user is not None
        ):
            raise AvtodorConnectionError("Unexpected API URL")
        method = "POST" if data is not None else "GET"
        headers = {
            "Content-Type": (
                "application/x-www-form-urlencoded"
                if data is not None
                else "application/json"
            )
        }
        if access_token is not None:
            headers["Authorization"] = f"Bearer {access_token}"
        try:
            async with self._session.request(
                method, target, data=data, headers=headers, allow_redirects=False
            ) as response:
                if response.status not in {200, 400, 401, 403}:
                    raise AvtodorConnectionError(f"HTTP {response.status}")
                if response.status != 200:
                    return response.status, None
                body = await response.text(errors="replace")
        except ClientError, TimeoutError, ValueError:
            # Не переносим детали исключений HTTP-клиента в журнал HA.
            raise AvtodorConnectionError("Unable to reach Avtodor") from None
        try:
            return 200, json.loads(body)
        except ValueError:
            raise AvtodorConnectionError("Invalid API response") from None

    async def _async_authenticate(self) -> None:
        self._access_token = None
        if self._refresh_token:
            status, payload = await self._async_request(
                f"{API_BASE_URL}oauth/refresh",
                {"refresh_token": self._refresh_token},
            )
            # Истёкший refresh token разрешает один обычный вход, сетевые ошибки — нет.
            if status in {400, 401}:
                self._refresh_token = None
        if not self._refresh_token:
            status, payload = await self._async_request(
                f"{API_BASE_URL}oauth/login",
                {"username": self._username, "password": self._password},
            )
        if status in {400, 401}:
            raise AvtodorAuthError("Authentication failed")
        if status != 200:
            raise AvtodorConnectionError(f"HTTP {status}")
        try:
            access_token = payload["access_token"]
            refresh_token = payload["refresh_token"]
            expires_in = payload["expires_in"]
            if (
                not isinstance(access_token, str)
                or not access_token
                or not isinstance(refresh_token, str)
                or not refresh_token
                or payload.get("token_type", "bearer").lower() != "bearer"
                or type(expires_in) not in {int, float}
                or not math.isfinite(expires_in)
                or expires_in <= 0
            ):
                raise ValueError
        except KeyError, TypeError, AttributeError, ValueError, OverflowError:
            raise AvtodorConnectionError("Invalid token response") from None
        self._access_token = access_token
        self._refresh_token = refresh_token
        # Монотонное время не зависит от перевода часов; небольшой запас учитывает задержки.
        self._token_expires_at = monotonic() + expires_in - min(30, expires_in / 10)

    async def _async_get_json(self, url: str) -> Any:
        """Прочитать API, обновив истёкший токен не более одного раза."""
        if self._access_token is None or monotonic() >= self._token_expires_at:
            await self._async_authenticate()
        status, payload = await self._async_request(
            url, access_token=self._access_token
        )
        if status == 401:
            await self._async_authenticate()
            status, payload = await self._async_request(
                url, access_token=self._access_token
            )
        if status == 401:
            self._access_token = self._refresh_token = None
            raise AvtodorAuthError("Token was rejected")
        if status != 200:
            raise AvtodorConnectionError(f"HTTP {status}")
        return payload

    async def async_get_data(self) -> dict[str, Any]:
        """Получить данные сенсоров, не сохраняя профиль клиента и auth_key."""
        payload = await self._async_get_json(API_URL)
        try:
            client_id = payload["client"]["id"]
            if not isinstance(client_id, (int, str)) or isinstance(client_id, bool):
                raise ValueError
            contracts = {}
            for contract in payload["contracts"]:
                contract_id = contract["id"]
                if not isinstance(contract_id, int) or isinstance(contract_id, bool):
                    raise ValueError
                account_id = contract["account_id"]
                if (
                    not isinstance(account_id, (int, str))
                    or isinstance(account_id, bool)
                    or not str(account_id)
                ):
                    raise ValueError
                balance = Decimal(str(contract["account_balance"]))
                if not balance.is_finite():
                    raise ValueError
                contracts[str(account_id)] = {
                    "id": contract_id,
                    "balance": balance,
                    "number": str(contract["num"]),
                    "loyalty_member_balance": (
                        contract.get("loyalty_member_balance")
                        if type(contract.get("loyalty_member_balance")) is int
                        else None
                    ),
                    "account_balance_dt": contract.get("account_balance_dt"),
                }
            if not str(client_id) or not contracts:
                raise ValueError
        except KeyError, TypeError, ValueError, InvalidOperation:
            # При сбое не подменяем неизвестный баланс нулём.
            raise AvtodorConnectionError("Invalid account data") from None

        for contract in contracts.values():
            contract["devices"] = None
            try:
                # В списке нужны также заблокированные и отключённые устройства.
                payload = await self._async_get_json(
                    f"{API_BASE_URL}api/devices?contract_id={contract['id']}&all=true"
                )
                devices = {}
                if not isinstance(payload["devices"], list):
                    raise ValueError
                for device in payload["devices"]:
                    if device["device_type_id"] != 1:
                        continue
                    device_id = device["id"]
                    if not isinstance(device_id, int) or isinstance(device_id, bool):
                        raise ValueError
                    if not isinstance(device["pan"], str) or not device["pan"]:
                        raise ValueError
                    devices[str(device_id)] = {
                        "pan": device["pan"],
                        "status": DEVICE_STATUSES.get(device["device_status_id"]),
                        "status_id": device["device_status_id"],
                        "interoperability": IOP_STATUSES.get(device["iop_status_id"]),
                        "iop_status_id": device["iop_status_id"],
                    }
                contract["devices"] = devices
            except AvtodorConnectionError, KeyError, TypeError, ValueError:
                # Сбой дополнительного API не должен лишать пользователя баланса.
                _LOGGER.warning("Unable to retrieve Avtodor transponders")

        vehicles = None
        try:
            payload = await self._async_get_json(f"{API_BASE_URL}api/grnzs")
            if not isinstance(payload, list):
                raise ValueError
            parsed_vehicles = {}
            for vehicle in payload:
                vehicle_id = vehicle["uuid"]
                if not isinstance(vehicle_id, str) or not vehicle_id:
                    raise ValueError
                if not isinstance(vehicle["grnz"], str) or not vehicle["grnz"]:
                    raise ValueError
                debt = Decimal(str(vehicle["debt"]))
                if not debt.is_finite():
                    raise ValueError
                parsed_vehicles[vehicle_id] = {
                    "plate": vehicle["grnz"],
                    "country": vehicle["country_code"],
                    "debt": debt,
                    "violations_count": vehicle.get("violations_count"),
                }
            vehicles = parsed_vehicles
        except (
            AvtodorConnectionError,
            KeyError,
            TypeError,
            ValueError,
            InvalidOperation,
        ):
            # Неизвестный долг отличается от подтверждённого нулевого долга.
            _LOGGER.warning("Unable to retrieve Avtodor vehicle debts")
        return {
            "client_id": str(client_id),
            "contracts": contracts,
            "vehicles": vehicles,
        }
