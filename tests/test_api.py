"""Авторизация, повторное использование сессии и ошибки API."""

import json
from decimal import Decimal

import pytest

from custom_components.avtodor.api import (
    AvtodorAuthError,
    AvtodorClient,
    AvtodorConnectionError,
)
from custom_components.avtodor.const import API_URL, CABINET_URL

LOGIN_URL = "https://auth-lkmp.avtodor-tr.ru/auth/realms/test/login-actions/authenticate?session_code=test"
LOGIN_FORM = f'<form action="{LOGIN_URL.replace("&", "&amp;")}" id="kc-form-login"><input type="hidden" name="credentialId" value=""></form>'
PAYLOAD = {
    "client": {"id": 99, "address": "Private address"},
    "contracts": [
        {
            "id": 10,
            "account_id": 123,
            "num": "TEST-001",
            "account_balance": -25.50,
            "auth_key": "private-contract-key",
            "loyalty_member_balance": 150,
        }
    ],
}
DEVICES_URL = f"{CABINET_URL}api/devices?contract_id=10&all=true"
VEHICLES_URL = f"{CABINET_URL}api/grnzs"
DEVICES = {
    "devices": [
        {
            "id": 7,
            "pan": "TEST-TRANSPONDER",
            "device_type_id": 1,
            "device_status_id": 3,
            "iop_status_id": 2,
        },
        {"id": 8, "device_type_id": 2},
    ]
}
VEHICLES = [
    {
        "uuid": "test-vehicle",
        "grnz": "А000АА00",
        "country_code": "RUS",
        "debt": 150.50,
        "violations_count": 2,
    }
]


@pytest.fixture
async def client(hass, aioclient_mock):
    aioclient_mock.get(DEVICES_URL, json=DEVICES)
    aioclient_mock.get(VEHICLES_URL, json=VEHICLES)
    api = AvtodorClient(hass, "example@example.com", "test-password")
    yield api
    api.close()


async def test_login_and_session_reuse(client, aioclient_mock):
    aioclient_mock.get(CABINET_URL, text=LOGIN_FORM)
    aioclient_mock.post(LOGIN_URL, text="<html>Account</html>")
    aioclient_mock.get(API_URL, json=PAYLOAD)
    first = await client.async_get_data()
    assert await client.async_get_data() == first
    assert first["contracts"]["123"]["balance"] == Decimal("-25.5")
    assert first["contracts"]["123"]["devices"]["7"]["status"] == "valid"
    assert first["contracts"]["123"]["devices"]["7"]["interoperability"] == "connected"
    assert "8" not in first["contracts"]["123"]["devices"]
    assert first["vehicles"]["test-vehicle"]["debt"] == Decimal("150.5")
    assert "auth_key" not in str(first)
    assert "address" not in str(first)
    assert sum(call[0] == "POST" for call in aioclient_mock.mock_calls) == 1


async def test_expired_session_reauthenticates_once(client, aioclient_mock):
    client._authenticated = True
    response = aioclient_mock.request("get", API_URL, status=401)
    aioclient_mock.get(CABINET_URL, text=LOGIN_FORM)

    async def login(method, url, data):
        response.status = 200
        response._response = json.dumps(PAYLOAD).encode()
        return aioclient_mock._mocks[-1]

    aioclient_mock.post(LOGIN_URL, text="<html>Account</html>", side_effect=login)
    assert (await client.async_get_data())["client_id"] == "99"
    assert sum(call[0] == "POST" for call in aioclient_mock.mock_calls) == 1


async def test_invalid_credentials_are_not_retried(client, aioclient_mock):
    aioclient_mock.get(CABINET_URL, text=LOGIN_FORM)
    aioclient_mock.post(LOGIN_URL, text=LOGIN_FORM)
    with pytest.raises(AvtodorAuthError, match="Authentication failed"):
        await client.async_get_data()
    assert aioclient_mock.call_count == 2


async def test_credentials_never_follow_untrusted_redirect(client, aioclient_mock):
    aioclient_mock.get(CABINET_URL, text=LOGIN_FORM)
    aioclient_mock.post(
        LOGIN_URL, status=307, headers={"Location": "https://example.com/collect"}
    )
    with pytest.raises(
        AvtodorConnectionError, match="Unexpected authentication redirect"
    ):
        await client.async_get_data()
    assert aioclient_mock.call_count == 2


async def test_untrusted_form_is_rejected(client, aioclient_mock):
    aioclient_mock.get(
        CABINET_URL,
        text='<form id="kc-form-login" action="https://example.com/login-actions/authenticate"></form>',
    )
    with pytest.raises(AvtodorConnectionError, match="Unexpected login form target"):
        await client.async_get_data()
    assert aioclient_mock.call_count == 1


@pytest.mark.parametrize("balance", [None, "NaN", "Infinity", "invalid", True])
async def test_invalid_balance_does_not_become_zero(client, aioclient_mock, balance):
    client._authenticated = True
    aioclient_mock.get(
        API_URL,
        json={
            "client": {"id": 99},
            "contracts": [
                {
                    "id": 10,
                    "account_id": 123,
                    "num": "TEST-001",
                    "account_balance": balance,
                }
            ],
        },
    )
    with pytest.raises(AvtodorConnectionError, match="Invalid account data"):
        await client.async_get_data()


@pytest.mark.parametrize("status", [429, 500, 503])
async def test_service_error_does_not_retry_login(client, aioclient_mock, status):
    client._authenticated = True
    aioclient_mock.get(API_URL, status=status)
    with pytest.raises(AvtodorConnectionError, match=f"HTTP {status}"):
        await client.async_get_data()
    assert aioclient_mock.call_count == 1


@pytest.mark.parametrize("index,key", [(0, "devices"), (1, "vehicles")])
async def test_auxiliary_failure_preserves_balance(client, aioclient_mock, index, key):
    client._authenticated = True
    aioclient_mock.get(API_URL, json=PAYLOAD)
    aioclient_mock._mocks[index].status = 503
    result = await client.async_get_data()
    assert result["contracts"]["123"]["balance"] == Decimal("-25.5")
    assert (
        result["contracts"]["123"][key] if key == "devices" else result[key]
    ) is None


@pytest.mark.parametrize("debt", [None, "NaN", "Infinity", True])
async def test_invalid_debt_is_not_zero(client, aioclient_mock, debt):
    client._authenticated = True
    aioclient_mock.get(API_URL, json=PAYLOAD)
    aioclient_mock._mocks[1]._response = json.dumps(
        [{**VEHICLES[0], "debt": debt}]
    ).encode()
    result = await client.async_get_data()
    assert result["vehicles"] is None
    assert result["contracts"]["123"]["balance"] == Decimal("-25.5")


async def test_unknown_status_is_not_reported_as_valid(client, aioclient_mock):
    client._authenticated = True
    aioclient_mock.get(API_URL, json=PAYLOAD)
    aioclient_mock._mocks[0]._response = json.dumps(
        {
            "devices": [
                {**DEVICES["devices"][0], "device_status_id": 999, "iop_status_id": 999}
            ]
        }
    ).encode()
    result = await client.async_get_data()
    device = result["contracts"]["123"]["devices"]["7"]
    assert device["status"] is None
    assert device["interoperability"] is None
    assert device["status_id"] == 999
