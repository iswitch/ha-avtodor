"""Токены мобильного API, восстановление авторизации и ошибки данных."""

import json
from decimal import Decimal

import pytest

from custom_components.avtodor.api import (
    AvtodorAuthError,
    AvtodorClient,
    AvtodorConnectionError,
)
from custom_components.avtodor.const import API_BASE_URL, API_URL

LOGIN_URL = f"{API_BASE_URL}oauth/login"
REFRESH_URL = f"{API_BASE_URL}oauth/refresh"
TOKENS = {
    "access_token": "access-token",
    "refresh_token": "refresh-token",
    "expires_in": 3600,
    "token_type": "bearer",
}
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
DEVICES_URL = f"{API_BASE_URL}api/devices?contract_id=10&all=true"
VEHICLES_URL = f"{API_BASE_URL}api/grnzs"
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


@pytest.fixture
def authenticated_client(client):
    client._access_token = "old-access-token"
    client._refresh_token = "old-refresh-token"
    client._token_expires_at = float("inf")
    return client


async def test_login_and_token_reuse(client, aioclient_mock):
    aioclient_mock.post(LOGIN_URL, json=TOKENS)
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
    calls = aioclient_mock.mock_calls
    assert sum(call[0] == "POST" for call in calls) == 1
    assert calls[0][2] == {
        "username": "example@example.com",
        "password": "test-password",
    }
    assert "Authorization" not in calls[0][3]
    assert calls[0][3]["Content-Type"] == "application/x-www-form-urlencoded"
    assert all(call[3]["Authorization"] == "Bearer access-token" for call in calls[1:])


async def test_expired_access_token_refreshes_without_password(
    authenticated_client, aioclient_mock
):
    authenticated_client._token_expires_at = 0
    aioclient_mock.post(REFRESH_URL, json=TOKENS)
    aioclient_mock.get(API_URL, json=PAYLOAD)
    await authenticated_client.async_get_data()
    calls = aioclient_mock.mock_calls
    assert calls[0][1].human_repr() == REFRESH_URL
    assert calls[0][2] == {"refresh_token": "old-refresh-token"}
    assert "Authorization" not in calls[0][3]
    assert sum(call[0] == "POST" for call in calls) == 1
    assert calls[1][3]["Authorization"] == "Bearer access-token"


async def test_rejected_access_token_refreshes_once(
    authenticated_client, aioclient_mock
):
    response = aioclient_mock.request("get", API_URL, status=401)

    async def refresh(method, url, data):
        response.status = 200
        response._response = json.dumps(PAYLOAD).encode()
        return aioclient_mock._mocks[-1]

    aioclient_mock.post(REFRESH_URL, json=TOKENS, side_effect=refresh)
    assert (await authenticated_client.async_get_data())["client_id"] == "99"
    assert sum(call[0] == "POST" for call in aioclient_mock.mock_calls) == 1
    assert aioclient_mock.mock_calls[0][3]["Authorization"] == "Bearer old-access-token"
    assert aioclient_mock.mock_calls[2][3]["Authorization"] == "Bearer access-token"


@pytest.mark.parametrize("status", [400, 401])
async def test_rejected_refresh_falls_back_to_one_login(
    authenticated_client, aioclient_mock, status
):
    authenticated_client._token_expires_at = 0
    aioclient_mock.post(REFRESH_URL, status=status)
    aioclient_mock.post(LOGIN_URL, json=TOKENS)
    aioclient_mock.get(API_URL, json=PAYLOAD)
    await authenticated_client.async_get_data()
    assert [call[1].human_repr() for call in aioclient_mock.mock_calls[:2]] == [
        REFRESH_URL,
        LOGIN_URL,
    ]
    assert sum(call[0] == "POST" for call in aioclient_mock.mock_calls) == 2


async def test_new_token_rejected_stops_reauth_loop(
    authenticated_client, aioclient_mock
):
    aioclient_mock.get(API_URL, status=401)
    aioclient_mock.post(REFRESH_URL, json=TOKENS)
    with pytest.raises(AvtodorAuthError, match="Token was rejected"):
        await authenticated_client.async_get_data()
    assert aioclient_mock.call_count == 3
    assert authenticated_client._access_token is None
    assert authenticated_client._refresh_token is None


@pytest.mark.parametrize("status", [400, 401])
async def test_invalid_credentials_are_not_retried(client, aioclient_mock, status):
    aioclient_mock.post(LOGIN_URL, status=status)
    with pytest.raises(AvtodorAuthError, match="Authentication failed"):
        await client.async_get_data()
    assert aioclient_mock.call_count == 1


@pytest.mark.parametrize("status", [403, 429, 500, 503])
async def test_refresh_service_failure_does_not_send_password(
    authenticated_client, aioclient_mock, status
):
    authenticated_client._token_expires_at = 0
    aioclient_mock.post(REFRESH_URL, status=status)
    with pytest.raises(AvtodorConnectionError, match=f"HTTP {status}"):
        await authenticated_client.async_get_data()
    assert aioclient_mock.call_count == 1
    assert aioclient_mock.mock_calls[0][2] == {"refresh_token": "old-refresh-token"}


@pytest.mark.parametrize("path", [LOGIN_URL, API_URL])
async def test_secrets_never_follow_redirect(client, aioclient_mock, path):
    if path == API_URL:
        client._access_token = "private-access-token"
        client._token_expires_at = float("inf")
        aioclient_mock.get(
            path, status=307, headers={"Location": "https://example.com/collect"}
        )
    else:
        aioclient_mock.post(
            path, status=307, headers={"Location": "https://example.com/collect"}
        )
    with pytest.raises(AvtodorConnectionError, match="HTTP 307"):
        await client.async_get_data()
    assert aioclient_mock.call_count == 1


async def test_untrusted_api_url_is_rejected(authenticated_client, aioclient_mock):
    with pytest.raises(AvtodorConnectionError, match="Unexpected API URL"):
        await authenticated_client._async_get_json("https://example.com/collect")
    assert aioclient_mock.call_count == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("access_token", None),
        ("access_token", ""),
        ("refresh_token", None),
        ("expires_in", True),
        ("expires_in", 0),
        ("expires_in", -1),
        ("expires_in", "3600"),
        ("expires_in", float("inf")),
        pytest.param("expires_in", 10**400, id="expiry-overflow"),
        ("token_type", None),
        ("token_type", "Basic"),
    ],
)
async def test_invalid_tokens_are_not_used(client, aioclient_mock, field, value):
    aioclient_mock.post(LOGIN_URL, text=json.dumps({**TOKENS, field: value}))
    with pytest.raises(AvtodorConnectionError, match="Invalid token response"):
        await client.async_get_data()
    assert aioclient_mock.call_count == 1
    assert client._access_token is None


async def test_non_json_response_is_not_an_auth_failure(
    authenticated_client, aioclient_mock
):
    aioclient_mock.get(API_URL, text="<html>Service unavailable</html>")
    with pytest.raises(AvtodorConnectionError, match="Invalid API response"):
        await authenticated_client.async_get_data()
    assert aioclient_mock.call_count == 1


@pytest.mark.parametrize("balance", [None, "NaN", "Infinity", "invalid", True])
async def test_invalid_balance_does_not_become_zero(
    authenticated_client, aioclient_mock, balance
):
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
        await authenticated_client.async_get_data()


@pytest.mark.parametrize("status", [403, 429, 500, 503])
async def test_service_error_does_not_retry_login(
    authenticated_client, aioclient_mock, status
):
    aioclient_mock.get(API_URL, status=status)
    with pytest.raises(AvtodorConnectionError, match=f"HTTP {status}"):
        await authenticated_client.async_get_data()
    assert aioclient_mock.call_count == 1


@pytest.mark.parametrize("index,key", [(0, "devices"), (1, "vehicles")])
async def test_auxiliary_failure_preserves_balance(
    authenticated_client, aioclient_mock, index, key
):
    aioclient_mock.get(API_URL, json=PAYLOAD)
    aioclient_mock._mocks[index].status = 503
    result = await authenticated_client.async_get_data()
    assert result["contracts"]["123"]["balance"] == Decimal("-25.5")
    assert (
        result["contracts"]["123"][key] if key == "devices" else result[key]
    ) is None


@pytest.mark.parametrize("debt", [None, "NaN", "Infinity", True])
async def test_invalid_debt_is_not_zero(authenticated_client, aioclient_mock, debt):
    aioclient_mock.get(API_URL, json=PAYLOAD)
    aioclient_mock._mocks[1]._response = json.dumps(
        [{**VEHICLES[0], "debt": debt}]
    ).encode()
    result = await authenticated_client.async_get_data()
    assert result["vehicles"] is None
    assert result["contracts"]["123"]["balance"] == Decimal("-25.5")


async def test_unknown_status_is_not_reported_as_valid(
    authenticated_client, aioclient_mock
):
    aioclient_mock.get(API_URL, json=PAYLOAD)
    aioclient_mock._mocks[0]._response = json.dumps(
        {
            "devices": [
                {**DEVICES["devices"][0], "device_status_id": 999, "iop_status_id": 999}
            ]
        }
    ).encode()
    result = await authenticated_client.async_get_data()
    device = result["contracts"]["123"]["devices"]["7"]
    assert device["status"] is None
    assert device["interoperability"] is None
    assert device["status_id"] == 999
