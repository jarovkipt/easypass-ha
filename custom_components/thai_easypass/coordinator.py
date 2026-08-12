"""Data update coordinator for Thai Easy Pass."""

from datetime import datetime
from typing import override

from homeassistant.config_entries import ConfigEntryAuthFailed
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    BANGKOK,
    CannotConnect,
    EasyPassClient,
    EasyPassError,
    InvalidAuth,
    SessionExpired,
    TwoFactorUnsupported,
)
from .const import DEFAULT_UPDATE_INTERVAL, DOMAIN, LOGGER
from .models import AccountSnapshot, CardSnapshot


class EasyPassCoordinator(DataUpdateCoordinator[AccountSnapshot]):
    """Coordinate a single account poll across all cards and entities."""

    def __init__(self, hass: HomeAssistant, entry, client: EasyPassClient) -> None:
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=DEFAULT_UPDATE_INTERVAL,
            always_update=False,
        )
        self.client = client

    async def _async_collect(self) -> AccountSnapshot:
        cards, token = await self.client.async_fetch_cards_with_token()
        today = datetime.now(BANGKOK).date()
        snapshot: AccountSnapshot = {}

        for card in cards:
            usage = None
            usage_available = False
            if card.account_number:
                try:
                    usage = await self.client.async_fetch_usage(
                        token, card.account_number, today
                    )
                    usage_available = True
                except (SessionExpired, InvalidAuth, TwoFactorUnsupported):
                    raise
                except EasyPassError:
                    # Keep balance entities healthy when a per-card usage call fails.
                    LOGGER.warning(
                        "Unable to update monthly usage for one Easy Pass card"
                    )
            snapshot[card.card_id] = CardSnapshot(
                card=card,
                usage=usage,
                usage_available=usage_available,
            )
        return snapshot

    @override
    async def _async_update_data(self) -> AccountSnapshot:
        try:
            return await self._async_collect()
        except SessionExpired:
            # A stale session gets one login and one collection retry. Fatal auth
            # outcomes below stop coordinator retries and launch Home Assistant reauth.
            try:
                await self.client.async_login()
                return await self._async_collect()
            except (SessionExpired, InvalidAuth, TwoFactorUnsupported) as err:
                raise ConfigEntryAuthFailed from err
            except CannotConnect as err:
                raise UpdateFailed("Unable to communicate with Easy Pass") from err
        except (InvalidAuth, TwoFactorUnsupported) as err:
            raise ConfigEntryAuthFailed from err
        except CannotConnect as err:
            raise UpdateFailed("Unable to communicate with Easy Pass") from err
