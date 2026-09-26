"""On/off settings: standby, vacation, and a room's vacation and adaptive options."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from modbus_event_connect import Key

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

# The client sends writes in order and folds a queued setting into a newer one, so actions
# are passed to it as they come.
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class SentioSwitchDescription(SentioEntityDescription, SwitchEntityDescription):
    """A switch of one point, and the values it holds when on and off."""

    on: Any
    off: Any


def _switch(
    scope: Scope,
    point: Key[Any] | PointKey[Any],
    *,
    on: Any,
    off: Any,
    config: bool = False,
    enabled: bool = True,
) -> SentioSwitchDescription:
    return SentioSwitchDescription(
        key=point_name(point),
        translation_key=point_name(point),
        scope=scope,
        point=point,
        on=on,
        off=off,
        entity_category=EntityCategory.CONFIG if config else None,
        entity_registry_enabled_default=enabled,
    )


SWITCHES: tuple[SentioSwitchDescription, ...] = (
    _switch(Scope.LOCATION, LocationPointKey.STANDBY_ENABLE, on=True, off=False),
    _switch(Scope.LOCATION, LocationPointKey.VACATION_ENABLE, on=True, off=False),
    _switch(
        Scope.LOCATION,
        LocationPointKey.DAYLIGHT_SAVING_ENABLE,
        on=True,
        off=False,
        config=True,
        enabled=False,
    ),
    # The manual gives these two no values; the register map allows 0 and 1.
    _switch(Scope.ROOM, RoomPointKey.EXCLUDE_FROM_VACATION, on=1, off=0, config=True),
    _switch(Scope.ROOM, RoomPointKey.ADAPTIVE_ENABLE, on=1, off=0, config=True),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SentioConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a switch for every described point the installation has."""
    data = entry.runtime_data
    async_add_entities(
        SentioSwitch(data, target, description)
        for target, description in all_targets(data, SWITCHES)
    )


class SentioSwitch(SentioEntity, SwitchEntity):
    """One on/off setting, written to the controller."""

    def __init__(
        self, data: SentioData, target: Target, description: SentioSwitchDescription
    ) -> None:
        self.entity_description = description
        self._on: Any = description.on
        self._off: Any = description.off
        super().__init__(data, target)

    def _show(self) -> None:
        value = self._current(self._key)
        self._attr_is_on = (
            True if value == self._on else False if value == self._off else None
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._write(self._key, self._on)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._write(self._key, self._off)
