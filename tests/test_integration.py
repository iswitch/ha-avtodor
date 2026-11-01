"""Работа сенсора, восстановление связи и выгрузка."""

from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.avtodor.api import AvtodorAuthError, AvtodorConnectionError
from custom_components.avtodor.const import DOMAIN

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


async def test_sensor_refresh_errors_and_unload(hass, account_data):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="99",
        data={"username": "example", "password": "password"},
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.avtodor.api.AvtodorClient.async_get_data",
        return_value=account_data,
    ) as fetch:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        entity = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)[
            0
        ]
        assert entity.unique_id == "99_123_balance"
        state = hass.states.get(entity.entity_id)
        assert state.state == "1859.25"
        assert state.attributes["unit_of_measurement"] == "RUB"
        assert "state_class" not in state.attributes

        fetch.side_effect = AvtodorConnectionError("HTTP 503")
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()
        assert hass.states.get(entity.entity_id).state == STATE_UNAVAILABLE

        fetch.side_effect = None
        updated = deepcopy(account_data)
        updated["contracts"]["123"]["balance"] = Decimal("-5.50")
        fetch.return_value = updated
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()
        assert hass.states.get(entity.entity_id).state == "-5.50"

        client = entry.runtime_data.client
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert client._session.closed


async def test_auth_failure_starts_reauth(hass, account_data):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="99",
        data={"username": "example", "password": "password"},
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.avtodor.api.AvtodorClient.async_get_data",
        return_value=account_data,
    ) as fetch:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        fetch.side_effect = AvtodorAuthError("Rejected")
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress()
    assert any(flow["context"]["source"] == "reauth" for flow in flows)


async def test_scheduled_refresh_and_stop_after_unload(hass, account_data):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="99",
        data={"username": "example", "password": "password"},
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.avtodor.api.AvtodorClient.async_get_data",
        return_value=account_data,
    ) as fetch:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert fetch.call_count == 1

        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=301))
        await hass.async_block_till_done()
        assert fetch.call_count == 2

        assert await hass.config_entries.async_unload(entry.entry_id)
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=10))
        await hass.async_block_till_done()
        assert fetch.call_count == 2


async def test_extra_sensors_partial_failure_and_discovery(hass, account_data):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="99",
        data={"username": "example", "password": "password"},
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.avtodor.api.AvtodorClient.async_get_data",
        return_value=account_data,
    ) as fetch:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        entities = {
            entity.unique_id: entity.entity_id
            for entity in er.async_entries_for_config_entry(
                er.async_get(hass), entry.entry_id
            )
        }
        assert len(entities) == 7
        bonus = hass.states.get(entities["99_123_loyalty_member_balance"])
        assert bonus.state == "150"
        assert bonus.attributes["unit_of_measurement"] == "points"
        assert hass.states.get(entities["99_transponder_7_status"]).state == "valid"
        assert (
            hass.states.get(entities["99_transponder_7_interoperability"]).state
            == "connected"
        )
        assert (
            hass.states.get(entities["99_vehicle_test-vehicle_plate"]).state
            == "А000АА00"
        )
        assert (
            hass.states.get(entities["99_vehicle_test-vehicle_violations_count"]).state
            == "2"
        )
        debt = hass.states.get(entities["99_vehicle_test-vehicle_debt"])
        assert debt.state == "150.50"
        assert debt.attributes["violations_count"] == 2
        assert debt.attributes["unit_of_measurement"] == "RUB"

        failed = deepcopy(account_data)
        failed["contracts"]["123"]["devices"] = None
        failed["vehicles"] = None
        fetch.return_value = failed
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()
        assert hass.states.get(entities["99_123_balance"]).state == "1859.25"
        assert hass.states.get(entities["99_123_loyalty_member_balance"]).state == "150"
        assert (
            hass.states.get(entities["99_transponder_7_status"]).state
            == STATE_UNAVAILABLE
        )
        assert (
            hass.states.get(entities["99_vehicle_test-vehicle_debt"]).state
            == STATE_UNAVAILABLE
        )

        updated = deepcopy(account_data)
        updated["contracts"]["123"]["devices"]["7"]["status"] = "blocked"
        updated["contracts"]["123"]["devices"]["7"]["interoperability"] = (
            "not_supported"
        )
        updated["contracts"]["123"]["devices"]["8"] = {
            **updated["contracts"]["123"]["devices"]["7"],
            "pan": "SECOND-TRANSPONDER",
        }
        updated["vehicles"]["test-vehicle"]["debt"] = Decimal("0")
        updated["vehicles"]["test-vehicle"]["plate"] = "А001АА00"
        updated["vehicles"]["test-vehicle"]["violations_count"] = 0
        updated["vehicles"]["second-vehicle"] = {
            **updated["vehicles"]["test-vehicle"],
            "plate": "В000ВВ00",
        }
        fetch.return_value = updated
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()
        assert hass.states.get(entities["99_transponder_7_status"]).state == "blocked"
        assert (
            hass.states.get(entities["99_transponder_7_interoperability"]).state
            == "not_supported"
        )
        assert hass.states.get(entities["99_vehicle_test-vehicle_debt"]).state == "0"
        assert (
            hass.states.get(entities["99_vehicle_test-vehicle_plate"]).state
            == "А001АА00"
        )
        assert (
            hass.states.get(entities["99_vehicle_test-vehicle_violations_count"]).state
            == "0"
        )
        assert (
            len(er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id))
            == 12
        )

        updated["contracts"]["123"]["devices"].pop("7")
        updated["vehicles"].pop("test-vehicle")
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()
        assert (
            hass.states.get(entities["99_transponder_7_status"]).state
            == STATE_UNAVAILABLE
        )
        assert (
            hass.states.get(entities["99_vehicle_test-vehicle_debt"]).state
            == STATE_UNAVAILABLE
        )
        assert (
            len(er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id))
            == 12
        )
        assert await hass.config_entries.async_unload(entry.entry_id)
