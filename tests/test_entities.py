"""What the entities show, when they are unavailable, and what they write."""

from __future__ import annotations

import pytest
from homeassistant.components.number.const import ATTR_VALUE, SERVICE_SET_VALUE
from homeassistant.components.select import ATTR_OPTION, SERVICE_SELECT_OPTION
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_UNIT_OF_MEASUREMENT,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from wavin_sentio_connect import InvalidValueError
from wavin_sentio_connect.testing import (
    FakeClock,
    SimulatedModbusDevice,
    SimulatedModbusGateway,
)

from custom_components.wavin_sentio_connect.const import DOMAIN
from custom_components.wavin_sentio_connect.data import SentioData

from .conftest import PERIPHERAL_BASE, SERIAL_NUMBER


def _state(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    assert state is not None, entity_id
    return state.state


async def _poll(hass: HomeAssistant, data: SentioData, clock: FakeClock) -> None:
    clock.advance(3600)
    await data.client.poll()
    await hass.async_block_till_done()


async def test_room_measurements_carry_their_units(
    hass: HomeAssistant, loaded: SentioData
) -> None:
    for entity_id, value, unit in (
        ("sensor.kitchen_air_temperature", "21.5", "°C"),
        ("sensor.kitchen_target_temperature", "21.0", "°C"),
        ("sensor.kitchen_floor_temperature", "22.5", "°C"),
        ("sensor.kitchen_humidity", "45.5", "%"),
        ("sensor.kitchen_dew_point", "9.5", "°C"),
    ):
        state = hass.states.get(entity_id)
        assert state is not None, entity_id
        assert (state.state, state.attributes[ATTR_UNIT_OF_MEASUREMENT]) == (value, unit)
        assert state.attributes["state_class"] == "measurement", entity_id


async def test_the_target_temperature_sensor_follows_what_the_room_regulates_to(
    hass: HomeAssistant,
    loaded: SentioData,
    controller: SimulatedModbusDevice,
    clock: FakeClock,
) -> None:
    """Vacation changes the target the room regulates to, not the room's own setpoint."""
    controller.input_registers[101] = 1600
    await _poll(hass, loaded, clock)
    assert _state(hass, "sensor.kitchen_target_temperature") == "16.0"
    assert controller.holding_registers[119] == 2100


async def test_a_state_shows_by_its_name(hass: HomeAssistant, loaded: SentioData) -> None:
    assert _state(hass, "sensor.kitchen_state") == "heating"
    assert _state(hass, "sensor.wavin_sentio_controller_heating_cooling_mode") == "heating"


async def test_a_dummy_room_has_no_measurements(
    hass: HomeAssistant, loaded: SentioData, entity_registry: er.EntityRegistry
) -> None:
    assert entity_registry.async_get_entity_id(
        "sensor", "wavin_sentio_connect", f"{SERIAL_NUMBER}_room_3_temp_air_current"
    ) is None
    assert _state(hass, "climate.hall") is not None


async def test_a_function_the_room_is_not_associated_with_has_no_entity(
    hass: HomeAssistant, loaded: SentioData, entity_registry: er.EntityRegistry
) -> None:
    def registered(point: str) -> bool:
        return entity_registry.async_get_entity_id(
            "sensor", "wavin_sentio_connect", f"{SERIAL_NUMBER}_room_1_{point}"
        ) is not None

    assert registered("radiators_state")
    assert not registered("ufhc_state")


async def test_no_reading_shows_as_unknown(
    hass: HomeAssistant,
    loaded: SentioData,
    controller: SimulatedModbusDevice,
    clock: FakeClock,
) -> None:
    controller.input_registers[104] = 0x7FFF
    await _poll(hass, loaded, clock)
    assert _state(hass, "sensor.kitchen_air_temperature") == STATE_UNKNOWN


async def test_everything_is_unavailable_while_the_controller_does_not_answer(
    hass: HomeAssistant,
    loaded: SentioData,
    gateway: SimulatedModbusGateway,
    controller: SimulatedModbusDevice,
    clock: FakeClock,
) -> None:
    gateway.link_down = True
    await _poll(hass, loaded, clock)
    assert _state(hass, "sensor.kitchen_air_temperature") == STATE_UNAVAILABLE
    assert _state(hass, "climate.kitchen") == STATE_UNAVAILABLE

    gateway.link_down = False
    controller.input_registers[104] = 2400
    await _poll(hass, loaded, clock)
    assert _state(hass, "sensor.kitchen_air_temperature") == "24.0"


async def test_an_alarm_bit_is_a_problem_sensor(
    hass: HomeAssistant,
    loaded: SentioData,
    controller: SimulatedModbusDevice,
    clock: FakeClock,
    entity_registry: er.EntityRegistry,
) -> None:
    entity_id = entity_registry.async_get_entity_id(
        "binary_sensor", "wavin_sentio_connect", f"{SERIAL_NUMBER}_system_error"
    )
    assert entity_id is not None
    assert _state(hass, entity_id) == "off"
    controller.discrete_inputs[2] = 1
    await _poll(hass, loaded, clock)
    assert _state(hass, entity_id) == "on"


async def test_a_switch_writes_its_point(
    hass: HomeAssistant, loaded: SentioData, controller: SimulatedModbusDevice
) -> None:
    await hass.services.async_call(
        "switch", SERVICE_TURN_ON, {ATTR_ENTITY_ID: "switch.wavin_sentio_controller_vacation"}, blocking=True
    )
    assert controller.holding_registers[27] == 1


async def test_a_select_writes_its_state(
    hass: HomeAssistant, loaded: SentioData, controller: SimulatedModbusDevice
) -> None:
    await hass.services.async_call(
        "select",
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: "select.kitchen_thermostat_lock", ATTR_OPTION: "hotel"},
        blocking=True,
    )
    assert controller.holding_registers[120] == 16


async def test_the_setpoint_is_set_apart_from_the_thermostat_even_on_a_schedule(
    hass: HomeAssistant,
    loaded: SentioData,
    controller: SimulatedModbusDevice,
    clock: FakeClock,
    entity_registry: er.EntityRegistry,
) -> None:
    controller.holding_registers[117] = 0                       # the room follows its schedule
    await _poll(hass, loaded, clock)
    entry = entity_registry.async_get("number.kitchen_setpoint")
    assert entry is not None and entry.entity_category is None
    assert _state(hass, "number.kitchen_setpoint") == "21.0"
    await hass.services.async_call(
        "number",
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: "number.kitchen_setpoint", ATTR_VALUE: 22.5},
        blocking=True,
    )
    assert controller.holding_registers[119] == 2250


async def test_a_number_writes_its_value_and_offers_the_encodings_range(
    hass: HomeAssistant, loaded: SentioData, controller: SimulatedModbusDevice
) -> None:
    state = hass.states.get("number.kitchen_vacation_temperature")
    assert state is not None
    assert (state.attributes["min"], state.attributes["max"]) == (-327.68, 327.66)
    await hass.services.async_call(
        "number",
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: "number.kitchen_vacation_temperature", ATTR_VALUE: 14.5},
        blocking=True,
    )
    assert controller.holding_registers[122] == 1450


@pytest.mark.parametrize("mode", [0, 1, 2, 3])
async def test_a_write_reaches_the_controller_whatever_its_modbus_mode_register_says(
    hass: HomeAssistant,
    loaded: SentioData,
    controller: SimulatedModbusDevice,
    clock: FakeClock,
    mode: int,
) -> None:
    """A CCU-208 in Modbus TCP read/write reported 0 (disabled) there, and took writes."""
    controller.holding_registers[5] = mode
    await _poll(hass, loaded, clock)
    await hass.services.async_call(
        "switch",
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: "switch.wavin_sentio_controller_vacation"},
        blocking=True,
    )
    assert controller.holding_registers[27] == 1


async def test_a_write_the_controller_refuses_is_reported(
    hass: HomeAssistant, loaded: SentioData, controller: SimulatedModbusDevice
) -> None:
    from wavin_sentio_connect.testing import FunctionCode

    controller.faults[(FunctionCode.WRITE_SINGLE_REGISTER, 27)] = 0x04
    controller.faults[(FunctionCode.WRITE_MULTIPLE_REGISTERS, 27)] = 0x04
    with pytest.raises(HomeAssistantError) as raised:
        await hass.services.async_call(
            "switch",
            SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: "switch.wavin_sentio_controller_vacation"},
            blocking=True,
        )
    assert raised.value.translation_key == "write_refused"


async def test_a_switch_turned_off_writes_its_off_value(
    hass: HomeAssistant, loaded: SentioData, controller: SimulatedModbusDevice
) -> None:
    controller.holding_registers[123] = 1
    await hass.services.async_call(
        "switch",
        SERVICE_TURN_OFF,
        {ATTR_ENTITY_ID: "switch.kitchen_exclude_from_vacation"},
        blocking=True,
    )
    assert controller.holding_registers[123] == 0


async def test_a_value_the_point_cannot_take_is_a_validation_error(
    hass: HomeAssistant, loaded: SentioData, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def refuse(*_: object) -> bool:
        raise InvalidValueError("simulated")

    monkeypatch.setattr(loaded.client, "write", refuse)
    with pytest.raises(ServiceValidationError) as raised:
        await hass.services.async_call(
            "switch", SERVICE_TURN_ON, {ATTR_ENTITY_ID: "switch.wavin_sentio_controller_vacation"}, blocking=True
        )
    assert raised.value.translation_key == "invalid_value"


async def test_a_peripheral_without_a_serial_number_gets_no_device_or_entities(
    hass: HomeAssistant,
    controller: SimulatedModbusDevice,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    device_registry: dr.DeviceRegistry,
) -> None:
    base = PERIPHERAL_BASE + 2 * 100
    controller.input_registers[base + 2] = controller.input_registers[base + 3] = 0xFFFF
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    identifiers = {
        identifier
        for device in dr.async_entries_for_config_entry(device_registry, config_entry.entry_id)
        for identifier in device.identifiers
    }
    assert (DOMAIN, f"{SERIAL_NUMBER}_peripheral_222") in identifiers
    assert not any("peripheral_333" in identifier for _, identifier in identifiers)
    assert not any(
        "peripheral_333" in entry.unique_id
        for entry in er.async_entries_for_config_entry(entity_registry, config_entry.entry_id)
    )
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_the_rooms_mode_and_preset_are_selects_of_their_own(
    hass: HomeAssistant, loaded: SentioData, controller: SimulatedModbusDevice
) -> None:
    assert _state(hass, "select.kitchen_mode") == "manual"
    assert _state(hass, "select.kitchen_preset") == "comfort"
    await hass.services.async_call(
        "select",
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: "select.kitchen_mode", ATTR_OPTION: "schedule"},
        blocking=True,
    )
    assert controller.holding_registers[117] == 0
    await hass.services.async_call(
        "select",
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: "select.kitchen_preset", ATTR_OPTION: "eco"},
        blocking=True,
    )
    assert controller.holding_registers[135] == 0
