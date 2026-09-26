"""Settings that take one of a set of states: a room's mode, preset and lock, and the location's."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Any

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from wavin_sentio_connect import (
    HeatingCoolingModeOverride,
    Key,
    LocationPointKey,
    PointKey,
    RoomLock,
    RoomMode,
    RoomPointKey,
    TemperaturePreset,
    UpdateMode,
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

# The client sends writes in order and folds a queued setting into a newer one, so actions
# are passed to it as they come.
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class SentioSelectDescription(SentioEntityDescription, SelectEntityDescription):
    """A select of one point, and the states it takes."""

    states: type[IntEnum]


def _select(
    scope: Scope,
    point: Key[Any] | PointKey[Any],
    states: type[IntEnum],
    *,
    enabled: bool = True,
    config: bool = True,
) -> SentioSelectDescription:
    return SentioSelectDescription(
        key=point_name(point),
        translation_key=point_name(point),
        scope=scope,
        point=point,
        states=states,
        options=[state.name.lower() for state in states],
        entity_category=EntityCategory.CONFIG if config else None,
        entity_registry_enabled_default=enabled,
    )


SELECTS: tuple[SentioSelectDescription, ...] = (
    # What the thermostat shows as its mode and preset, each with its own history.
    _select(Scope.ROOM, RoomPointKey.MODE, RoomMode, config=False),
    _select(Scope.ROOM, RoomPointKey.TEMP_PRESET, TemperaturePreset, config=False),
    _select(Scope.LOCATION, LocationPointKey.UPDATE_MODE, UpdateMode, enabled=False),
    # The manual: only hardware profiles with a manual change-over offer the override.
    _select(
        Scope.LOCATION,
        LocationPointKey.HEATING_COOLING_MODE_BMS_OVERRIDE,
        HeatingCoolingModeOverride,
        enabled=False,
    ),
    _select(Scope.ROOM, RoomPointKey.LOCK, RoomLock),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SentioConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a select for every described point the installation has."""
    data = entry.runtime_data
    async_add_entities(
        SentioSelect(data, target, description)
        for target, description in all_targets(data, SELECTS)
    )


class SentioSelect(SentioEntity, SelectEntity):
    """One state setting, written to the controller."""

    def __init__(
        self, data: SentioData, target: Target, description: SentioSelectDescription
    ) -> None:
        self.entity_description = description
        self._states = description.states
        super().__init__(data, target)

    def _show(self) -> None:
        value = self._current(self._key)
        self._attr_current_option = (
            value.name.lower() if isinstance(value, IntEnum) else None
        )

    async def async_select_option(self, option: str) -> None:
        await self._write(self._key, self._states[option.upper()])
