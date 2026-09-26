"""Number settings: standby and vacation temperatures, and the installer's limits."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from modbus_event_connect import Key, Point

from wavin_sentio_connect import LocationPointKey, PointKey, RoomPointKey

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

# The client sends writes in order and folds a queued setting into a newer one, so actions
# are passed to it as they come.
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class SentioNumberDescription(SentioEntityDescription, NumberEntityDescription):
    """A number of one point."""


def _number(
    scope: Scope,
    point: Key[Any] | PointKey[Any],
    device_class: NumberDeviceClass | None,
    *,
    enabled: bool = True,
    config: bool = True,
) -> SentioNumberDescription:
    return SentioNumberDescription(
        key=point_name(point),
        translation_key=point_name(point),
        scope=scope,
        point=point,
        # Offsets and hysteresis are differences, which a temperature class would convert as
        # absolute temperatures; they have no device class.
        device_class=device_class,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG if config else None,
        entity_registry_enabled_default=enabled,
    )


_TEMPERATURE = NumberDeviceClass.TEMPERATURE
_HUMIDITY = NumberDeviceClass.HUMIDITY
_ROOM = Scope.ROOM

NUMBERS: tuple[SentioNumberDescription, ...] = (
    _number(
        Scope.LOCATION,
        LocationPointKey.TEMP_OUTDOOR_COOLING_MIN,
        _TEMPERATURE,
        enabled=False,
    ),
    _number(
        Scope.LOCATION,
        LocationPointKey.TEMP_OUTDOOR_HEATING_MAX,
        _TEMPERATURE,
        enabled=False,
    ),
    # The room's own setpoint, which the manual says is not used while the room follows its
    # schedule, during vacation or standby, or under a temporary override; it is kept for when
    # none of them applies.
    _number(_ROOM, RoomPointKey.TEMP_AIR_TARGET, _TEMPERATURE, config=False),
    _number(_ROOM, RoomPointKey.TEMP_STANDBY, _TEMPERATURE),
    _number(_ROOM, RoomPointKey.TEMP_VACATION, _TEMPERATURE),
    _number(_ROOM, RoomPointKey.THERMAL_INTEGRATION_HEATING_OFFSET, None, enabled=False),
    _number(_ROOM, RoomPointKey.THERMAL_INTEGRATION_HYSTERESIS, None, enabled=False),
    _number(_ROOM, RoomPointKey.HUMIDITY_THRESHOLD_HEATING, _HUMIDITY, enabled=False),
    _number(_ROOM, RoomPointKey.HUMIDITY_THRESHOLD_COOLING, _HUMIDITY, enabled=False),
    _number(_ROOM, RoomPointKey.HUMIDITY_HYSTERESIS, None, enabled=False),
    _number(_ROOM, RoomPointKey.DRYING_COOLING_WATER_OFFSET, None, enabled=False),
    _number(
        _ROOM, RoomPointKey.DRYING_COOLING_WATER_OFFSET_HYSTERESIS, None, enabled=False
    ),
    _number(_ROOM, RoomPointKey.DEW_POINT_COOLING_THRESHOLD, _TEMPERATURE, enabled=False),
    _number(
        _ROOM, RoomPointKey.DEW_POINT_COOLING_THRESHOLD_HYSTERESIS, None, enabled=False
    ),
    _number(_ROOM, RoomPointKey.HUMIDITY_HIGH_ALARM_LIMIT, _HUMIDITY, enabled=False),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SentioConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a number for every described point the installation has."""
    data = entry.runtime_data
    async_add_entities(
        SentioNumber(data, target, description)
        for target, description in all_targets(data, NUMBERS)
    )


def value_range(point: Point[Any]) -> tuple[float, float, float]:
    """The lowest and highest value `point` can be written with, and its step.

    The point's own limits where it has them; otherwise every value its encoding can carry,
    as the manual gives these settings no range.
    """
    if point.transform is not None:
        raise ValueError(f"{point.key} is transformed; its range cannot be derived")
    step = point.scale
    if point.limits is not None and point.limits.step is not None:
        step = point.limits.step
    if (
        point.limits is not None
        and point.limits.min is not None
        and point.limits.max is not None
    ):
        return point.limits.min, point.limits.max, step
    raw = point.valid_raw
    if not isinstance(raw, range) or raw.step != 1 or not raw:
        raise ValueError(f"{point.key} has neither limits nor a range of valid values")
    lowest = raw.start * point.scale + point.offset
    highest = (raw.stop - 1) * point.scale + point.offset
    return round(lowest, 10), round(highest, 10), step


class SentioNumber(SentioEntity, NumberEntity):
    """One number setting, written to the controller."""

    def __init__(
        self, data: SentioData, target: Target, description: SentioNumberDescription
    ) -> None:
        super().__init__(data, target)
        self.entity_description = description
        (point,) = data.client.select([target.key])
        lowest, highest, step = value_range(point)
        self._attr_native_min_value = lowest
        self._attr_native_max_value = highest
        self._attr_native_step = step
        self._attr_native_unit_of_measurement = ha_unit(data.client, target.key)

    def _show(self) -> None:
        value = self._current(self._key)
        self._attr_native_value = (
            value
            if isinstance(value, int | float) and not isinstance(value, bool)
            else None
        )

    async def async_set_native_value(self, value: float) -> None:
        await self._write(self._key, value)
