"""Measurements and states of the controller, its rooms and its peripherals."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import IntEnum
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import (
    async_track_device_registry_updated_event,
    async_track_utc_time_change,
)
from homeassistant.util import dt as dt_util

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
    room_key,
)

from .data import SentioConfigEntry, SentioData
from .entity import (
    Scope,
    SentioEntity,
    SentioEntityDescription,
    Target,
    all_targets,
    entity_key,
    room_target,
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




@dataclass(frozen=True, kw_only=True)
class SentioDurationDescription(SentioSensorDescription):
    """The hours a room's state point has held one value."""

    counted: IntEnum
    """The value whose time is counted."""


def _duration(
    name: str, point: PointKey[Any], counted: IntEnum
) -> SentioDurationDescription:
    return SentioDurationDescription(
        key=name,
        translation_key=name,
        scope=Scope.ROOM,
        point=point,
        counted=counted,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfTime.HOURS,
        suggested_display_precision=2,
    )


DURATIONS: tuple[SentioDurationDescription, ...] = (
    _duration("ufhc_heating_time", RoomPointKey.UFHC_STATE, RoomState.HEATING),
    _duration(
        "ufhc_floor_limited_time",
        RoomPointKey.BLOCKING_SOURCE_UFHC,
        BlockingSource.FLOOR_TEMP,
    ),
)
"""How long each room's underfloor heating heats, and is held back by the floor temperature."""

SHOW_MINUTES = tuple(range(4, 60, 5))
SHOW_SECOND = 55
"""When a duration being counted shows its time so far: just before every five minutes end, as
Home Assistant's statistics take a sensor's state at the end of each five minutes."""


def duration_targets(
    data: SentioData, description: SentioDurationDescription
) -> list[Target]:
    """One target for each room that has the described point, with a unique id of its own."""
    point = description.point
    assert isinstance(point, PointKey)
    return [
        replace(
            room_target(data, room.number, key),
            unique_id=f"{data.serial_number}_room_{room.number}_{description.key}",
        )
        for room in data.rooms
        if data.client.has(key := room_key(room.number, point))
    ]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SentioConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a sensor for every described point the installation has, and the durations of each
    room's underfloor heating."""
    data = entry.runtime_data
    async_add_entities(
        (SentioPlace if description is PLACE else SentioSensor)(data, target, description)
        for target, description in all_targets(data, SENSORS)
    )
    async_add_entities(
        SentioDuration(data, target, description)
        for description in DURATIONS
        for target in duration_targets(data, description)
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


class SentioDuration(SentioEntity, RestoreSensor):
    """The hours a room's point has held one value, kept over restarts.

    The time from an update that shows the value to the next update is counted while the
    room is available; the time Home Assistant does not run is not.
    """

    def __init__(
        self, data: SentioData, target: Target, description: SentioDurationDescription
    ) -> None:
        self.entity_description = description
        self._counted = description.counted
        self._hours = 0.0
        self._since: datetime | None = None
        super().__init__(data, target)

    async def async_added_to_hass(self) -> None:
        last = await self.async_get_last_sensor_data()
        if last is not None and isinstance(last.native_value, int | float):
            self._hours += last.native_value
        self.async_on_remove(
            async_track_utc_time_change(
                self.hass, self._tick, minute=SHOW_MINUTES, second=SHOW_SECOND
            )
        )
        await super().async_added_to_hass()

    @callback
    def _tick(self, now: datetime) -> None:
        # The client tells only changes; showing the time counted so far keeps the statistics
        # in step while the value holds. A total that is not growing needs no new state.
        if self._since is not None:
            self._changed()

    def _show(self) -> None:
        now = dt_util.utcnow()
        if self._since is not None:
            # A clock set back adds no time.
            self._hours += max((now - self._since).total_seconds(), 0.0) / 3600
        counting = self._attr_available and self._current(self._key) == self._counted
        self._since = now if counting else None
        self._attr_native_value = self._hours
