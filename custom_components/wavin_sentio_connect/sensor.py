"""Measurements and states of the controller, its rooms and its peripherals."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_device_registry_updated_event
from modbus_event_connect import Key

from wavin_sentio_connect import (
    BlockingSource,
    HeatingCoolingMode,
    LocationPointKey,
    ModbusMode,
    PeripheralPointKey,
    PointKey,
    RoomModeOverride,
    RoomPointKey,
    RoomState,
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
from .units import ha_unit

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class SentioSensorDescription(SentioEntityDescription, SensorEntityDescription):
    """A sensor of one point."""


def _enum(
    scope: Scope,
    point: Key[Any] | PointKey[Any],
    states: type[IntEnum],
    *,
    diagnostic: bool = False,
    enabled: bool = True,
) -> SentioSensorDescription:
    return SentioSensorDescription(
        key=point_name(point),
        translation_key=point_name(point),
        scope=scope,
        point=point,
        device_class=SensorDeviceClass.ENUM,
        options=[state.name.lower() for state in states],
        entity_category=EntityCategory.DIAGNOSTIC if diagnostic else None,
        entity_registry_enabled_default=enabled,
    )


def _measurement(
    point: PointKey[float], device_class: SensorDeviceClass
) -> SentioSensorDescription:
    return SentioSensorDescription(
        key=point.name,
        translation_key=point.name,
        scope=Scope.ROOM,
        point=point,
        device_class=device_class,
        state_class=SensorStateClass.MEASUREMENT,
    )


PLACE = SentioSensorDescription(
    key=PeripheralPointKey.OWNER.name,
    translation_key=PeripheralPointKey.OWNER.name,
    scope=Scope.PERIPHERAL,
    point=PeripheralPointKey.OWNER,
    entity_category=EntityCategory.DIAGNOSTIC,
)
"""The room a peripheral belongs to, or the controller itself."""

SENSORS: tuple[SentioSensorDescription, ...] = (
    PLACE,
    _enum(Scope.LOCATION, LocationPointKey.HEATING_COOLING_MODE, HeatingCoolingMode),
    _enum(Scope.LOCATION, LocationPointKey.MODBUS_MODE, ModbusMode, diagnostic=True),
    _measurement(RoomPointKey.TEMP_AIR_CURRENT, SensorDeviceClass.TEMPERATURE),
    # What the room regulates to now, which the thermostat also shows; as a sensor it gets
    # long-term statistics.
    _measurement(RoomPointKey.TEMP_AIR_TARGET_ACTIVE, SensorDeviceClass.TEMPERATURE),
    _measurement(RoomPointKey.TEMP_FLOOR_CURRENT, SensorDeviceClass.TEMPERATURE),
    _measurement(RoomPointKey.HUMIDITY_CURRENT, SensorDeviceClass.HUMIDITY),
    _measurement(RoomPointKey.DEW_POINT_CURRENT, SensorDeviceClass.TEMPERATURE),
    _enum(Scope.ROOM, RoomPointKey.STATE, RoomState),
    _enum(Scope.ROOM, RoomPointKey.BLOCKING_SOURCE, BlockingSource),
    _enum(Scope.ROOM, RoomPointKey.RADIATORS_STATE, RoomState, enabled=False),
    _enum(Scope.ROOM, RoomPointKey.UFHC_STATE, RoomState, enabled=False),
    _enum(Scope.ROOM, RoomPointKey.THERMAL_INTEGRATION_STATE, RoomState, enabled=False),
    _enum(
        Scope.ROOM,
        RoomPointKey.BLOCKING_SOURCE_RADIATORS,
        BlockingSource,
        enabled=False,
    ),
    _enum(Scope.ROOM, RoomPointKey.BLOCKING_SOURCE_UFHC, BlockingSource, enabled=False),
    _enum(
        Scope.ROOM, RoomPointKey.BLOCKING_SOURCE_DRYING, BlockingSource, enabled=False
    ),
    _enum(
        Scope.ROOM,
        RoomPointKey.BLOCKING_SOURCE_THERMAL_INTEGRATION,
        BlockingSource,
        enabled=False,
    ),
    _enum(
        Scope.ROOM,
        RoomPointKey.BLOCKING_SOURCE_VENTILATION,
        BlockingSource,
        enabled=False,
    ),
    _enum(Scope.ROOM, RoomPointKey.MODE_OVERRIDE, RoomModeOverride, diagnostic=True),
    SentioSensorDescription(
        key=PeripheralPointKey.SIGNAL_STRENGTH.name,
        translation_key=PeripheralPointKey.SIGNAL_STRENGTH.name,
        scope=Scope.PERIPHERAL,
        point=PeripheralPointKey.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SentioConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a sensor for every described point the installation has."""
    data = entry.runtime_data
    async_add_entities(
        (SentioPlace if description is PLACE else SentioSensor)(data, target, description)
        for target, description in all_targets(data, SENSORS)
    )


class SentioSensor(SentioEntity, SensorEntity):
    """The value of one point."""

    def __init__(
        self, data: SentioData, target: Target, description: SentioSensorDescription
    ) -> None:
        super().__init__(data, target)
        self.entity_description = description
        self._attr_native_unit_of_measurement = ha_unit(data.client, target.key)

    def _show(self) -> None:
        """The point's value; a state as its lower-case name."""
        value = self._current(self._key)
        if isinstance(value, IntEnum):
            self._attr_native_value = value.name.lower()
        elif isinstance(value, int | float) and not isinstance(value, bool):
            self._attr_native_value = value
        else:
            self._attr_native_value = None


class SentioPlace(SentioSensor):
    """Where a peripheral belongs: the name Home Assistant shows for that room, or for the
    controller, kept current as it is renamed; unknown for a place the installation lacks."""

    def __init__(
        self, data: SentioData, target: Target, description: SentioSensorDescription
    ) -> None:
        self._places = data.places
        self._registry: dr.DeviceRegistry | None = None
        super().__init__(data, target, description)

    async def async_added_to_hass(self) -> None:
        self._registry = dr.async_get(self.hass)
        self.async_on_remove(
            async_track_device_registry_updated_event(
                self.hass, set(self._places.values()), self._on_place_updated
            )
        )
        await super().async_added_to_hass()

    @callback
    def _on_place_updated(self, event: Event[dr.EventDeviceRegistryUpdatedData]) -> None:
        self._changed()

    def _show(self) -> None:
        owner = self._current(self._key)
        device_id = self._places.get(owner) if owner is not None else None
        place = (
            self._registry.async_get(device_id)
            if self._registry is not None and device_id is not None
            else None
        )
        self._attr_native_value = (place.name_by_user or place.name) if place else None
