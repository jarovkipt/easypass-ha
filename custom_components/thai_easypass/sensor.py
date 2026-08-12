"""Sensor entities for Thai Easy Pass."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, override

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.core import callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from . import EasyPassConfigEntry
from .entity import EasyPassEntity
from .models import CardSnapshot


@dataclass(frozen=True, kw_only=True)
class EasyPassSensorDescription(SensorEntityDescription):
    """Describe an Easy Pass sensor."""

    value_fn: Callable[[CardSnapshot], StateType]
    attributes_fn: Callable[[CardSnapshot], Mapping[str, Any]] | None = None
    usage_required: bool = False
    month_reset: bool = False


SENSORS: tuple[EasyPassSensorDescription, ...] = (
    EasyPassSensorDescription(
        key="balance",
        translation_key="balance",
        icon="mdi:highway",
        native_unit_of_measurement="THB",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        value_fn=lambda item: item.card.balance,
        attributes_fn=lambda item: {
            key: value
            for key, value in {
                "card_name": item.card.card_name,
                "tag_status": item.card.tag_status,
                "tag_action": item.card.tag_action,
                "plate_no": item.card.plate_no,
                "car_model": item.card.car_model,
                "car_color": item.card.car_color,
                "account_status": item.card.account_status,
            }.items()
            if value is not None
        },
    ),
    EasyPassSensorDescription(
        key="toll_this_month",
        translation_key="toll_this_month",
        icon="mdi:cash-minus",
        native_unit_of_measurement="THB",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        value_fn=lambda item: item.usage.toll_total if item.usage else None,
        usage_required=True,
        month_reset=True,
    ),
    EasyPassSensorDescription(
        key="topup_this_month",
        translation_key="topup_this_month",
        icon="mdi:cash-plus",
        native_unit_of_measurement="THB",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        value_fn=lambda item: item.usage.topup_total if item.usage else None,
        usage_required=True,
        month_reset=True,
    ),
    EasyPassSensorDescription(
        key="trips_this_month",
        translation_key="trips_this_month",
        icon="mdi:car-multiple",
        native_unit_of_measurement="trips",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda item: item.usage.trip_count if item.usage else None,
        usage_required=True,
    ),
    EasyPassSensorDescription(
        key="last_trip",
        translation_key="last_trip",
        icon="mdi:boom-gate-up",
        value_fn=lambda item: (
            item.usage.last_trip.location
            if item.usage and item.usage.last_trip
            else None
        ),
        attributes_fn=lambda item: (
            {
                "occurred_at": item.usage.last_trip.occurred_at,
                "position": item.usage.last_trip.position,
                "amount": item.usage.last_trip.amount,
                "balance_after": item.usage.last_trip.balance_after,
            }
            if item.usage and item.usage.last_trip
            else {}
        ),
        usage_required=True,
    ),
)


async def async_setup_entry(
    hass,
    entry: EasyPassConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors and discover cards added after initial setup."""
    coordinator = entry.runtime_data.coordinator
    known_cards: set[str] = set()

    @callback
    def add_new_cards() -> None:
        new_cards = set(coordinator.data) - known_cards
        if not new_cards:
            return
        async_add_entities(
            EasyPassSensor(coordinator, card_id, description)
            for card_id in sorted(new_cards)
            for description in SENSORS
        )
        known_cards.update(new_cards)

    add_new_cards()
    entry.async_on_unload(coordinator.async_add_listener(add_new_cards))


class EasyPassSensor(EasyPassEntity, SensorEntity):
    """One sensor attached to an Easy Pass card."""

    entity_description: EasyPassSensorDescription

    def __init__(
        self,
        coordinator,
        card_id: str,
        description: EasyPassSensorDescription,
    ) -> None:
        super().__init__(coordinator, card_id)
        self.entity_description = description
        self._attr_unique_id = f"{card_id}_{description.key}"

    @property
    @override
    def available(self) -> bool:
        if not super().available:
            return False
        return not self.entity_description.usage_required or bool(
            self.snapshot and self.snapshot.usage_available
        )

    @property
    @override
    def native_value(self) -> StateType:
        if self.snapshot is None:
            return None
        return self.entity_description.value_fn(self.snapshot)

    @property
    @override
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        if self.snapshot is None or self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(self.snapshot)

    @property
    @override
    def last_reset(self) -> datetime | None:
        if (
            self.entity_description.month_reset
            and self.snapshot
            and self.snapshot.usage
        ):
            return self.snapshot.usage.period_start
        return None
