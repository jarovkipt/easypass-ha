"""Base entity for Thai Easy Pass."""

from typing import override

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import EasyPassCoordinator
from .models import CardSnapshot


class EasyPassEntity(CoordinatorEntity[EasyPassCoordinator]):
    """Base class for an entity belonging to one Easy Pass card."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: EasyPassCoordinator, card_id: str) -> None:
        super().__init__(coordinator, context=card_id)
        self.card_id = card_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, card_id)},
            name=f"Easy Pass {card_id}",
            manufacturer=MANUFACTURER,
            model=MODEL,
            serial_number=card_id,
        )

    @property
    def snapshot(self) -> CardSnapshot | None:
        """Return current in-memory data for this card."""
        return self.coordinator.data.get(self.card_id)

    @property
    @override
    def available(self) -> bool:
        return super().available and self.snapshot is not None

