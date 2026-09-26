"""Warnings and errors of the controller, its rooms and its peripherals."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from modbus_event_connect import Key

from wavin_sentio_connect import (
    LocationPointKey,
    PeripheralPointKey,
    PointKey,
    RoomPointKey,
)

from .data import SentioConfigEntry, SentioData
from .entity import (
    Scope,
    SentioEntity,
    SentioEntityDescription,
    Target,
    all_targets,
    point_name,
)

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class SentioBinarySensorDescription(
    SentioEntityDescription, BinarySensorEntityDescription
):
    """A binary sensor of one alarm bit."""


def _alarm(
    scope: Scope,
    point: Key[Any] | PointKey[Any],
    device_class: BinarySensorDeviceClass,
) -> SentioBinarySensorDescription:
    return SentioBinarySensorDescription(
        key=point_name(point),
        translation_key=point_name(point),
        scope=scope,
        point=point,
        device_class=device_class,
        entity_category=EntityCategory.DIAGNOSTIC,
    )


_PROBLEM = BinarySensorDeviceClass.PROBLEM
_BATTERY = BinarySensorDeviceClass.BATTERY

BINARY_SENSORS: tuple[SentioBinarySensorDescription, ...] = (
    _alarm(Scope.LOCATION, LocationPointKey.SYSTEM_WARNING, _PROBLEM),
    _alarm(Scope.LOCATION, LocationPointKey.SYSTEM_ERROR, _PROBLEM),
    _alarm(Scope.ROOM, RoomPointKey.WARNING, _PROBLEM),
    _alarm(Scope.ROOM, RoomPointKey.ERROR, _PROBLEM),
    _alarm(Scope.ROOM, RoomPointKey.LOW_BATTERY, _BATTERY),
    _alarm(Scope.ROOM, RoomPointKey.PERIPHERAL_LOST, _PROBLEM),
    _alarm(Scope.PERIPHERAL, PeripheralPointKey.WARNING, _PROBLEM),
    _alarm(Scope.PERIPHERAL, PeripheralPointKey.ERROR, _PROBLEM),
    _alarm(Scope.PERIPHERAL, PeripheralPointKey.LOW_BATTERY, _BATTERY),
    _alarm(Scope.PERIPHERAL, PeripheralPointKey.LOST, _PROBLEM),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SentioConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a binary sensor for every alarm bit the installation has."""
    data = entry.runtime_data
    async_add_entities(
        SentioBinarySensor(data, target, description)
        for target, description in all_targets(data, BINARY_SENSORS)
    )


class SentioBinarySensor(SentioEntity, BinarySensorEntity):
    """One alarm bit: on while the controller reports the problem."""

    def __init__(
        self,
        data: SentioData,
        target: Target,
        description: SentioBinarySensorDescription,
    ) -> None:
        super().__init__(data, target)
        self.entity_description = description

    def _show(self) -> None:
        value = self._current(self._key)
        self._attr_is_on = value if isinstance(value, bool) else None
