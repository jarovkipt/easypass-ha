"""Tests for setup and reauthentication flows."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.thai_easypass.api import InvalidAuth, TwoFactorUnsupported
from custom_components.thai_easypass.const import DOMAIN


@pytest.mark.asyncio
async def test_user_flow_success(hass) -> None:
    with patch(
        "custom_components.thai_easypass.config_flow._async_validate",
        new=AsyncMock(),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] is FlowResultType.FORM

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: " Test@Example.com ", CONF_PASSWORD: "secret"},
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Thai Easy Pass"
    assert result["data"][CONF_USERNAME] == "Test@Example.com"
    assert result["data"][CONF_PASSWORD] == "secret"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("exception", "error"),
    [
        (InvalidAuth, "invalid_auth"),
        (TwoFactorUnsupported, "two_factor_unsupported"),
    ],
)
async def test_user_flow_fatal_login_errors(hass, exception, error) -> None:
    with patch(
        "custom_components.thai_easypass.config_flow._async_validate",
        new=AsyncMock(side_effect=exception),
    ) as validate:
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={CONF_USERNAME: "test-user", CONF_PASSWORD: "wrong"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}
    validate.assert_awaited_once()


@pytest.mark.asyncio
async def test_duplicate_account_is_blocked_case_insensitively(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="test@example.com",
        data={CONF_USERNAME: "test@example.com", CONF_PASSWORD: "secret"},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
        data={CONF_USERNAME: "TEST@example.com", CONF_PASSWORD: "secret"},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.asyncio
async def test_reauth_updates_only_password(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="test-user",
        data={CONF_USERNAME: "test-user", CONF_PASSWORD: "old"},
    )
    entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.thai_easypass.config_flow._async_validate",
            new=AsyncMock(),
        ),
        patch(
            "homeassistant.config_entries.ConfigEntries.async_reload",
            new=AsyncMock(return_value=True),
        ),
    ):
        result = await entry.start_reauth_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PASSWORD: "new"}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data == {CONF_USERNAME: "test-user", CONF_PASSWORD: "new"}
