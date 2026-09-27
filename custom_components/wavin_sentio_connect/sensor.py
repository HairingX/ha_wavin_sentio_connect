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

from wavin_sentio_connect import (
    BlockingSource,
    BoilerHeatPumpPointKey,
    BufferTankPointKey,
    CirculationState,
    DehumidifierPointKey,
    DhwTankPointKey,
    DhwTankState,
    DryingState,
    HccPointKey,
    HeatSourceState,
    HeatingCoolingMode,
    HeatingCoolingSourcePointKey,
    ItcPointKey,
    Key,
    LocationPointKey,
    ModbusMode,
    OutdoorPointKey,
    PeripheralPointKey,
    PointKey,
    PumpState,
    RoomModeOverride,
    RoomPointKey,
    RoomState,
    ThermistorPointKey,
    VentilationPointKey,
    VentilationState,
    VentilationUnitState,
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
        key=entity_key(scope, point),
        translation_key=entity_key(scope, point),
        scope=scope,
        point=point,
        device_class=SensorDeviceClass.ENUM,
        options=[state.name.lower() for state in states],
        entity_category=EntityCategory.DIAGNOSTIC if diagnostic else None,
        entity_registry_enabled_default=enabled,
    )


def _reading(
    scope: Scope,
    point: Key[Any] | PointKey[Any],
    device_class: SensorDeviceClass | None,
    *,
    enabled: bool = True,
    diagnostic: bool = False,
    measurement: bool = True,
) -> SentioSensorDescription:
    return SentioSensorDescription(
        key=entity_key(scope, point),
        translation_key=entity_key(scope, point),
        scope=scope,
        point=point,
        device_class=device_class,
        # A code is a number without an order, which has no statistics.
        state_class=SensorStateClass.MEASUREMENT if measurement else None,
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
    # A CCU-208 in Modbus TCP read and write reported this as disabled.
    _enum(
        Scope.LOCATION,
        LocationPointKey.MODBUS_MODE,
        ModbusMode,
        diagnostic=True,
        enabled=False,
    ),
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
    _enum(Scope.ROOM, RoomPointKey.DRYING_STATE, DryingState, enabled=False),
    _enum(Scope.ROOM, RoomPointKey.VENTILATION_STATE, VentilationState, enabled=False),
    _reading(Scope.OUTDOOR, OutdoorPointKey.AIR_TEMP, SensorDeviceClass.TEMPERATURE),
    _reading(
        Scope.OUTDOOR,
        OutdoorPointKey.AIR_TEMP_FILTERED,
        SensorDeviceClass.TEMPERATURE,
        diagnostic=True,
        enabled=False,
    ),
    _reading(
        Scope.OUTDOOR,
        OutdoorPointKey.AIR_TEMP_GEOMETRICAL,
        SensorDeviceClass.TEMPERATURE,
        diagnostic=True,
        enabled=False,
    ),
    _enum(Scope.HCC, HccPointKey.STATE, RoomState),
    _enum(Scope.HCC, HccPointKey.BLOCKING_SOURCE, BlockingSource),
    _enum(Scope.HCC, HccPointKey.PUMP_DEMAND, PumpState, enabled=False),
    _enum(Scope.HCC, HccPointKey.PUMP_STATE, PumpState),
    _reading(Scope.HCC, HccPointKey.TEMP_INLET_CURRENT, SensorDeviceClass.TEMPERATURE),
    _reading(Scope.HCC, HccPointKey.TEMP_INLET_TARGET, SensorDeviceClass.TEMPERATURE),
    _reading(
        Scope.HCC,
        HccPointKey.TEMP_ROOM_TARGET,
        SensorDeviceClass.TEMPERATURE,
        enabled=False,
    ),
    _enum(Scope.ITC, ItcPointKey.STATE, RoomState),
    _enum(Scope.ITC, ItcPointKey.BLOCKING_SOURCE, BlockingSource),
    _enum(Scope.ITC, ItcPointKey.PUMP_DEMAND, PumpState, enabled=False),
    _enum(Scope.ITC, ItcPointKey.PUMP_STATE, PumpState),
    _reading(Scope.ITC, ItcPointKey.TEMP_INLET_CURRENT, SensorDeviceClass.TEMPERATURE),
    _reading(Scope.ITC, ItcPointKey.TEMP_INLET_TARGET, SensorDeviceClass.TEMPERATURE),
    _reading(
        Scope.ITC,
        ItcPointKey.TEMP_ROOM_TARGET,
        SensorDeviceClass.TEMPERATURE,
        enabled=False,
    ),
    _reading(Scope.ITC, ItcPointKey.TEMP_RETURN_CURRENT, SensorDeviceClass.TEMPERATURE),
    _reading(
        Scope.ITC,
        ItcPointKey.TEMP_MAIN_SUPPLIER,
        SensorDeviceClass.TEMPERATURE,
        enabled=False,
    ),
    _reading(Scope.ITC, ItcPointKey.SERVO_POSITION_REQUEST, None, enabled=False),
    _enum(Scope.HC_SOURCE, HeatingCoolingSourcePointKey.STATE, RoomState),
    _enum(Scope.BOILER_HEAT_PUMP, BoilerHeatPumpPointKey.STATE, HeatSourceState),
    _enum(
        Scope.BOILER_HEAT_PUMP, BoilerHeatPumpPointKey.BLOCKING_SOURCE, BlockingSource
    ),
    _reading(
        Scope.BOILER_HEAT_PUMP,
        BoilerHeatPumpPointKey.TEMP_INLET_CURRENT,
        SensorDeviceClass.TEMPERATURE,
    ),
    _reading(
        Scope.BOILER_HEAT_PUMP,
        BoilerHeatPumpPointKey.TEMP_REQUESTED,
        SensorDeviceClass.TEMPERATURE,
    ),
    _enum(Scope.BUFFER_TANK, BufferTankPointKey.STATE, HeatSourceState),
    _enum(Scope.BUFFER_TANK, BufferTankPointKey.BLOCKING_SOURCE, BlockingSource),
    _reading(
        Scope.BUFFER_TANK,
        BufferTankPointKey.TEMP_SOURCE_INLET,
        SensorDeviceClass.TEMPERATURE,
    ),
    _reading(
        Scope.BUFFER_TANK, BufferTankPointKey.TEMP_UPPER, SensorDeviceClass.TEMPERATURE
    ),
    _reading(
        Scope.BUFFER_TANK, BufferTankPointKey.TEMP_LOWER, SensorDeviceClass.TEMPERATURE
    ),
    _reading(
        Scope.THERMISTOR_INPUTS,
        ThermistorPointKey.TEMP_T1,
        SensorDeviceClass.TEMPERATURE,
        enabled=False,
    ),
    _reading(
        Scope.THERMISTOR_INPUTS,
        ThermistorPointKey.TEMP_T2,
        SensorDeviceClass.TEMPERATURE,
        enabled=False,
    ),
    _reading(
        Scope.THERMISTOR_INPUTS,
        ThermistorPointKey.TEMP_T3,
        SensorDeviceClass.TEMPERATURE,
        enabled=False,
    ),
    _reading(
        Scope.THERMISTOR_INPUTS,
        ThermistorPointKey.TEMP_T4,
        SensorDeviceClass.TEMPERATURE,
        enabled=False,
    ),
    _reading(
        Scope.THERMISTOR_INPUTS,
        ThermistorPointKey.TEMP_T5,
        SensorDeviceClass.TEMPERATURE,
        enabled=False,
    ),
    _reading(
        Scope.DHW_TANK, DhwTankPointKey.TEMP_CURRENT, SensorDeviceClass.TEMPERATURE
    ),
    _reading(
        Scope.DHW_TANK, DhwTankPointKey.TEMP_TARGET, SensorDeviceClass.TEMPERATURE
    ),
    _enum(Scope.DHW_TANK, DhwTankPointKey.STATE, DhwTankState),
    _enum(Scope.DHW_TANK, DhwTankPointKey.BLOCKING_SOURCE, BlockingSource),
    _enum(Scope.DHW_TANK, DhwTankPointKey.CIRCULATION_STATE, CirculationState),
    _reading(
        Scope.DHW_TANK,
        DhwTankPointKey.TEMP_CIRCULATION_RETURN,
        SensorDeviceClass.TEMPERATURE,
        enabled=False,
    ),
    _reading(
        Scope.DHW_TANK,
        DhwTankPointKey.TEMP_SOURCE_INLET,
        SensorDeviceClass.TEMPERATURE,
        enabled=False,
    ),
    _reading(
        Scope.DHW_TANK,
        DhwTankPointKey.TEMP_SOURCE_RETURN,
        SensorDeviceClass.TEMPERATURE,
        enabled=False,
    ),
    _enum(Scope.VENTILATION, VentilationPointKey.STATE, VentilationUnitState),
    _enum(Scope.VENTILATION, VentilationPointKey.BLOCKING_SOURCE, BlockingSource),
    _reading(
        Scope.VENTILATION,
        VentilationPointKey.WARNING_CODE,
        None,
        diagnostic=True,
        enabled=False,
        measurement=False,
    ),
    _reading(
        Scope.VENTILATION,
        VentilationPointKey.ERROR_CODE,
        None,
        diagnostic=True,
        enabled=False,
        measurement=False,
    ),
    _reading(
        Scope.VENTILATION,
        VentilationPointKey.FREE_COOLING,
        None,
        diagnostic=True,
        enabled=False,
        measurement=False,
    ),
    _reading(Scope.VENTILATION, VentilationPointKey.SUPPLY_FAN_SPEED, None),
    _reading(Scope.VENTILATION, VentilationPointKey.EXHAUST_FAN_SPEED, None),
    _reading(
        Scope.VENTILATION, VentilationPointKey.SUPPLY_FAN_SETPOINT, None, enabled=False
    ),
    _reading(
        Scope.VENTILATION, VentilationPointKey.EXHAUST_FAN_SETPOINT, None, enabled=False
    ),
    _reading(
        Scope.VENTILATION,
        VentilationPointKey.SUPPLY_FLOW_SETPOINT,
        SensorDeviceClass.VOLUME_FLOW_RATE,
        enabled=False,
    ),
    _reading(
        Scope.VENTILATION,
        VentilationPointKey.EXHAUST_FLOW_SETPOINT,
        SensorDeviceClass.VOLUME_FLOW_RATE,
        enabled=False,
    ),
    _reading(
        Scope.VENTILATION,
        VentilationPointKey.TEMP_INTAKE,
        SensorDeviceClass.TEMPERATURE,
    ),
    _reading(
        Scope.VENTILATION,
        VentilationPointKey.TEMP_SUPPLY,
        SensorDeviceClass.TEMPERATURE,
    ),
    _reading(
        Scope.VENTILATION,
        VentilationPointKey.TEMP_EXTRACT,
        SensorDeviceClass.TEMPERATURE,
    ),
    _reading(
        Scope.VENTILATION,
        VentilationPointKey.TEMP_EXHAUST,
        SensorDeviceClass.TEMPERATURE,
    ),
    _reading(
        Scope.VENTILATION,
        VentilationPointKey.BYPASS_DAMPER_POSITION,
        None,
        enabled=False,
    ),
    _enum(Scope.DEHUMIDIFIER, DehumidifierPointKey.DRYING_STATE, DryingState),
    _enum(
        Scope.DEHUMIDIFIER, DehumidifierPointKey.DRYING_BLOCKING_SOURCE, BlockingSource
    ),
    _enum(
        Scope.DEHUMIDIFIER, DehumidifierPointKey.THERMAL_INTEGRATION_STATE, RoomState
    ),
    _enum(
        Scope.DEHUMIDIFIER,
        DehumidifierPointKey.THERMAL_INTEGRATION_BLOCKING_SOURCE,
        BlockingSource,
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
