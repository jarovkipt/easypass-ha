"""Tests for coordinator failure isolation and sensor semantics."""

from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.sensor import SensorStateClass
from homeassistant.config_entries import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.thai_easypass.api import (
    BANGKOK,
    CannotConnect,
    EasyPassClient,
    InvalidAuth,
)
from custom_components.thai_easypass.const import CONF_PASSWORD, CONF_USERNAME, DOMAIN
from custom_components.thai_easypass.coordinator import EasyPassCoordinator
from custom_components.thai_easypass.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.thai_easypass.models import CardInfo, CardSnapshot, UsageSummary
from custom_components.thai_easypass.sensor import SENSORS, EasyPassSensor


def fake_card(card_id: str = "9000000001") -> CardInfo:
    return CardInfo(
        card_id=card_id,
        account_number=f"ACCOUNT-{card_id[-1]}",
        balance=Decimal("200.00"),
        card_name="Synthetic card",
    )


def fake_usage() -> UsageSummary:
    return UsageSummary(
        toll_total=Decimal("75.00"),
        topup_total=Decimal("500.00"),
        other_total=Decimal("0.00"),
        trip_count=2,
        last_trip=None,
        period_start=datetime(2026, 8, 1, tzinfo=BANGKOK),
    )


@pytest.mark.asyncio
async def test_usage_failure_does_not_hide_balance(hass) -> None:
    client = AsyncMock()
    client.async_fetch_cards_with_token.return_value = ([fake_card()], "token")
    client.async_fetch_usage.side_effect = CannotConnect
    coordinator = EasyPassCoordinator(
        hass, MockConfigEntry(domain=DOMAIN), client
    )

    result = await coordinator._async_collect()

    assert result["9000000001"].card.balance == Decimal("200.00")
    assert result["9000000001"].usage is None
    assert result["9000000001"].usage_available is False


@pytest.mark.asyncio
async def test_invalid_auth_stops_coordinator(hass) -> None:
    client = AsyncMock()
    client.async_fetch_cards_with_token.side_effect = InvalidAuth
    coordinator = EasyPassCoordinator(
        hass, MockConfigEntry(domain=DOMAIN), client
    )

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()
    client.async_login.assert_not_awaited()


def test_sensor_state_classes_and_partial_availability() -> None:
    snapshot = CardSnapshot(fake_card(), fake_usage(), True)
    coordinator = AsyncMock()
    coordinator.data = {"9000000001": snapshot}
    coordinator.last_update_success = True

    by_key = {description.key: description for description in SENSORS}
    balance = EasyPassSensor(coordinator, "9000000001", by_key["balance"])
    toll = EasyPassSensor(
        coordinator, "9000000001", by_key["toll_this_month"]
    )

    assert balance.native_value == Decimal("200.00")
    assert balance.available is True
    assert toll.native_value == Decimal("75.00")
    assert toll.last_reset == datetime(2026, 8, 1, tzinfo=BANGKOK)
    assert toll.entity_description.state_class is SensorStateClass.TOTAL
    assert by_key["topup_this_month"].state_class is SensorStateClass.TOTAL
    assert by_key["trips_this_month"].state_class is SensorStateClass.TOTAL_INCREASING

    coordinator.data = {
        "9000000001": CardSnapshot(fake_card(), None, False)
    }
    assert balance.available is True
    assert toll.available is False


@pytest.mark.asyncio
async def test_full_entry_setup_creates_every_card_and_safe_diagnostics(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="synthetic-user",
        data={CONF_USERNAME: "synthetic-user", CONF_PASSWORD: "secret-value"},
    )
    entry.add_to_hass(hass)
    cards = [fake_card("9000000001"), fake_card("9000000002")]

    with (
        patch.object(
            EasyPassClient,
            "async_fetch_cards_with_token",
            new=AsyncMock(return_value=(cards, "synthetic-token")),
        ),
        patch.object(
            EasyPassClient,
            "async_fetch_usage",
            new=AsyncMock(return_value=fake_usage()),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        entity_entries = er.async_entries_for_config_entry(
            er.async_get(hass), entry.entry_id
        )
        device_entries = dr.async_entries_for_config_entry(
            dr.async_get(hass), entry.entry_id
        )
        diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert len(entity_entries) == 10
    assert len(device_entries) == 2
    assert diagnostics["card_count"] == 2
    serialized = repr(diagnostics)
    assert "synthetic-user" not in serialized
    assert "secret-value" not in serialized
    assert "9000000001" not in serialized

    assert await hass.config_entries.async_unload(entry.entry_id)
