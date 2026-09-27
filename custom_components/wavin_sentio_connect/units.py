"""The units of Sentio values, as Home Assistant spells them."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from homeassistant.const import (
    PERCENTAGE,
    REVOLUTIONS_PER_MINUTE,
    UnitOfTemperature,
    UnitOfTime,
    UnitOfVolumeFlowRate,
)
from wavin_sentio_connect import Client, Key, Unit

HA_UNITS: Mapping[Unit, str] = MappingProxyType(
    {
        Unit.CELSIUS: UnitOfTemperature.CELSIUS,
        Unit.KELVIN: UnitOfTemperature.KELVIN,
        Unit.PERCENT: PERCENTAGE,
        Unit.SECONDS: UnitOfTime.SECONDS,
        Unit.MINUTES: UnitOfTime.MINUTES,
        Unit.RPM: REVOLUTIONS_PER_MINUTE,
        Unit.CUBIC_METERS_PER_HOUR: UnitOfVolumeFlowRate.CUBIC_METERS_PER_HOUR,
    }
)
"""Every unit a Sentio value has."""


def ha_unit(client: Client, key: Key[Any]) -> str | None:
    """The unit of `key`'s value, or None when it has none."""
    (point,) = client.select([key])
    return HA_UNITS[point.unit] if point.unit is not None else None
