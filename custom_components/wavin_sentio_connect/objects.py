"""Where a point lives, and the controller's objects besides its rooms and peripherals."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from wavin_sentio_connect import (
    BOILER_HEAT_PUMP,
    BUFFER_TANK,
    DEHUMIDIFIER,
    DHW_TANK,
    HCC,
    HEATING_COOLING_SOURCE,
    ITC,
    OBJECT,
    OUTDOOR,
    THERMISTOR_INPUTS,
    VENTILATION,
    BoilerHeatPumpPointKey,
    BufferTankPointKey,
    Client,
    DehumidifierPointKey,
    DhwTankPointKey,
    HccPointKey,
    ItcPointKey,
    Key,
    Labels,
    OutdoorPointKey,
    PointKey,
    VentilationPointKey,
    dehumidifier_key,
    hcc_key,
    itc_key,
    ventilation_key,
)

from .const import DOMAIN


class Scope(StrEnum):
    """Where a point lives: the location, every room or peripheral, or one of the controller's
    other objects."""

    LOCATION = "location"
    ROOM = "room"
    PERIPHERAL = "peripheral"
    OUTDOOR = "outdoor"
    HC_SOURCE = "hc_source"
    BOILER_HEAT_PUMP = "boiler_heat_pump"
    THERMISTOR_INPUTS = "thermistor_inputs"
    DHW_TANK = "dhw_tank"
    BUFFER_TANK = "buffer_tank"
    HCC = "hcc"
    ITC = "itc"
    VENTILATION = "ventilation_unit"
    DEHUMIDIFIER = "dehumidifier"


@dataclass(frozen=True)
class SingleObject:
    """One of the controller's objects it has at most one of: a part of the controller."""

    label: str
    """The value of the library's object label on its points."""
    name: Key[str] | None
    """The object's name on the controller, when it has one."""


@dataclass(frozen=True)
class RepeatedObject:
    """One of the controller's objects it has several of."""

    label: str
    """The library's instance label."""
    key: Callable[[int, PointKey[Any]], Key[Any]]
    name: PointKey[str]
    part: bool
    """A part of the controller, or a device of its own that the controller reaches."""
    model: PointKey[Any] | None = None
    """The point that gives a device of its own its model."""


SINGLE_OBJECTS: Mapping[Scope, SingleObject] = MappingProxyType(
    {
        Scope.OUTDOOR: SingleObject(OUTDOOR, OutdoorPointKey.NAME),
        Scope.HC_SOURCE: SingleObject(HEATING_COOLING_SOURCE, None),
        Scope.BOILER_HEAT_PUMP: SingleObject(
            BOILER_HEAT_PUMP, BoilerHeatPumpPointKey.NAME
        ),
        Scope.THERMISTOR_INPUTS: SingleObject(THERMISTOR_INPUTS, None),
        Scope.DHW_TANK: SingleObject(DHW_TANK, DhwTankPointKey.NAME),
        Scope.BUFFER_TANK: SingleObject(BUFFER_TANK, BufferTankPointKey.NAME),
    }
)

REPEATED_OBJECTS: Mapping[Scope, RepeatedObject] = MappingProxyType(
    {
        Scope.HCC: RepeatedObject(HCC, hcc_key, HccPointKey.NAME, part=True),
        Scope.ITC: RepeatedObject(ITC, itc_key, ItcPointKey.NAME, part=True),
        # The manual: ventilation units are connected by the controller's Modbus RTU master.
        Scope.VENTILATION: RepeatedObject(
            VENTILATION,
            ventilation_key,
            VentilationPointKey.NAME,
            part=False,
            model=VentilationPointKey.DEVICE_MODEL,
        ),
        Scope.DEHUMIDIFIER: RepeatedObject(
            DEHUMIDIFIER,
            dehumidifier_key,
            DehumidifierPointKey.NAME,
            part=False,
            model=DehumidifierPointKey.TYPE,
        ),
    }
)


def object_identifier(
    serial_number: str, scope: Scope, number: int | None = None
) -> tuple[str, str]:
    """The device identifier of an object, and of its instance `number` where it has several."""
    suffix = f"_{number}" if number is not None else ""
    return (DOMAIN, f"{serial_number}_{scope.value}{suffix}")


def present_objects(client: Client) -> list[tuple[Scope, int | None]]:
    """Every object the controller has, with its number where it has several."""
    found: list[tuple[Scope, int | None]] = [
        (scope, None)
        for scope, single in SINGLE_OBJECTS.items()
        if client.select(Labels(**{OBJECT: single.label}))
    ]
    for scope, repeated in REPEATED_OBJECTS.items():
        found.extend((scope, number) for number in client.instances(repeated.label))
    return found
