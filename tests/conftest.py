"""A simulated Sentio installation behind the integration, and a config entry for it.

The integration runs the real client and the real Sentio model; only the Modbus link is
simulated. The clock moves only when a test advances it, so nothing is read by itself.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from modbus_event_connect import Client
from modbus_event_connect.testing import (
    FakeClock,
    SimulatedModbusDevice,
    SimulatedModbusGateway,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry
from wavin_sentio_connect import PeripheralType, create_client_on

from custom_components.wavin_sentio_connect.const import CONF_UNIT_ID, DOMAIN
from custom_components.wavin_sentio_connect.data import SentioData

HOST = "sentio.example"
"""The address the simulated controller answers at; any other host answers nothing."""
SERIAL_NUMBER = 1234
ROOM_BASE = 100
PERIPHERAL_BASE = 51100


def text(value: str, registers: int = 16) -> list[int]:
    """`value` as the controller stores a string: UTF-8, NUL padded, two bytes a register."""
    raw = value.encode().ljust(registers * 2, b"\x00")
    return [int.from_bytes(raw[i : i + 2], "big") for i in range(0, len(raw), 2)]


def room_base(number: int) -> int:
    return number * ROOM_BASE


def peripheral_base(slot: int) -> int:
    return PERIPHERAL_BASE + slot * 100


def installation(*, serial_number: int = SERIAL_NUMBER) -> SimulatedModbusDevice:
    """A controller with three rooms and two peripherals.

    Room 1 "Kitchen" has a thermostat and radiators; room 2 has no name; room 3 "Hall" is a
    dummy room. Peripheral 1 is an RT-250 in room 1, peripheral 2 an LCD-200 on the location.
    """
    inputs: dict[int, int] = {
        1: 3, 2: 7, 10: 1, 11: 8, 12: 18, 13: 4, 14: 1530,
        15: serial_number >> 16, 16: serial_number & 0xFFFF, 20: 0,
    }
    holding: dict[int, int] = {
        1: 3, 2: 7, 5: 2, 26: 0, 27: 0, 28: 0, 29: 0, 30: 1,
        31: 0xFE0C, 32: 2000, 33: 1, 34: 0, 35: 60,
    }
    holding.update(dict(enumerate(text("Home"), start=10)))
    controller = SimulatedModbusDevice(
        input_registers=inputs,
        holding_registers=holding,
        discrete_inputs={1: 0, 2: 0},
        max_registers=32,
    )
    set_up_room(controller, 1, "Kitchen", air=2150)
    set_up_room(controller, 2, "", air=1900)
    set_up_room(controller, 3, "Hall", air=0x7FFF, dummy=True)
    pair(controller, 1, PeripheralType.RT_250, serial=222, owner=1, name="Kitchen RT")
    pair(controller, 2, PeripheralType.LCD_200, serial=333, owner=0, name="")
    return controller


def set_up_room(
    controller: SimulatedModbusDevice, number: int, name: str, *, air: int, dummy: bool = False
) -> None:
    """Configure room `number` on `controller`, associated with radiators."""
    base = room_base(number)
    inputs, holding = controller.input_registers, controller.holding_registers
    for offset in range(1, 29):
        if offset not in (8, 9, 10, 13):
            inputs[base + offset] = 0
    inputs[base + 1] = 2100
    inputs[base + 2] = 2
    inputs[base + 4] = air
    inputs[base + 5] = 2250
    inputs[base + 6] = 4550
    inputs[base + 7] = 950
    inputs[base + 11] = 81
    inputs[base + 27] = 1 if dummy else 0
    holding.update(dict(enumerate(text(name), start=base + 1)))
    for offset in range(17, 36):
        holding[base + offset] = 0
    holding[base + 17] = 1
    holding[base + 19] = 2100
    holding[base + 20] = 32
    holding[base + 21] = 1600
    holding[base + 22] = 1500
    holding[base + 35] = 1
    controller.discrete_inputs.update({base + bit: 0 for bit in (1, 2, 3, 4)})


def pair(
    controller: SimulatedModbusDevice,
    slot: int,
    kind: PeripheralType,
    *,
    serial: int,
    owner: int,
    name: str,
) -> None:
    """Pair a peripheral in `slot` on `controller`, owned by room `owner` (0: the location)."""
    base = peripheral_base(slot)
    controller.input_registers.update(
        {base + 1: kind, base + 2: 0, base + 3: serial, base + 4: owner, base + 5: 5}
    )
    controller.holding_registers.update(dict(enumerate(text(name), start=base + 1)))
    controller.discrete_inputs.update({base + bit: 0 for bit in (1, 2, 3, 4)})


def take_away(controller: SimulatedModbusDevice, base: int) -> None:
    """Remove every register of the block at `base`, as the controller does for an unused one."""
    for registers in (
        controller.input_registers,
        controller.holding_registers,
        controller.discrete_inputs,
    ):
        for address in [a for a in registers if base < a < base + 100]:
            del registers[address]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> Iterator[None]:
    yield


@pytest.fixture(autouse=True)
def no_deprecated_usage(caplog: pytest.LogCaptureFixture) -> Iterator[None]:
    """Fail a test in which Home Assistant reports this integration using something deprecated."""
    yield
    reports = [
        record.getMessage()
        for phase in ("setup", "call")
        for record in caplog.get_records(phase)
        if "Detected that custom integration 'wavin_sentio_connect'" in record.getMessage()
    ]
    assert reports == []


@pytest.fixture
def controller() -> SimulatedModbusDevice:
    """The simulated controller; change its registers to change what it answers."""
    return installation()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def gateway(controller: SimulatedModbusDevice) -> SimulatedModbusGateway:
    """The link to the controller; `link_down` makes it stop answering."""
    return SimulatedModbusGateway({1: controller})


@pytest.fixture(autouse=True)
def simulated_link(
    monkeypatch: pytest.MonkeyPatch, gateway: SimulatedModbusGateway, clock: FakeClock
) -> list[Client]:
    """Every client the integration makes reaches the simulated controller at HOST.

    Returns the clients made, in order.
    """
    made: list[Client] = []

    def create_client(host: str, *, port: int, unit_id: int, **_: Any) -> Client:
        link = gateway
        if host != HOST:
            link = SimulatedModbusGateway({})
            link.link_down = True
        client = create_client_on(link, unit_id=unit_id, clock=clock)
        made.append(client)
        return client

    monkeypatch.setattr(
        "custom_components.wavin_sentio_connect.data.create_client", create_client
    )
    return made


def entry_data(host: str = HOST) -> dict[str, Any]:
    return {CONF_HOST: host, CONF_PORT: 502, CONF_UNIT_ID: 1}


@pytest.fixture
def config_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Wavin Sentio Home",
        unique_id=str(SERIAL_NUMBER),
        data=entry_data(),
    )


@pytest.fixture
async def loaded(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> AsyncIterator[SentioData]:
    """The config entry, set up; unloaded again after the test."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    data: SentioData = config_entry.runtime_data
    yield data
    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
