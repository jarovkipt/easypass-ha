"""Privacy-safe diagnostics for Thai Easy Pass."""

from typing import Any

from homeassistant.core import HomeAssistant

from . import EasyPassConfigEntry
from .const import DEFAULT_UPDATE_INTERVAL, DOMAIN


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: EasyPassConfigEntry
) -> dict[str, Any]:
    """Return diagnostics without credentials, identifiers, or portal payloads."""
    coordinator = entry.runtime_data.coordinator
    return {
        "domain": DOMAIN,
        "update_interval_minutes": int(
            DEFAULT_UPDATE_INTERVAL.total_seconds() // 60
        ),
        "last_update_success": coordinator.last_update_success,
        "card_count": len(coordinator.data),
        "cards": [
            {"usage_available": item.usage_available}
            for item in coordinator.data.values()
        ],
    }

