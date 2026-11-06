"""How long each room's underfloor heating heats, and is held back by the floor temperature."""

from __future__ import annotations

from datetime import timedelta

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.sensor import DATA_COMPONENT as SENSOR_COMPONENT
from homeassistant.components.sensor import RestoreSensor
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant.common import (
    MockConfigEntry,
    async_fire_time_changed,
    mock_restore_cache_with_extra_data,
)
from wavin_sentio_connect import BlockingSource, RoomState
from wavin_sentio_connect.testing import (
    FakeClock,
    SimulatedModbusDevice,
    SimulatedModbusGateway,
)

from custom_components.wavin_sentio_connect.const import DOMAIN
from custom_components.wavin_sentio_connect.data import SentioData

from .conftest import SERIAL_NUMBER, installation, room_base

HEATING_TIME = "sensor.wavin_sentio_controller_kitchen_underfloor_heating_time"
FLOOR_LIMITED = "sensor.wavin_sentio_controller_kitchen_floor_limited_time"
KITCHEN = "climate.wavin_sentio_controller_kitchen"
UFHC_STATE = room_base(1) + 18
UFHC_BLOCKING_SOURCE = room_base(1) + 23
NO_VALUE = 0xFF
TOLERANCE = 36 / 3600
"""How far apart the hours counted and expected may be: the clock is frozen only once the entry
is set up."""


@pytest.fixture
def controller() -> SimulatedModbusDevice:
    """The installation, with underfloor heating in the kitchen that heats."""
    found = installation()
    found.input_registers[room_base(1) + 12] = 1
    found.input_registers[UFHC_STATE] = RoomState.HEATING
    found.input_registers[UFHC_BLOCKING_SOURCE] = BlockingSource.NONE
    return found


async def _poll(hass: HomeAssistant, data: SentioData, clock: FakeClock) -> None:
    clock.advance(3600)
    await data.client.poll()
    await hass.async_block_till_done()


async def _wait(hass: HomeAssistant, freezer: FrozenDateTimeFactory, hours: float) -> None:
    freezer.tick(timedelta(hours=hours))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


def _hours(hass: HomeAssistant, entity_id: str) -> float:
    state = hass.states.get(entity_id)
    assert state is not None, entity_id
    return float(state.state)


def _counted(hass: HomeAssistant, entity_id: str, hours: float) -> bool:
    return abs(_hours(hass, entity_id) - hours) <= TOLERANCE


async def test_a_room_with_underfloor_heating_has_both_durations_on_its_thermostats_device(
    hass: HomeAssistant,
    loaded: SentioData,
    clock: FakeClock,
    entity_registry: er.EntityRegistry,
    device_registry: dr.DeviceRegistry,
) -> None:
    await _poll(hass, loaded, clock)
    thermostat = entity_registry.async_get(KITCHEN)
    assert thermostat is not None and thermostat.device_id is not None
    room = device_registry.async_get(thermostat.device_id)
    assert room is not None
    assert (DOMAIN, f"{SERIAL_NUMBER}_room_1") in room.identifiers
    for entity_id, key in (
        (HEATING_TIME, "ufhc_heating_time"),
        (FLOOR_LIMITED, "ufhc_floor_limited_time"),
    ):
        entry = entity_registry.async_get(entity_id)
        assert entry is not None, entity_id
        assert entry.device_id == room.id
        assert entry.translation_key == key
        assert entry.unique_id == f"{SERIAL_NUMBER}_room_1_{key}"
        assert entry.disabled_by is None
        state = hass.states.get(entity_id)
        assert state is not None
        assert state.attributes[ATTR_DEVICE_CLASS] == "duration"
        assert state.attributes["state_class"] == "total_increasing"
        assert state.attributes[ATTR_UNIT_OF_MEASUREMENT] == "h"


async def test_a_room_without_underfloor_heating_has_no_durations(
    hass: HomeAssistant, loaded: SentioData, entity_registry: er.EntityRegistry
) -> None:
    for key in ("ufhc_heating_time", "ufhc_floor_limited_time"):
        assert entity_registry.async_get_entity_id(
            "sensor", DOMAIN, f"{SERIAL_NUMBER}_room_2_{key}"
        ) is None


async def test_the_time_the_underfloor_heating_heats_is_counted(
    hass: HomeAssistant,
    loaded: SentioData,
    controller: SimulatedModbusDevice,
    clock: FakeClock,
    freezer: FrozenDateTimeFactory,
) -> None:
    await _poll(hass, loaded, clock)
    assert _counted(hass, HEATING_TIME, 0)
    await _wait(hass, freezer, 1)
    assert _counted(hass, HEATING_TIME, 1)

    freezer.tick(timedelta(minutes=30))
    controller.input_registers[UFHC_STATE] = RoomState.IDLE
    await _poll(hass, loaded, clock)
    assert _counted(hass, HEATING_TIME, 1.5)

    await _wait(hass, freezer, 2)
    assert _counted(hass, HEATING_TIME, 1.5)

    controller.input_registers[UFHC_STATE] = RoomState.HEATING
    await _poll(hass, loaded, clock)
    await _wait(hass, freezer, 0.25)
    assert _counted(hass, HEATING_TIME, 1.75)


async def test_the_time_the_floor_temperature_holds_the_underfloor_heating_back_is_counted(
    hass: HomeAssistant,
    loaded: SentioData,
    controller: SimulatedModbusDevice,
    clock: FakeClock,
    freezer: FrozenDateTimeFactory,
) -> None:
    await _poll(hass, loaded, clock)
    await _wait(hass, freezer, 1)
    assert _hours(hass, FLOOR_LIMITED) == 0

    controller.input_registers[UFHC_STATE] = RoomState.BLOCKED_HEATING
    controller.input_registers[UFHC_BLOCKING_SOURCE] = BlockingSource.FLOOR_TEMP
    await _poll(hass, loaded, clock)
    await _wait(hass, freezer, 2)
    assert _counted(hass, FLOOR_LIMITED, 2)
    assert _counted(hass, HEATING_TIME, 1)

    controller.input_registers[UFHC_BLOCKING_SOURCE] = BlockingSource.AIR_TEMP
    await _poll(hass, loaded, clock)
    await _wait(hass, freezer, 1)
    assert _counted(hass, FLOOR_LIMITED, 2)


async def test_no_time_is_counted_while_the_controller_does_not_answer(
    hass: HomeAssistant,
    loaded: SentioData,
    gateway: SimulatedModbusGateway,
    clock: FakeClock,
    freezer: FrozenDateTimeFactory,
) -> None:
    await _poll(hass, loaded, clock)
    await _wait(hass, freezer, 1)
    gateway.link_down = True
    await _poll(hass, loaded, clock)
    await _poll(hass, loaded, clock)
    state = hass.states.get(HEATING_TIME)
    assert state is not None and state.state == STATE_UNAVAILABLE

    await _wait(hass, freezer, 3)
    gateway.link_down = False
    await _poll(hass, loaded, clock)
    assert _counted(hass, HEATING_TIME, 1)
    await _wait(hass, freezer, 1)
    assert _counted(hass, HEATING_TIME, 2)


async def test_no_time_is_counted_while_the_state_has_no_value(
    hass: HomeAssistant,
    loaded: SentioData,
    controller: SimulatedModbusDevice,
    clock: FakeClock,
    freezer: FrozenDateTimeFactory,
) -> None:
    await _poll(hass, loaded, clock)
    await _wait(hass, freezer, 1)
    controller.input_registers[UFHC_STATE] = NO_VALUE
    await _poll(hass, loaded, clock)
    await _wait(hass, freezer, 3)
    assert _counted(hass, HEATING_TIME, 1)


async def test_a_clock_set_back_adds_no_time(
    hass: HomeAssistant,
    loaded: SentioData,
    controller: SimulatedModbusDevice,
    clock: FakeClock,
    freezer: FrozenDateTimeFactory,
) -> None:
    await _poll(hass, loaded, clock)
    await _wait(hass, freezer, 1)
    freezer.tick(timedelta(hours=-3))
    controller.input_registers[UFHC_STATE] = RoomState.IDLE
    await _poll(hass, loaded, clock)
    assert _counted(hass, HEATING_TIME, 1)


async def test_the_total_is_kept_over_a_reload_without_the_time_between(
    hass: HomeAssistant,
    loaded: SentioData,
    config_entry: MockConfigEntry,
    clock: FakeClock,
    freezer: FrozenDateTimeFactory,
) -> None:
    await _poll(hass, loaded, clock)
    await _wait(hass, freezer, 2)
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()

    freezer.tick(timedelta(hours=5))
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    await _poll(hass, config_entry.runtime_data, clock)
    assert _counted(hass, HEATING_TIME, 2)
    await _wait(hass, freezer, 1)
    assert _counted(hass, HEATING_TIME, 3)


async def test_the_total_goes_on_from_where_home_assistant_stopped(
    hass: HomeAssistant, config_entry: MockConfigEntry, clock: FakeClock
) -> None:
    mock_restore_cache_with_extra_data(
        hass,
        (
            (
                State(HEATING_TIME, "12.5"),
                {"native_value": 12.5, "native_unit_of_measurement": "h"},
            ),
            (
                State(FLOOR_LIMITED, STATE_UNAVAILABLE),
                {"native_value": None, "native_unit_of_measurement": "h"},
            ),
        ),
    )
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    await _poll(hass, config_entry.runtime_data, clock)
    assert _counted(hass, HEATING_TIME, 12.5)
    assert _hours(hass, FLOOR_LIMITED) == 0
    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()



def _stored(hass: HomeAssistant, entity_id: str) -> float:
    entity = hass.data[SENSOR_COMPONENT].get_entity(entity_id)
    assert isinstance(entity, RestoreSensor), entity_id
    value = entity.extra_restore_state_data.native_value
    assert isinstance(value, float), value
    return value


async def test_a_stop_keeps_the_time_counted_since_the_last_update(
    hass: HomeAssistant,
    loaded: SentioData,
    controller: SimulatedModbusDevice,
    clock: FakeClock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Home Assistant saves what is restored when it stops, between two updates."""
    await _poll(hass, loaded, clock)
    shown = _hours(hass, HEATING_TIME)
    freezer.tick(timedelta(seconds=40))
    assert abs(_stored(hass, HEATING_TIME) - shown - 40 / 3600) < 1e-6

    controller.input_registers[UFHC_STATE] = RoomState.IDLE
    await _poll(hass, loaded, clock)
    idle = _hours(hass, HEATING_TIME)
    freezer.tick(timedelta(hours=1))
    assert abs(_stored(hass, HEATING_TIME) - idle) < 1e-9
