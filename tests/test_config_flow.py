"""Настройка, дубли аккаунтов и повторная авторизация."""

from unittest.mock import patch

import pytest
from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.avtodor.api import AvtodorAuthError, AvtodorConnectionError
from custom_components.avtodor.const import CONF_UPDATE_INTERVAL, DOMAIN

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")
CREDS = {"username": "example@example.com", "password": "test-password"}


async def test_user_flow(hass, account_data):
    with (
        patch(
            "custom_components.avtodor.config_flow.AvtodorClient.async_get_data",
            return_value=account_data,
        ),
        patch("custom_components.avtodor.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        assert result["type"] == FlowResultType.FORM
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], CREDS
        )
        await hass.async_block_till_done()
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"] == CREDS
    assert result["result"].unique_id == "99"


@pytest.mark.parametrize(
    "error,expected",
    [
        (AvtodorAuthError("Rejected"), "invalid_auth"),
        (AvtodorConnectionError("HTTP 503"), "cannot_connect"),
    ],
)
async def test_flow_errors(hass, error, expected):
    with patch(
        "custom_components.avtodor.config_flow.AvtodorClient.async_get_data",
        side_effect=error,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=CREDS
        )
    assert result["errors"] == {"base": expected}


async def test_duplicate_account(hass, account_data):
    MockConfigEntry(domain=DOMAIN, unique_id="99", data=CREDS).add_to_hass(hass)
    with patch(
        "custom_components.avtodor.config_flow.AvtodorClient.async_get_data",
        return_value=account_data,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=CREDS
        )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.parametrize(
    "source,step_id",
    [(SOURCE_REAUTH, "reauth_confirm"), (SOURCE_RECONFIGURE, "reconfigure")],
)
async def test_update_credentials(hass, account_data, source, step_id):
    entry = MockConfigEntry(domain=DOMAIN, unique_id="99", data=CREDS)
    entry.add_to_hass(hass)
    with (
        patch(
            "custom_components.avtodor.config_flow.AvtodorClient.async_get_data",
            return_value=account_data,
        ),
        patch(
            "homeassistant.config_entries.ConfigEntries.async_reload", return_value=True
        ),
    ):
        flow = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": source, "entry_id": entry.entry_id, "unique_id": "99"},
            data=CREDS if source == SOURCE_REAUTH else None,
        )
        assert flow["step_id"] == step_id
        result = await hass.config_entries.flow.async_configure(
            flow["flow_id"], {**CREDS, "password": "new-password"}
        )
        await hass.async_block_till_done()
    assert result["type"] == FlowResultType.ABORT
    assert entry.data["password"] == "new-password"
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


async def test_reconfigure_cannot_replace_account(hass, account_data):
    entry = MockConfigEntry(domain=DOMAIN, unique_id="different-account", data=CREDS)
    entry.add_to_hass(hass)
    with patch(
        "custom_components.avtodor.config_flow.AvtodorClient.async_get_data",
        return_value=account_data,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": SOURCE_RECONFIGURE,
                "entry_id": entry.entry_id,
                "unique_id": entry.unique_id,
            },
            data=CREDS,
        )
    assert result["reason"] == "wrong_account"


async def test_options(hass):
    entry = MockConfigEntry(domain=DOMAIN, unique_id="99", data=CREDS)
    entry.add_to_hass(hass)
    with patch(
        "homeassistant.config_entries.ConfigEntries.async_reload", return_value=True
    ):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["type"] == FlowResultType.FORM
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_UPDATE_INTERVAL: 15}
        )
        await hass.async_block_till_done()
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_UPDATE_INTERVAL] == 15
