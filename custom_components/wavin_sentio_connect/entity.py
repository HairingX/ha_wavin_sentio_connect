"""What an entity is made of, and the entity every platform builds on."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.device_registry import ChildDeviceInfo, DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription

from wavin_sentio_connect import (
    DataValue,
    InvalidValueError,
    Key,
    LocationPointKey,
    ModbusMode,
    PointKey,
    Quality,
    Status,
    peripheral_key,
    room_key,
)

from .const import DOMAIN
from .data import SentioData, value
from .devices import controller_identifier, peripheral_identifier, room_identifier
from .objects import REPEATED_OBJECTS, SINGLE_OBJECTS, Scope, object_identifier

_USABLE = frozenset({Quality.GOOD, Quality.NO_DATA, Quality.STALE})
"""Qualities an entity shows: a value, "unknown" for no reading, or the last good value.

OFFLINE and MISSING leave the entity unavailable, as does a controller that stopped answering.
"""

_NOT_WRITABLE = frozenset(
    {ModbusMode.DISABLED, ModbusMode.READ_ONLY, ModbusMode.WRITE_WITH_PASSWORD}
)
"""Modbus modes in which the controller refuses writes from this integration.

The manual: in WRITE_WITH_PASSWORD, writes are refused until a password has been written,
which this integration does not do.
"""


@dataclass(frozen=True, kw_only=True)
class SentioEntityDescription(EntityDescription):
    """Describes an entity of one point, in every room or peripheral that has it."""

    scope: Scope
    point: Key[Any] | PointKey[Any]
    """A location point's key, or a room's or peripheral's point key."""


def point_name(point: Key[Any] | PointKey[Any]) -> str:
    """The name of a point: a location point's whole key, or a room's or peripheral's."""
    return point.name if isinstance(point, PointKey) else str(point)


@dataclass(frozen=True)
class Target:
    """One entity to create: the point's key, its device and its unique id."""

    key: Key[Any]
    device: DeviceInfo | ChildDeviceInfo
    unique_id: str


def entity_key(scope: Scope, point: Key[Any] | PointKey[Any]) -> str:
    """The name of the entity of `point` in `scope`, which its translation is found by.

    A point of the objects there are several of is named after its object too: a circuit's
    `state` and a ventilation unit's are named alike but mean different things.
    """
    name = point_name(point)
    return f"{scope.value}_{name}" if scope in REPEATED_OBJECTS else name


def room_target(data: SentioData, room: int, key: Key[Any]) -> Target:
    """The entity of `key` in room `room`."""
    return Target(
        key,
        ChildDeviceInfo(
            identifiers={room_identifier(data, room)},
            parent_device_id=data.controller_device_id,
        ),
        f"{data.serial_number}_{key}",
    )


def targets(data: SentioData, description: SentioEntityDescription) -> list[Target]:
    """One target for each place that has the described point.

    A room or peripheral the controller says lacks the point - a dummy room's temperature, a
    register this unit refuses - gets no entity. A peripheral that reports no serial number
    gets none either, as its slot is not a stable identity.
    """
    point = description.point
    found: list[Target] = []
    match description.scope:
        case Scope.LOCATION:
            assert isinstance(point, Key)
            found.append(
                Target(
                    point,
                    DeviceInfo(identifiers={controller_identifier(data)}),
                    f"{data.serial_number}_{point}",
                )
            )
        case Scope.ROOM:
            assert isinstance(point, PointKey)
            found.extend(
                room_target(data, room.number, room_key(room.number, point))
                for room in data.rooms
            )
        case Scope.PERIPHERAL:
            assert isinstance(point, PointKey)
            found.extend(
                Target(
                    peripheral_key(peripheral.slot, point),
                    DeviceInfo(
                        identifiers={peripheral_identifier(data, peripheral.serial_number)}
                    ),
                    # The slot is left out: the controller renumbers slots on a relearn.
                    f"{data.serial_number}_peripheral_"
                    f"{peripheral.serial_number}_{point.name}",
                )
                for peripheral in data.peripherals
                if peripheral.serial_number is not None
            )
        case scope if scope in SINGLE_OBJECTS:
            assert isinstance(point, Key)
            found.append(
                Target(
                    point,
                    ChildDeviceInfo(
                        identifiers={object_identifier(data.serial_number, scope)},
                        parent_device_id=data.controller_device_id,
                    ),
                    f"{data.serial_number}_{point}",
                )
            )
        case scope:
            assert isinstance(point, PointKey)
            repeated = REPEATED_OBJECTS[scope]
            for number in data.client.instances(repeated.label):
                identifiers = {object_identifier(data.serial_number, scope, number)}
                key = repeated.key(number, point)
                device: DeviceInfo | ChildDeviceInfo = (
                    ChildDeviceInfo(
                        identifiers=identifiers,
                        parent_device_id=data.controller_device_id,
                    )
                    if repeated.part
                    else DeviceInfo(identifiers=identifiers)
                )
                found.append(Target(key, device, f"{data.serial_number}_{key}"))
    return [target for target in found if data.client.has(target.key)]


def all_targets[D: SentioEntityDescription](
    data: SentioData, descriptions: Iterable[D]
) -> list[tuple[Target, D]]:
    """Every target of every description."""
    return [
        (target, description)
        for description in descriptions
        for target in targets(data, description)
    ]


def usable(current: DataValue[Any] | None) -> bool:
    """Whether a value may be shown: a reading, no reading, or the last good one."""
    return current is not None and current.quality in _USABLE


class SentioEntity(Entity):
    """An entity kept current by the client's subscriptions; it is never polled by HA.

    A subclass sets its `_attr_` values in `_show`, which runs here, before HA reads the
    entity's capabilities, and then on every change of a watched key and of whether the
    controller answers. What `_show` uses is set before calling this constructor.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, data: SentioData, target: Target) -> None:
        self._client = data.client
        self._key = target.key
        self._attr_unique_id = target.unique_id
        self._attr_device_info = target.device
        self._added = False
        self._changed()

    def _watched(self) -> tuple[Key[Any], ...]:
        """Every key whose change changes this entity's state."""
        return (self._key,)

    async def async_update(self) -> None:
        """Read this entity's values from the controller now."""
        await self._client.refresh(list(self._watched()))

    def _show(self) -> None:
        """Set this entity's state from the client's current values."""

    async def async_added_to_hass(self) -> None:
        """Follow the watched keys and whether the controller answers."""
        for key in self._watched():
            self.async_on_remove(self._client.subscribe(key, self._on_value))
        self.async_on_remove(
            self._client.subscribe_status(Status.CONNECTED, self._on_status)
        )
        # Each subscription has told its current value; HA writes the state once this returns.
        self._added = True

    @callback
    def _on_value(
        self, key: Key[Any], old: DataValue[Any] | None, new: DataValue[Any]
    ) -> None:
        self._changed()

    @callback
    def _on_status(
        self, status: Status, old: DataValue[bool] | None, new: DataValue[bool]
    ) -> None:
        self._changed()

    @callback
    def _changed(self) -> None:
        """Recompute the state: available while the controller answers and the value can
        be shown."""
        self._attr_available = self._client.status(
            Status.CONNECTED
        ).value is True and usable(self._client.value(self._key))
        self._show()
        if self._added:
            self.async_write_ha_state()

    def _current[T](self, key: Key[T]) -> T | None:
        return value(self._client, key)

    async def _write[T](self, key: Key[T], new: T) -> None:
        """Write `new` to `key`, raising an error the user can read when it is not taken."""
        mode = self._current(LocationPointKey.MODBUS_MODE)
        if mode in _NOT_WRITABLE:
            assert mode is not None
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="modbus_not_writable",
                translation_placeholders={"mode": mode.name},
            )
        try:
            accepted = await self._client.write(key, new)
        except InvalidValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_value",
                translation_placeholders={"value": str(new)},
            ) from err
        if not accepted:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="write_refused"
            )
