"""Loading and unloading a controller's config entry, and its devices."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import WebSocketGenerator
from wavin_sentio_connect import (
    Client,
    PeripheralType,
    PollRate,
    Status,
    UnsupportedDeviceError,
)
from wavin_sentio_connect.testing import (
    FakeClock,
    SimulatedModbusDevice,
    SimulatedModbusGateway,
)

from custom_components.wavin_sentio_connect.const import DOMAIN
from custom_components.wavin_sentio_connect.data import SentioData

from .conftest import (
    SERIAL_NUMBER,
    entry_data,
    installation,
    pair,
    peripheral_base,
    room_base,
    set_up_room,
    take_away,
    text,
)


async def test_a_controller_that_does_not_answer_is_retried_later(
    hass: HomeAssistant, config_entry: MockConfigEntry, gateway: SimulatedModbusGateway
) -> None:
    gateway.link_down = True
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_another_controller_at_the_address_is_not_taken_for_the_configured_one(
    hass: HomeAssistant, config_entry: MockConfigEntry, controller: SimulatedModbusDevice
) -> None:
    controller.input_registers.update(installation(serial_number=9999).input_registers)
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    assert config_entry.reason is not None and "9999" in config_entry.reason


async def test_setup_connects_and_unload_stops_reading_and_disconnects(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED
    data: SentioData = config_entry.runtime_data
    assert data.client.status(Status.CONNECTED).value is True
    assert data.poller is not None and not data.poller.done()

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.NOT_LOADED
    assert data.poller.cancelled()
    assert data.client.status(Status.CONNECTED).value is False


def _device(
    registry: dr.DeviceRegistry, entry: MockConfigEntry, identifier: str
) -> dr.DeviceEntry:
    device = registry.async_get_device_by_identifier((DOMAIN, identifier), entry.entry_id)
    assert device is not None, identifier
    return device


def _room(
    registry: dr.DeviceRegistry, entry: MockConfigEntry, number: int
) -> dr.ChildDeviceEntry:
    room = registry.async_get_child_device_by_identifier(
        (DOMAIN, f"{SERIAL_NUMBER}_room_{number}"), entry.entry_id
    )
    assert room is not None, number
    return room


async def test_every_room_and_peripheral_is_a_device_under_the_controller(
    hass: HomeAssistant,
    loaded: SentioData,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    controller = _device(device_registry, config_entry, str(SERIAL_NUMBER))
    assert (controller.manufacturer, controller.model, controller.name) == (
        "Wavin",
        "CCU-208",
        "Wavin Sentio Controller",
    )
    assert (controller.sw_version, controller.hw_version) == ("18.4", "8")
    assert controller.serial_number == str(SERIAL_NUMBER)

    kitchen = _room(device_registry, config_entry, 1)
    assert kitchen.name == "Kitchen"
    assert kitchen.parent_device_id == controller.id
    unnamed = _room(device_registry, config_entry, 2)
    assert unnamed.name == "Room 2"

    thermostat = _device(device_registry, config_entry, f"{SERIAL_NUMBER}_peripheral_222")
    assert (thermostat.model, thermostat.name, thermostat.serial_number) == (
        "RT-250",
        "Kitchen RT",
        "222",
    )
    assert thermostat.via_device_id == controller.id
    display = _device(device_registry, config_entry, f"{SERIAL_NUMBER}_peripheral_333")
    assert display.name == "LCD-200"
    assert display.via_device_id == controller.id


async def test_a_room_registered_as_a_device_before_becomes_a_part_of_the_controller(
    hass: HomeAssistant, config_entry: MockConfigEntry, device_registry: dr.DeviceRegistry
) -> None:
    config_entry.add_to_hass(hass)
    before = device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        identifiers={(DOMAIN, f"{SERIAL_NUMBER}_room_1")},
        name="Kitchen",
    )
    # As when an earlier setup of the entry has ended.
    device_registry.async_config_entry_unloaded(config_entry.entry_id)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert _room(device_registry, config_entry, 1).id == before.id
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_a_peripheral_is_named_after_its_room(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    controller: SimulatedModbusDevice,
    device_registry: dr.DeviceRegistry,
) -> None:
    pair(controller, 3, PeripheralType.RT_250, serial=444, owner=2, name="RT-250")
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    for serial, name in (
        (444, "Room 2 RT-250"),
        (222, "Kitchen RT"),
        (333, "LCD-200"),
    ):
        device = _device(device_registry, config_entry, f"{SERIAL_NUMBER}_peripheral_{serial}")
        assert device.name == name, serial
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_a_room_renamed_in_home_assistant_is_shown_as_the_place_at_once(
    hass: HomeAssistant,
    loaded: SentioData,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    device_registry.async_update_child_device(
        _room(device_registry, config_entry, 1).id, name_by_user="Køkken"
    )
    await hass.async_block_till_done()
    state = hass.states.get("sensor.kitchen_rt_room")
    assert state is not None and state.state == "Køkken"


async def test_names_on_the_controller_only_name_a_device_when_it_is_created(
    hass: HomeAssistant,
    loaded: SentioData,
    config_entry: MockConfigEntry,
    controller: SimulatedModbusDevice,
    device_registry: dr.DeviceRegistry,
) -> None:
    controller.holding_registers.update(dict(enumerate(text("Scullery"), start=room_base(1) + 1)))
    controller.holding_registers.update(
        dict(enumerate(text("Scullery RT"), start=peripheral_base(1) + 1))
    )
    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert _room(device_registry, config_entry, 1).name == "Kitchen"
    thermostat = _device(device_registry, config_entry, f"{SERIAL_NUMBER}_peripheral_222")
    assert thermostat.name == "Kitchen RT"


async def test_each_peripheral_shows_the_place_it_belongs_to(
    hass: HomeAssistant, loaded: SentioData, entity_registry: er.EntityRegistry
) -> None:
    for entity_id, place in (
        ("sensor.kitchen_rt_room", "Kitchen"),
        ("sensor.lcd_200_room", "Wavin Sentio Controller"),
    ):
        state = hass.states.get(entity_id)
        assert state is not None and state.state == place, entity_id
        registered = entity_registry.async_get(entity_id)
        assert registered is not None
        assert registered.entity_category is EntityCategory.DIAGNOSTIC


async def test_only_a_device_the_installation_no_longer_has_can_be_removed(
    hass: HomeAssistant,
    loaded: SentioData,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    assert await async_setup_component(hass, "config", {})
    gone = device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        identifiers={(DOMAIN, f"{SERIAL_NUMBER}_peripheral_999")},
    )
    kitchen = _room(device_registry, config_entry, 1)
    client = await hass_ws_client(hass)
    for device, removable in ((kitchen, False), (gone, True)):
        await client.send_json_auto_id(
            {
                "type": "config/device_registry/remove",
                "device_id": device.id,
            }
        )
        response = await client.receive_json()
        assert response["success"] is removable


async def test_the_poller_reads_what_is_due_and_survives_a_failing_poll(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    controller: SimulatedModbusDevice,
    clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("custom_components.wavin_sentio_connect.POLL_TICK", 0.001)
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    data: SentioData = config_entry.runtime_data
    real_poll = data.client.poll
    failures = 0

    async def poll_failing_once() -> None:
        nonlocal failures
        if failures == 0:
            failures += 1
            raise RuntimeError("simulated")
        await real_poll()

    monkeypatch.setattr(data.client, "poll", poll_failing_once)
    controller.input_registers[104] = 2300
    clock.advance(60)
    shown: list[str] = []
    for _ in range(100):
        state = hass.states.get("sensor.kitchen_air_temperature")
        assert state is not None
        shown.append(state.state)
        if state.state == "23.0":
            break
        await asyncio.sleep(0.01)
    assert shown[-1] == "23.0"
    assert failures == 1
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_a_device_the_library_does_not_support_is_not_retried(
    hass: HomeAssistant, config_entry: MockConfigEntry, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def unsupported(self: Client) -> None:
        raise UnsupportedDeviceError("simulated")

    monkeypatch.setattr(Client, "connect", unsupported)
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.SETUP_ERROR


async def test_the_controller_stays_connected_when_its_entities_cannot_be_unloaded(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    data: SentioData = config_entry.runtime_data

    async def refuse(*_: object) -> bool:
        return False

    monkeypatch.setattr(hass.config_entries, "async_unload_platforms", refuse)
    assert not await hass.config_entries.async_unload(config_entry.entry_id)
    assert data.client.status(Status.CONNECTED).value is True
    assert data.poller is not None and not data.poller.done()

    # Home Assistant will not unload the entry again, so the test lets go of the controller.
    data.poller.cancel()
    await asyncio.wait([data.poller])
    await data.client.disconnect()


async def test_every_subscription_ends_when_the_entry_reloads_or_unloads(
    hass: HomeAssistant, config_entry: MockConfigEntry, monkeypatch: pytest.MonkeyPatch
) -> None:
    live: set[int] = set()
    made = 0

    def tracked(subscribe: Callable[..., Callable[[], None]]) -> Callable[..., Callable[[], None]]:
        def subscribing(client: Client, *args: Any, **kwargs: Any) -> Callable[[], None]:
            nonlocal made
            unsubscribe = subscribe(client, *args, **kwargs)
            made += 1
            token = made
            live.add(token)

            def ending() -> None:
                live.discard(token)
                unsubscribe()

            return ending

        return subscribing

    for name in ("subscribe", "subscribe_points", "subscribe_status"):
        monkeypatch.setattr(Client, name, tracked(getattr(Client, name)))
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert made > 0
    assert live == set()


async def test_with_polling_disabled_nothing_is_read_on_a_schedule(
    hass: HomeAssistant, controller: SimulatedModbusDevice, clock: FakeClock
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Wavin Sentio Home",
        unique_id=str(SERIAL_NUMBER),
        data=entry_data(),
        pref_disable_polling=True,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    data: SentioData = entry.runtime_data
    assert data.client.seconds_until_next_poll() is None
    controller.input_registers[room_base(1) + 4] = 2300
    clock.advance(3600)
    await data.client.poll()
    state = hass.states.get("sensor.kitchen_air_temperature")
    assert state is not None and state.state == "21.5"
    await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("polling", [True, False])
async def test_update_entity_reads_that_entity_from_the_controller(
    hass: HomeAssistant,
    controller: SimulatedModbusDevice,
    gateway: SimulatedModbusGateway,
    polling: bool,
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Wavin Sentio Home",
        unique_id=str(SERIAL_NUMBER),
        data=entry_data(),
        pref_disable_polling=not polling,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert await async_setup_component(hass, "homeassistant", {})
    controller.input_registers[room_base(1) + 4] = 2300
    gateway.requests.clear()
    await hass.services.async_call(
        "homeassistant",
        "update_entity",
        {"entity_id": "sensor.kitchen_air_temperature"},
        blocking=True,
    )
    state = hass.states.get("sensor.kitchen_air_temperature")
    assert state is not None and state.state == "23.0"
    assert {(r.address, r.count) for _, r in gateway.requests} == {(room_base(1) + 4, 1)}
    await hass.config_entries.async_unload(entry.entry_id)


# ======================================================== when the installation changes


async def _check_the_installation(hass: HomeAssistant, config_entry: MockConfigEntry) -> SentioData:
    """Check the controller for changes, as polling does, and let a reload finish."""
    data: SentioData = config_entry.runtime_data
    await data.client.refresh(PollRate.SCAN)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED
    return config_entry.runtime_data


async def test_an_unchanged_installation_is_not_reloaded(
    hass: HomeAssistant,
    loaded: SentioData,
    config_entry: MockConfigEntry,
    simulated_link: list[Client],
) -> None:
    await _check_the_installation(hass, config_entry)
    assert len(simulated_link) == 1


async def test_a_room_set_up_later_becomes_a_device_with_its_entities(
    hass: HomeAssistant,
    loaded: SentioData,
    config_entry: MockConfigEntry,
    controller: SimulatedModbusDevice,
    device_registry: dr.DeviceRegistry,
) -> None:
    set_up_room(controller, 4, "Office", air=2000)
    data = await _check_the_installation(hass, config_entry)
    assert [room.number for room in data.rooms] == [1, 2, 3, 4]
    office = _room(device_registry, config_entry, 4)
    assert office.name == "Office"
    state = hass.states.get("sensor.office_air_temperature")
    assert state is not None and state.state == "20.0"


async def test_with_new_entities_disabled_a_room_set_up_later_has_them_disabled(
    hass: HomeAssistant,
    controller: SimulatedModbusDevice,
    entity_registry: er.EntityRegistry,
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Wavin Sentio Home",
        unique_id=str(SERIAL_NUMBER),
        data=entry_data(),
        pref_disable_new_entities=True,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    set_up_room(controller, 4, "Office", air=2000)
    await _check_the_installation(hass, entry)
    office = entity_registry.async_get("sensor.office_air_temperature")
    assert office is not None and office.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    await hass.config_entries.async_unload(entry.entry_id)


async def test_a_room_taken_away_loses_its_device(
    hass: HomeAssistant,
    loaded: SentioData,
    config_entry: MockConfigEntry,
    controller: SimulatedModbusDevice,
    device_registry: dr.DeviceRegistry,
) -> None:
    take_away(controller, room_base(2))
    data = await _check_the_installation(hass, config_entry)
    assert [room.number for room in data.rooms] == [1, 3]
    assert device_registry.async_get_child_device_by_identifier(
        (DOMAIN, f"{SERIAL_NUMBER}_room_2"), config_entry.entry_id
    ) is None


async def test_an_entity_of_something_the_room_lost_is_removed(
    hass: HomeAssistant,
    loaded: SentioData,
    config_entry: MockConfigEntry,
    controller: SimulatedModbusDevice,
    entity_registry: er.EntityRegistry,
) -> None:
    controller.input_registers[room_base(1) + 27] = 1
    await _check_the_installation(hass, config_entry)
    assert entity_registry.async_get("sensor.kitchen_air_temperature") is None
    assert entity_registry.async_get("climate.kitchen") is not None


async def test_a_disabled_entity_the_installation_still_has_is_kept(
    hass: HomeAssistant,
    loaded: SentioData,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()
    kept = entity_registry.async_get("sensor.kitchen_radiators_state")
    assert kept is not None and kept.disabled_by is er.RegistryEntryDisabler.INTEGRATION


async def test_another_thermostat_in_a_slot_replaces_the_one_before(
    hass: HomeAssistant,
    loaded: SentioData,
    config_entry: MockConfigEntry,
    controller: SimulatedModbusDevice,
    device_registry: dr.DeviceRegistry,
) -> None:
    pair(controller, 1, PeripheralType.RT_250, serial=444, owner=1, name="Kitchen RT")
    await _check_the_installation(hass, config_entry)
    _device(device_registry, config_entry, f"{SERIAL_NUMBER}_peripheral_444")
    assert device_registry.async_get_device_by_identifier(
        (DOMAIN, f"{SERIAL_NUMBER}_peripheral_222"), config_entry.entry_id
    ) is None


async def test_a_thermostat_moved_to_another_room_shows_its_new_room(
    hass: HomeAssistant,
    loaded: SentioData,
    config_entry: MockConfigEntry,
    controller: SimulatedModbusDevice,
    device_registry: dr.DeviceRegistry,
) -> None:
    controller.input_registers[peripheral_base(1) + 4] = 2
    await _check_the_installation(hass, config_entry)
    state = hass.states.get("sensor.kitchen_rt_room")
    assert state is not None and state.state == "Room 2"
    thermostat = _device(device_registry, config_entry, f"{SERIAL_NUMBER}_peripheral_222")
    assert thermostat.name == "Kitchen RT", "a name is only given when the device is created"
