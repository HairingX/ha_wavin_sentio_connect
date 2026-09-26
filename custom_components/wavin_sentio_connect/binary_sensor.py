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

from wavin_sentio_connect import (
    BoilerHeatPumpPointKey,
    BufferTankPointKey,
    DehumidifierPointKey,
    DhwTankPointKey,
    HccPointKey,
    HeatingCoolingSourcePointKey,
    ItcPointKey,
    Key,
    LocationPointKey,
    OutdoorPointKey,
    PeripheralPointKey,
    PointKey,
    RoomPointKey,
    VentilationPointKey,
)

from .data import SentioConfigEntry, SentioData
from .entity import (
    Scope,
    SentioEntity,
    SentioEntityDescription,
    Target,
    all_targets,
    entity_key,
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
        key=entity_key(scope, point),
        translation_key=entity_key(scope, point),
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
    _alarm(Scope.OUTDOOR, OutdoorPointKey.WARNING, _PROBLEM),
    _alarm(Scope.OUTDOOR, OutdoorPointKey.ERROR, _PROBLEM),
    _alarm(Scope.OUTDOOR, OutdoorPointKey.LOW_BATTERY, _BATTERY),
    _alarm(Scope.OUTDOOR, OutdoorPointKey.PERIPHERAL_LOST, _PROBLEM),
    _alarm(Scope.HCC, HccPointKey.WARNING, _PROBLEM),
    _alarm(Scope.HCC, HccPointKey.ERROR, _PROBLEM),
    _alarm(Scope.HCC, HccPointKey.INLET_SENSOR_FAILURE, _PROBLEM),
    _alarm(Scope.HCC, HccPointKey.HIGH_TEMP_CUTOFF_ACTIVE, _PROBLEM),
    _alarm(Scope.ITC, ItcPointKey.WARNING, _PROBLEM),
    _alarm(Scope.ITC, ItcPointKey.ERROR, _PROBLEM),
    _alarm(Scope.ITC, ItcPointKey.INLET_SENSOR_FAILURE, _PROBLEM),
    _alarm(Scope.ITC, ItcPointKey.HIGH_TEMP_CUTOFF_ACTIVE, _PROBLEM),
    _alarm(Scope.ITC, ItcPointKey.SERVO_FAILURE, _PROBLEM),
    _alarm(Scope.ITC, ItcPointKey.RETURN_SENSOR_FAILURE, _PROBLEM),
    _alarm(Scope.ITC, ItcPointKey.OUTDOOR_SENSOR_FAILURE, _PROBLEM),
    _alarm(Scope.ITC, ItcPointKey.FROST_PROTECTION_ACTIVE, _PROBLEM),
    _alarm(Scope.HC_SOURCE, HeatingCoolingSourcePointKey.WARNING, _PROBLEM),
    _alarm(Scope.HC_SOURCE, HeatingCoolingSourcePointKey.ERROR, _PROBLEM),
    _alarm(Scope.HC_SOURCE, HeatingCoolingSourcePointKey.FAILURE, _PROBLEM),
    _alarm(Scope.BOILER_HEAT_PUMP, BoilerHeatPumpPointKey.WARNING, _PROBLEM),
    _alarm(Scope.BOILER_HEAT_PUMP, BoilerHeatPumpPointKey.ERROR, _PROBLEM),
    _alarm(
        Scope.BOILER_HEAT_PUMP, BoilerHeatPumpPointKey.INLET_SENSOR_FAILURE, _PROBLEM
    ),
    _alarm(Scope.BOILER_HEAT_PUMP, BoilerHeatPumpPointKey.FAILURE, _PROBLEM),
    _alarm(Scope.BUFFER_TANK, BufferTankPointKey.WARNING, _PROBLEM),
    _alarm(Scope.BUFFER_TANK, BufferTankPointKey.ERROR, _PROBLEM),
    _alarm(Scope.BUFFER_TANK, BufferTankPointKey.INLET_SENSOR_FAILURE, _PROBLEM),
    _alarm(Scope.BUFFER_TANK, BufferTankPointKey.PRIORITY_SENSOR_FAILURE, _PROBLEM),
    _alarm(Scope.BUFFER_TANK, BufferTankPointKey.UPPER_SENSOR_FAILURE, _PROBLEM),
    _alarm(Scope.BUFFER_TANK, BufferTankPointKey.LOWER_SENSOR_FAILURE, _PROBLEM),
    _alarm(Scope.DHW_TANK, DhwTankPointKey.WARNING, _PROBLEM),
    _alarm(Scope.DHW_TANK, DhwTankPointKey.ERROR, _PROBLEM),
    _alarm(Scope.DHW_TANK, DhwTankPointKey.CLEANING_FAILED, _PROBLEM),
    _alarm(Scope.DHW_TANK, DhwTankPointKey.TANK_SENSOR_FAILURE, _PROBLEM),
    _alarm(Scope.DHW_TANK, DhwTankPointKey.CIRCULATION_RETURN_SENSOR_FAILURE, _PROBLEM),
    _alarm(Scope.DHW_TANK, DhwTankPointKey.SOURCE_RETURN_SENSOR_FAILURE, _PROBLEM),
    _alarm(Scope.DHW_TANK, DhwTankPointKey.SOURCE_INLET_SENSOR_FAILURE, _PROBLEM),
    _alarm(Scope.DHW_TANK, DhwTankPointKey.SOURCE_INLET_TEMP_TOO_LOW, _PROBLEM),
    _alarm(Scope.DHW_TANK, DhwTankPointKey.LOW_BATTERY, _BATTERY),
    _alarm(Scope.DHW_TANK, DhwTankPointKey.PERIPHERAL_LOST, _PROBLEM),
    _alarm(Scope.VENTILATION, VentilationPointKey.WARNING, _PROBLEM),
    _alarm(Scope.VENTILATION, VentilationPointKey.ERROR, _PROBLEM),
    _alarm(Scope.VENTILATION, VentilationPointKey.AIR_FILTER_EXPIRED, _PROBLEM),
    _alarm(Scope.VENTILATION, VentilationPointKey.AIR_FILTER_YEAR_PASSED, _PROBLEM),
    _alarm(Scope.VENTILATION, VentilationPointKey.DEVICE_WARNING, _PROBLEM),
    _alarm(Scope.VENTILATION, VentilationPointKey.DEVICE_FAULT, _PROBLEM),
    _alarm(Scope.VENTILATION, VentilationPointKey.COMMUNICATION_ERROR, _PROBLEM),
    _alarm(Scope.VENTILATION, VentilationPointKey.NOT_COMPATIBLE, _PROBLEM),
    _alarm(Scope.VENTILATION, VentilationPointKey.DEVICE_ERROR, _PROBLEM),
    _alarm(Scope.DEHUMIDIFIER, DehumidifierPointKey.WARNING, _PROBLEM),
    _alarm(Scope.DEHUMIDIFIER, DehumidifierPointKey.ERROR, _PROBLEM),
    _alarm(Scope.DEHUMIDIFIER, DehumidifierPointKey.AIR_FILTER_EXPIRED, _PROBLEM),
    _alarm(Scope.DEHUMIDIFIER, DehumidifierPointKey.AIR_FILTER_YEAR_PASSED, _PROBLEM),
    _alarm(Scope.DEHUMIDIFIER, DehumidifierPointKey.HCW_SUPPLIER_NOT_SET, _PROBLEM),
    _alarm(Scope.DEHUMIDIFIER, DehumidifierPointKey.DEVICE_FAULT, _PROBLEM),
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
