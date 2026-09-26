"""A thermostat for every room."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    PRESET_COMFORT,
    PRESET_ECO,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from modbus_event_connect import Key

from wavin_sentio_connect import (
    HeatingCoolingMode,
    LocationPointKey,
    RoomMode,
    RoomPointKey,
    RoomState,
    TemperaturePreset,
    room_key,
)

from .const import DOMAIN
from .data import SentioConfigEntry, SentioData
from .entity import SentioEntity, Target, room_target

# The client sends writes in order and folds a queued setting into a newer one, so actions
# are passed to it as they come.
PARALLEL_UPDATES = 0

PRESETS: dict[TemperaturePreset, str] = {
    TemperaturePreset.ECO: PRESET_ECO,
    TemperaturePreset.COMFORT: PRESET_COMFORT,
    TemperaturePreset.EXTRA_COMFORT: "extra_comfort",
}

ACTIONS: dict[RoomState, HVACAction | None] = {
    # The manual: NONE is "not used in this room, or load was not detected".
    RoomState.NONE: None,
    RoomState.IDLE: HVACAction.IDLE,
    RoomState.HEATING: HVACAction.HEATING,
    RoomState.COOLING: HVACAction.COOLING,
    RoomState.BLOCKED_HEATING: HVACAction.IDLE,
    RoomState.BLOCKED_COOLING: HVACAction.IDLE,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SentioConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a thermostat for every room that reports the target it regulates to."""
    data = entry.runtime_data
    async_add_entities(
        SentioClimate(data, room_target(data, room.number, key), room.number)
        for room in data.rooms
        if data.client.has(
            key := room_key(room.number, RoomPointKey.TEMP_AIR_TARGET_ACTIVE)
        )
    )


class SentioClimate(SentioEntity, ClimateEntity):
    """A room: its temperature, its target, whether it follows its schedule, its preset.

    The target shown is the one the controller regulates to. Setting it sets the room's own
    setpoint, which the manual says is not used while the room follows its schedule, during
    vacation or standby, or under a temporary override.
    """

    _attr_name = None
    _attr_translation_key = "room"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS

    def __init__(self, data: SentioData, target: Target, room: int) -> None:
        self._air = room_key(room, RoomPointKey.TEMP_AIR_CURRENT)
        self._humidity = room_key(room, RoomPointKey.HUMIDITY_CURRENT)
        self._setpoint = room_key(room, RoomPointKey.TEMP_AIR_TARGET)
        self._mode = room_key(room, RoomPointKey.MODE)
        self._state = room_key(room, RoomPointKey.STATE)
        self._preset = room_key(room, RoomPointKey.TEMP_PRESET)
        client = data.client
        features = ClimateEntityFeature(0)
        if client.can_write(self._setpoint):
            features |= ClimateEntityFeature.TARGET_TEMPERATURE
        if client.can_write(self._preset):
            features |= ClimateEntityFeature.PRESET_MODE
            self._attr_preset_modes = list(PRESETS.values())
        self._attr_supported_features = features
        self._mode_writable = client.can_write(self._mode)
        super().__init__(data, target)

    def _watched(self) -> tuple[Key[Any], ...]:
        keys: tuple[Key[Any], ...] = (
            self._key,
            LocationPointKey.HEATING_COOLING_MODE,
            self._air,
            self._humidity,
            self._setpoint,
            self._mode,
            self._state,
            self._preset,
        )
        return tuple(key for key in keys if self._client.has(key))

    def _show(self) -> None:
        self._attr_current_temperature = self._current(self._air)
        self._attr_current_humidity = self._current(self._humidity)
        self._attr_target_temperature = self._current(self._key)
        manual = self._manual_mode()
        # The location's heating or cooling, and AUTO when the room can follow its schedule.
        self._attr_hvac_modes = [manual] if manual is not None else []
        if self._mode_writable:
            self._attr_hvac_modes.append(HVACMode.AUTO)
        # AUTO while the room follows its schedule, else the location's heating or cooling.
        self._attr_hvac_mode = (
            HVACMode.AUTO if self._current(self._mode) is RoomMode.SCHEDULE else manual
        )
        state = self._current(self._state)
        self._attr_hvac_action = ACTIONS.get(state) if state is not None else None
        preset = self._current(self._preset)
        self._attr_preset_mode = PRESETS[preset] if preset is not None else None

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the room's setpoint; refused while the room follows its schedule."""
        if self.hvac_mode is HVACMode.AUTO:
            # HA's AUTO: the temperature follows a schedule and cannot be adjusted.
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="schedule_has_the_target"
            )
        await self._write(self._setpoint, float(kwargs[ATTR_TEMPERATURE]))

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """AUTO follows the room's schedule; heating or cooling uses its setpoint."""
        mode = RoomMode.SCHEDULE if hvac_mode is HVACMode.AUTO else RoomMode.MANUAL
        await self._write(self._mode, mode)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        preset = next(key for key, value in PRESETS.items() if value == preset_mode)
        await self._write(self._preset, preset)

    def _manual_mode(self) -> HVACMode | None:
        """HEAT or COOL, as the location is heating or cooling; None when it did not say."""
        location = self._current(LocationPointKey.HEATING_COOLING_MODE)
        if location is HeatingCoolingMode.HEATING:
            return HVACMode.HEAT
        if location is HeatingCoolingMode.COOLING:
            return HVACMode.COOL
        return None
