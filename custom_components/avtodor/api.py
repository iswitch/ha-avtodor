"""Авторизация в личном кабинете и чтение баланса Автодора."""

import asyncio
import json
import logging
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Any

from aiohttp import ClientError, ClientTimeout, CookieJar
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from yarl import URL

from .const import API_URL, AUTH_HOST, CABINET_URL, DEVICE_STATUSES, IOP_STATUSES

_LOGGER = logging.getLogger(__name__)


class AvtodorError(Exception):
    """Ошибка сервиса Автодор."""


class AvtodorAuthError(AvtodorError):
    """Учётные данные отклонены."""


class AvtodorConnectionError(AvtodorError):
    """Сервис недоступен или вернул некорректный ответ."""


class LoginFormParser(HTMLParser):
    """Извлечение формы входа Keycloak."""

    def __init__(self) -> None:
        super().__init__()
        self.action: str | None = None
        self.fields: dict[str, str] = {}
        self.in_form = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "form" and attributes.get("id") == "kc-form-login":
            self.action = attributes.get("action")
            self.in_form = True
        elif self.in_form and tag == "input" and attributes.get("type") == "hidden":
            if name := attributes.get("name"):
                self.fields[name] = attributes.get("value") or ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "form":
            self.in_form = False


class AvtodorClient:
    """Одна изолированная HTTP-сессия на аккаунт."""

    def __init__(self, hass: HomeAssistant, username: str, password: str) -> None:
        self._username = username
        self._password = password
        self._authenticated = False
        # Куки личного кабинета нельзя смешивать с общей сессией Home Assistant.
        self._session = async_create_clientsession(
            hass,
            cookie_jar=CookieJar(),
            timeout=ClientTimeout(total=30),
            # User-Agent сетевого клиента Android-приложения Автодор 2.2.4.
            headers={"User-Agent": "okhttp/4.4.0"},
        )

    def close(self) -> None:
        """Освободить сессию, оставив общий коннектор под управлением HA."""
        self._session.detach()

    async def _async_request(
        self, url: str, data: dict[str, str] | None = None
    ) -> tuple[int, str]:
        target = URL(url)
        method = "POST" if data is not None else "GET"
        try:
            async with asyncio.timeout(30):
                for _ in range(10):
                    # В цепочке входа есть два домена. Не пересылаем сессию и пароль посторонним.
                    if (
                        target.scheme != "https"
                        or target.host not in {URL(CABINET_URL).host, AUTH_HOST}
                        or target.port != 443
                        or target.user is not None
                    ):
                        raise AvtodorConnectionError(
                            "Unexpected authentication redirect"
                        )
                    async with self._session.request(
                        method, target, data=data, allow_redirects=False
                    ) as response:
                        if response.status in {301, 302, 303, 307, 308}:
                            location = response.headers.get("Location")
                            if not location:
                                raise AvtodorConnectionError(
                                    "Missing redirect location"
                                )
                            target = target.join(URL(location))
                            if response.status == 303 or (
                                response.status in {301, 302} and method == "POST"
                            ):
                                method, data = "GET", None
                            continue
                        if response.status not in {200, 401, 403}:
                            raise AvtodorConnectionError(f"HTTP {response.status}")
                        return response.status, await response.text(errors="replace")
        except ClientError, TimeoutError, ValueError:
            # Исключения aiohttp могут содержать URL с токеном сессии.
            raise AvtodorConnectionError("Unable to reach Avtodor") from None
        raise AvtodorConnectionError("Too many authentication redirects")

    async def _async_login(self) -> None:
        self._authenticated = False
        self._session.cookie_jar.clear()
        status, body = await self._async_request(CABINET_URL)
        form = LoginFormParser()
        form.feed(body)
        if status != 200 or not form.action:
            raise AvtodorConnectionError("Login form is unavailable")
        action = URL(form.action)
        if (
            action.scheme != "https"
            or action.host != AUTH_HOST
            or action.port != 443
            or action.user is not None
            or not action.path.endswith("/login-actions/authenticate")
        ):
            raise AvtodorConnectionError("Unexpected login form target")
        status, body = await self._async_request(
            str(action),
            {
                **form.fields,
                "username": self._username,
                "password": self._password,
                "credentialId": "",
            },
        )
        form = LoginFormParser()
        form.feed(body)
        if status in {401, 403} or form.action:
            raise AvtodorAuthError("Authentication failed")
        self._authenticated = True

    async def _async_get_json(self, url: str) -> Any:
        """Прочитать API, восстановив истёкшую сессию не более одного раза."""
        if not self._authenticated:
            await self._async_login()
        status, body = await self._async_request(url)
        # Истёкшая сессия может вернуть HTML входа со статусом 200 вместо 401.
        if status in {401, 403} or "kc-form-login" in body:
            await self._async_login()
            status, body = await self._async_request(url)
        if status in {401, 403} or "kc-form-login" in body:
            self._authenticated = False
            raise AvtodorAuthError("Session was rejected")
        try:
            return json.loads(body)
        except ValueError:
            raise AvtodorConnectionError("Invalid API response") from None

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
                    f"{CABINET_URL}api/devices?contract_id={contract['id']}&all=true"
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
            payload = await self._async_get_json(f"{CABINET_URL}api/grnzs")
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
