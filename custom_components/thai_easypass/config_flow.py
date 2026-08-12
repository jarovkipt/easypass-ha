"""Config flow for Thai Easy Pass."""

from collections.abc import Mapping
from typing import Any, override

import voluptuous as vol
from aiohttp import CookieJar
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    CannotConnect,
    EasyPassClient,
    InvalidAuth,
    NoCards,
    TwoFactorUnsupported,
)
from .const import CONF_PASSWORD, CONF_USERNAME, DOMAIN, LOGGER


def _password_selector() -> TextSelector:
    return TextSelector(
        TextSelectorConfig(
            type=TextSelectorType.PASSWORD,
            autocomplete="current-password",
        )
    )


def _user_schema(username: str | None = None) -> vol.Schema:
    username_key = (
        vol.Required(CONF_USERNAME, default=username)
        if username is not None
        else vol.Required(CONF_USERNAME)
    )
    return vol.Schema(
        {
            username_key: TextSelector(
                TextSelectorConfig(
                    type=TextSelectorType.TEXT,
                    autocomplete="username",
                )
            ),
            vol.Required(CONF_PASSWORD): _password_selector(),
        }
    )


async def _async_validate(hass, username: str, password: str) -> None:
    """Validate credentials with exactly one explicit login attempt."""
    session = async_create_clientsession(
        hass,
        auto_cleanup=False,
        cookie_jar=CookieJar(),
        headers={"Accept-Language": "th,en;q=0.9"},
    )
    try:
        client = EasyPassClient(session, username, password)
        await client.async_login()
        await client.async_fetch_cards()
    finally:
        session.detach()


class EasyPassConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Thai Easy Pass."""

    VERSION = 1

    async def _async_validate_input(
        self, user_input: dict[str, Any]
    ) -> dict[str, str]:
        try:
            await _async_validate(
                self.hass,
                user_input[CONF_USERNAME],
                user_input[CONF_PASSWORD],
            )
        except InvalidAuth:
            return {"base": "invalid_auth"}
        except TwoFactorUnsupported:
            return {"base": "two_factor_unsupported"}
        except NoCards:
            return {"base": "no_cards"}
        except CannotConnect:
            return {"base": "cannot_connect"}
        except Exception:
            LOGGER.exception("Unexpected exception while validating Easy Pass")
            return {"base": "unknown"}
        return {}

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Set up one Easy Pass account."""
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input[CONF_USERNAME] = user_input[CONF_USERNAME].strip()
            await self.async_set_unique_id(user_input[CONF_USERNAME].casefold())
            self._abort_if_unique_id_configured()
            errors = await self._async_validate_input(user_input)
            if not errors:
                return self.async_create_entry(
                    title="Thai Easy Pass",
                    data=user_input,
                )
        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(
                user_input.get(CONF_USERNAME) if user_input else None
            ),
            errors=errors,
        )

    @override
    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start reauthentication for a stopped account."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Validate a replacement password and reload the entry."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            candidate = {
                CONF_USERNAME: entry.data[CONF_USERNAME],
                CONF_PASSWORD: user_input[CONF_PASSWORD],
            }
            errors = await self._async_validate_input(candidate)
            if not errors:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]},
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {vol.Required(CONF_PASSWORD): _password_selector()}
            ),
            description_placeholders={"username": entry.data[CONF_USERNAME]},
            errors=errors,
        )
