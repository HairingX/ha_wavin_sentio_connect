"""A room as a thermostat."""

from __future__ import annotations

import pytest
from homeassistant.components.climate.const import (
    ATTR_CURRENT_HUMIDITY,
    ATTR_CURRENT_TEMPERATURE,
    ATTR_HVAC_ACTION,
    ATTR_HVAC_MODE,
    ATTR_HVAC_MODES,
    ATTR_PRESET_MODE,
    ATTR_PRESET_MODES,
    SERVICE_SET_HVAC_MODE,
    SERVICE_SET_PRESET_MODE,
    SERVICE_SET_TEMPERATURE,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_ENTITY_ID, ATTR_TEMPERATURE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry
from wavin_sentio_connect.testing import FakeClock, FunctionCode, SimulatedModbusDevice

from custom_components.wavin_sentio_connect.data import SentioData

KITCHEN = "climate.kitchen"


async def _poll(hass: HomeAssistant, data: SentioData, clock: FakeClock) -> None:
    clock.advance(3600)
    await data.client.poll()
    await hass.async_block_till_done()


def _attributes(hass: HomeAssistant) -> dict[str, object]:
    state = hass.states.get(KITCHEN)
    assert state is not None
    return {"state": state.state, **state.attributes}


async def test_a_room_in_manual_mode_heats_to_its_target(
    hass: HomeAssistant, loaded: SentioData
) -> None:
    shown = _attributes(hass)
    assert shown["state"] == HVACMode.HEAT
    assert shown[ATTR_HVAC_MODES] == [HVACMode.HEAT, HVACMode.AUTO]
    assert shown[ATTR_HVAC_ACTION] == HVACAction.HEATING
    assert shown[ATTR_CURRENT_TEMPERATURE] == 21.5
    assert shown[ATTR_CURRENT_HUMIDITY] == 45.5
    assert shown[ATTR_TEMPERATURE] == 21.0
    assert shown[ATTR_PRESET_MODE] == "comfort"


async def test_a_room_on_its_schedule_is_auto(
    hass: HomeAssistant,
    loaded: SentioData,
    controller: SimulatedModbusDevice,
    clock: FakeClock,
) -> None:
    controller.holding_registers[117] = 0
    await _poll(hass, loaded, clock)
    assert _attributes(hass)["state"] == HVACMode.AUTO


async def test_the_location_cooling_makes_the_room_cool(
    hass: HomeAssistant,
    loaded: SentioData,
    controller: SimulatedModbusDevice,
    clock: FakeClock,
) -> None:
    controller.input_registers[20] = 1
    await _poll(hass, loaded, clock)
    shown = _attributes(hass)
    assert shown["state"] == HVACMode.COOL
    assert shown[ATTR_HVAC_MODES] == [HVACMode.COOL, HVACMode.AUTO]


async def test_setting_the_temperature_writes_the_rooms_setpoint(
    hass: HomeAssistant, loaded: SentioData, controller: SimulatedModbusDevice
) -> None:
    await hass.services.async_call(
        "climate",
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: KITCHEN, ATTR_TEMPERATURE: 22.5},
        blocking=True,
    )
    assert controller.holding_registers[119] == 2250


async def test_the_temperature_of_a_room_on_its_schedule_cannot_be_set(
    hass: HomeAssistant,
    loaded: SentioData,
    controller: SimulatedModbusDevice,
    clock: FakeClock,
) -> None:
    controller.holding_registers[117] = 0
    await _poll(hass, loaded, clock)
    with pytest.raises(ServiceValidationError) as raised:
        await hass.services.async_call(
            "climate",
            SERVICE_SET_TEMPERATURE,
            {ATTR_ENTITY_ID: KITCHEN, ATTR_TEMPERATURE: 22.5},
            blocking=True,
        )
    assert raised.value.translation_key == "schedule_has_the_target"
    assert controller.holding_registers[119] == 2100


@pytest.mark.parametrize(("mode", "register"), [(HVACMode.AUTO, 0), (HVACMode.HEAT, 1)])
async def test_the_hvac_mode_sets_the_rooms_mode(
    hass: HomeAssistant,
    loaded: SentioData,
    controller: SimulatedModbusDevice,
    mode: HVACMode,
    register: int,
) -> None:
    controller.holding_registers[117] = 1 - register
    await hass.services.async_call(
        "climate",
        SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: KITCHEN, ATTR_HVAC_MODE: mode},
        blocking=True,
    )
    assert controller.holding_registers[117] == register


async def test_a_preset_writes_the_rooms_preset(
    hass: HomeAssistant, loaded: SentioData, controller: SimulatedModbusDevice
) -> None:
    await hass.services.async_call(
        "climate",
        SERVICE_SET_PRESET_MODE,
        {ATTR_ENTITY_ID: KITCHEN, ATTR_PRESET_MODE: "extra_comfort"},
        blocking=True,
    )
    assert controller.holding_registers[135] == 2


async def test_a_blocked_room_is_idle(
    hass: HomeAssistant,
    loaded: SentioData,
    controller: SimulatedModbusDevice,
    clock: FakeClock,
) -> None:
    controller.input_registers[102] = 4
    await _poll(hass, loaded, clock)
    assert _attributes(hass)[ATTR_HVAC_ACTION] == HVACAction.IDLE


async def test_a_room_whose_location_gives_no_heating_or_cooling_mode_offers_only_auto(
    hass: HomeAssistant,
    loaded: SentioData,
    controller: SimulatedModbusDevice,
    clock: FakeClock,
) -> None:
    controller.input_registers[20] = 0xFF
    await _poll(hass, loaded, clock)
    shown = _attributes(hass)
    assert shown[ATTR_HVAC_MODES] == [HVACMode.AUTO]
    assert shown["state"] == "unknown"


async def test_a_controller_that_refuses_the_preset_register_gets_no_presets(
    hass: HomeAssistant, controller: SimulatedModbusDevice, config_entry: MockConfigEntry
) -> None:
    """A CCU-208 with address space 3.7 refuses the room preset register (0x02)."""
    controller.faults[(FunctionCode.READ_HOLDING_REGISTERS, 135)] = 0x02
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    state = hass.states.get(KITCHEN)
    assert state is not None and state.state == HVACMode.HEAT
    assert ATTR_PRESET_MODES not in state.attributes
    assert ATTR_PRESET_MODE not in state.attributes
    assert hass.states.get("select.kitchen_preset") is None
    await hass.config_entries.async_unload(config_entry.entry_id)
