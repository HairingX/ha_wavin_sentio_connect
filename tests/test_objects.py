"""The controller's objects besides its rooms and peripherals: their devices and entities."""

from __future__ import annotations

import pytest
from homeassistant.components.number.const import ATTR_VALUE, SERVICE_SET_VALUE
from homeassistant.components.select import ATTR_OPTION, SERVICE_SELECT_OPTION
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_UNIT_OF_MEASUREMENT,
    SERVICE_TURN_ON,
    EntityCategory,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from wavin_sentio_connect import PollRate
from wavin_sentio_connect.testing import SimulatedModbusDevice

from custom_components.wavin_sentio_connect.const import DOMAIN
from custom_components.wavin_sentio_connect.data import SentioData
from custom_components.wavin_sentio_connect.entity import all_targets
from custom_components.wavin_sentio_connect.number import NUMBERS, value_range

from .conftest import SERIAL_NUMBER, installation, room_base, take_away, text

NO_READING = 0x7FFF


def add_objects(controller: SimulatedModbusDevice) -> None:
    """The objects a CCU-208 answers for, with the values it gave: an outdoor zone,
    heating/cooling circuits 1 and 2, the heating/cooling source, the boiler/heat pump and the
    thermistor inputs."""
    inputs, holding = controller.input_registers, controller.holding_registers
    inputs.update({3301: NO_READING, 3302: 0, 3303: 0})
    holding.update(dict(enumerate(text("outdoor"), start=3301)))
    holding[3317] = NO_READING
    controller.discrete_inputs.update({3300 + bit: 0 for bit in (1, 2, 3, 4)})
    for n in (1, 2):
        base = 7600 + n * 100
        inputs.update({base + 1: 1, base + 2: 19, base + 3: 1, base + 4: 1})
        inputs.update({base + 5: NO_READING, base + 6: NO_READING, base + 8: NO_READING})
        holding.update(dict(enumerate(text(f"Sentio HCC {n}"), start=base + 1)))
        holding.update({base + 17: 2, base + 18: 10, base + 19: 0, base + 20: 2500})
        holding.update({base + 21: 4500, base + 22: 10, base + 23: 0, base + 24: 5000})
        controller.discrete_inputs.update({base + bit: 0 for bit in (1, 2, 3, 4)})
    inputs[8101] = 1
    controller.discrete_inputs.update({8100 + bit: 0 for bit in (1, 2, 3)})
    inputs.update({8201: 1, 8202: 0, 8203: NO_READING, 8204: NO_READING})
    holding.update(dict(enumerate(text("Heat pump / Boiler"), start=8201)))
    holding.update({8217: 0, 8218: 0, 8219: 5, 8220: 0})
    controller.discrete_inputs.update({8200 + bit: 0 for bit in (1, 2, 3, 4)})
    inputs.update({12800 + number: NO_READING for number in range(1, 6)})


def add_objects_from_the_manual(controller: SimulatedModbusDevice) -> None:
    """A hot water tank, ITC 1, a buffer tank, ventilation unit 1 and dehumidifier 1, none of
    them named; the values are chosen from the manual's."""
    inputs, holding = controller.input_registers, controller.holding_registers
    inputs.update({6601: 5230, 6602: 5500, 6603: 2, 6604: 0, 6605: 1})
    holding.update(dict(enumerate(text(""), start=6601)))
    holding.update({6617: 0, 6621: 5500, 6625: 0})
    inputs.update({7301: 2, 7305: 3510})
    holding.update(dict(enumerate(text(""), start=7301)))
    inputs.update({8301: 3, 8304: 4500})
    holding.update(dict(enumerate(text(""), start=8301)))
    inputs.update(dict(enumerate(text("Comfort 200"), start=61001)))
    inputs.update({61023: 3, 61025: 1250})
    holding.update(dict(enumerate(text(""), start=61001)))
    inputs.update({65001: 1, 65003: 2})
    holding.update(dict(enumerate(text(""), start=65001)))


def with_every_object() -> SimulatedModbusDevice:
    controller = installation()
    add_objects(controller)
    add_objects_from_the_manual(controller)
    return controller


@pytest.fixture
def controller() -> SimulatedModbusDevice:
    return with_every_object()


def _state(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    assert state is not None, entity_id
    return state.state


def _object(
    registry: dr.DeviceRegistry, entry: MockConfigEntry, identifier: str
) -> dr.DeviceEntry | dr.ChildDeviceEntry | None:
    found = (DOMAIN, f"{SERIAL_NUMBER}_{identifier}")
    return registry.async_get_child_device_by_identifier(
        found, entry.entry_id
    ) or registry.async_get_device_by_identifier(found, entry.entry_id)


async def _check_the_installation(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> SentioData:
    data: SentioData = config_entry.runtime_data
    await data.client.refresh(PollRate.SCAN)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED
    return config_entry.runtime_data


@pytest.mark.parametrize(
    ("identifier", "name"),
    [
        ("outdoor", "outdoor"),
        ("hc_source", "Heating/cooling source"),
        ("boiler_heat_pump", "Heat pump / Boiler"),
        ("thermistor_inputs", "Thermistor inputs"),
        ("dhw_tank", "Hot water tank"),
        ("buffer_tank", "Buffer tank"),
        ("hcc_1", "Sentio HCC 1"),
        ("hcc_2", "Sentio HCC 2"),
        ("itc_1", "Inlet temperature controller 1"),
    ],
)
async def test_each_part_of_the_controller_is_a_device_under_it(
    hass: HomeAssistant,
    loaded: SentioData,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    identifier: str,
    name: str,
) -> None:
    part = device_registry.async_get_child_device_by_identifier(
        (DOMAIN, f"{SERIAL_NUMBER}_{identifier}"), config_entry.entry_id
    )
    assert part is not None
    assert (part.name, part.parent_device_id) == (name, loaded.controller_device_id)


@pytest.mark.parametrize(
    ("identifier", "name", "model"),
    [
        ("ventilation_unit_1", "Ventilation unit 1", "Comfort 200"),
        ("dehumidifier_1", "Dehumidifier 1", "P300/S300"),
    ],
)
async def test_a_unit_the_controller_reaches_is_a_device_of_its_own(
    hass: HomeAssistant,
    loaded: SentioData,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    identifier: str,
    name: str,
    model: str,
) -> None:
    unit = device_registry.async_get_device_by_identifier(
        (DOMAIN, f"{SERIAL_NUMBER}_{identifier}"), config_entry.entry_id
    )
    assert unit is not None
    assert (unit.name, unit.model) == (name, model)
    assert unit.via_device_id == loaded.controller_device_id


@pytest.mark.parametrize("controller", [installation()])
async def test_a_controller_without_the_objects_has_no_devices_for_them(
    hass: HomeAssistant,
    loaded: SentioData,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    for identifier in ("outdoor", "hc_source", "dhw_tank", "hcc_1", "ventilation_unit_1"):
        assert _object(device_registry, config_entry, identifier) is None, identifier


async def test_the_objects_show_their_states_and_measurements(
    hass: HomeAssistant, loaded: SentioData
) -> None:
    for entity_id, value in (
        ("sensor.hot_water_tank_temperature", "52.3"),
        ("sensor.hot_water_tank_state", "heating"),
        ("sensor.buffer_tank_upper_temperature", "45.0"),
        ("sensor.inlet_temperature_controller_1_inlet_temperature", "35.1"),
        ("sensor.sentio_hcc_1_state", "idle"),
        ("sensor.sentio_hcc_1_pump", "idle"),
        ("sensor.heat_pump_boiler_state", "idle"),
        ("sensor.ventilation_unit_1_state", "comfort"),
        ("sensor.ventilation_unit_1_supply_fan_speed", "1250"),
        ("sensor.dehumidifier_1_drying", "drying"),
    ):
        assert _state(hass, entity_id) == value, entity_id
    state = hass.states.get("sensor.hot_water_tank_temperature")
    assert state is not None and state.attributes[ATTR_UNIT_OF_MEASUREMENT] == "°C"


async def test_installer_settings_and_thermistors_are_disabled_by_default(
    hass: HomeAssistant, loaded: SentioData, entity_registry: er.EntityRegistry
) -> None:
    def entity(platform: str, point: str) -> er.RegistryEntry:
        entity_id = entity_registry.async_get_entity_id(
            platform, DOMAIN, f"{SERIAL_NUMBER}_{point}"
        )
        assert entity_id is not None, point
        found = entity_registry.async_get(entity_id)
        assert found is not None
        return found

    slope = entity("number", "hcc_1_heat_curve_slope")
    assert (slope.disabled_by, slope.entity_category) == (
        er.RegistryEntryDisabler.INTEGRATION,
        EntityCategory.CONFIG,
    )
    assert entity("sensor", "thermistor_t1_temp").disabled_by is not None
    assert entity("sensor", "hcc_1_state").disabled_by is None


async def test_every_number_has_a_range_also_where_it_is_disabled_by_default(
    hass: HomeAssistant, loaded: SentioData
) -> None:
    for target, _ in all_targets(loaded, NUMBERS):
        (point,) = loaded.client.select([target.key])
        lowest, highest, _ = value_range(point)
        assert lowest < highest, target.key


async def test_the_hot_water_tank_is_set_from_home_assistant(
    hass: HomeAssistant, loaded: SentioData, controller: SimulatedModbusDevice
) -> None:
    await hass.services.async_call(
        "number",
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: "number.hot_water_tank_setpoint", ATTR_VALUE: 60},
        blocking=True,
    )
    await hass.services.async_call(
        "select",
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: "select.hot_water_tank_mode", ATTR_OPTION: "eco"},
        blocking=True,
    )
    await hass.services.async_call(
        "switch",
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: "switch.hot_water_tank_exclude_from_vacation"},
        blocking=True,
    )
    assert [controller.holding_registers[a] for a in (6621, 6617, 6625)] == [6000, 2, 1]


@pytest.mark.parametrize("controller", [installation()])
async def test_an_object_set_up_later_becomes_a_device(
    hass: HomeAssistant,
    loaded: SentioData,
    config_entry: MockConfigEntry,
    controller: SimulatedModbusDevice,
    device_registry: dr.DeviceRegistry,
) -> None:
    add_objects(controller)
    await _check_the_installation(hass, config_entry)
    assert _object(device_registry, config_entry, "hcc_1") is not None


async def test_an_object_taken_away_loses_its_device(
    hass: HomeAssistant,
    loaded: SentioData,
    config_entry: MockConfigEntry,
    controller: SimulatedModbusDevice,
    device_registry: dr.DeviceRegistry,
) -> None:
    take_away(controller, 61000)
    await _check_the_installation(hass, config_entry)
    assert _object(device_registry, config_entry, "ventilation_unit_1") is None
    assert _object(device_registry, config_entry, "dehumidifier_1") is not None


async def test_a_rooms_drying_and_ventilation_show_their_own_states(
    hass: HomeAssistant,
    loaded: SentioData,
    config_entry: MockConfigEntry,
    controller: SimulatedModbusDevice,
    entity_registry: er.EntityRegistry,
) -> None:
    """Disabled by default; room 1 is associated with both only after setup."""
    base = room_base(1)
    controller.input_registers.update({base + 14: 1, base + 16: 1, base + 19: 2, base + 21: 4})
    await _check_the_installation(hass, config_entry)
    for entity_id in ("sensor.kitchen_drying_state", "sensor.kitchen_ventilation_state"):
        found = entity_registry.async_get(entity_id)
        assert found is not None and found.disabled_by is not None, entity_id
        entity_registry.async_update_entity(entity_id, disabled_by=None)
    await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert _state(hass, "sensor.kitchen_drying_state") == "drying"
    assert _state(hass, "sensor.kitchen_ventilation_state") == "comfort"
