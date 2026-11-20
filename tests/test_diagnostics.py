"""A bug report's diagnostics: complete, without the address or the controller's identity."""

from __future__ import annotations

import json
from importlib import metadata

import pytest
from homeassistant.components.climate.const import SERVICE_SET_TEMPERATURE
from homeassistant.const import ATTR_ENTITY_ID, ATTR_TEMPERATURE
from homeassistant.core import HomeAssistant
from pytest_homeassistant.common import MockConfigEntry
from wavin_sentio_connect import PointKey
from wavin_sentio_connect.testing import FakeClock, SimulatedModbusDevice

from custom_components.wavin_sentio_connect.const import DOMAIN
from custom_components.wavin_sentio_connect.data import SentioData
from custom_components.wavin_sentio_connect.diagnostics import (
    REDACTED,
    async_get_config_entry_diagnostics,
)

from .conftest import HOST, SERIAL_NUMBER, entry_data, text

KITCHEN = "climate.wavin_sentio_controller_kitchen"


async def test_diagnostics_hold_every_value_but_not_the_address_or_identity(
    hass: HomeAssistant,
    loaded: SentioData,
    config_entry: MockConfigEntry,
) -> None:
    diagnostics = await async_get_config_entry_diagnostics(hass, config_entry)
    text = json.dumps(diagnostics)  # raises for anything JSON cannot hold
    assert HOST not in text
    assert str(SERIAL_NUMBER) not in text
    assert "Home" not in text
    values = diagnostics["values"]
    assert isinstance(values, dict)
    assert values["room_1_state"] == {
        "value": "HEATING",
        "raw": [2],
        "quality": "GOOD",
        "certainty": "reported",
        "at": "2026-01-01T00:00:00+00:00",
        "consecutive_failures": 0,
    }
    assert values["serial_number"]["value"] == values["serial_number"]["raw"] == REDACTED
    assert values["serial_number"]["quality"] == "GOOD"
    assert diagnostics["status"] == {"CONNECTED": True, "WRITE_PENDING": False}
    assert (diagnostics["model"], diagnostics["identity"], diagnostics["level"]) == (
        "Sentio", {}, "documented",
    )


async def test_diagnostics_say_how_the_link_answers_and_the_versions(
    hass: HomeAssistant, loaded: SentioData, config_entry: MockConfigEntry
) -> None:
    diagnostics = await async_get_config_entry_diagnostics(hass, config_entry)
    assert diagnostics["integration_version"] == "0.0.0"
    assert diagnostics["libraries"] == {
        "wavin_sentio_connect": metadata.version("wavin_sentio_connect"),
        "modbus_event_connect": metadata.version("modbus_event_connect"),
        "event_connect": metadata.version("event_connect"),
    }
    assert (diagnostics["silent"], diagnostics["silent_for"]) == (False, 0.0)
    assert diagnostics["seconds_until_next_poll"] is not None
    link = diagnostics["link"]
    assert link["requests"] > 0
    assert (link["open"], link["open_for"], link["openings"], link["gave_up"]) == (
        False, 0.0, 0, False,
    )
    assert link["refused_while_open"] == 0
    assert not {"level", "writes"} & set(link)


async def test_a_library_not_installed_has_no_version(
    hass: HomeAssistant,
    loaded: SentioData,
    config_entry: MockConfigEntry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(name: str) -> str:
        raise metadata.PackageNotFoundError(name)

    monkeypatch.setattr(metadata, "version", missing)
    diagnostics = await async_get_config_entry_diagnostics(hass, config_entry)
    assert set(diagnostics["libraries"].values()) == {None}


async def test_a_write_shows_that_the_controller_took_it_and_what_it_read_back(
    hass: HomeAssistant, loaded: SentioData, config_entry: MockConfigEntry, clock: FakeClock
) -> None:
    await hass.services.async_call(
        "climate",
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: KITCHEN, ATTR_TEMPERATURE: 22.5},
        blocking=True,
    )
    clock.advance(3600)
    await loaded.client.poll()
    diagnostics = await async_get_config_entry_diagnostics(hass, config_entry)
    (record,) = diagnostics["writes"]["room_1_temp_air_target"]
    assert (record["value"], record["raw"], record["attempts"]) == (22.5, [2250], 1)
    assert (record["outcome"], record["detail"]) == ("taken", "")
    assert record["sent_at"] and record["ended_at"]
    read_back = record["read_back"]
    assert (read_back["value"], read_back["quality"], read_back["raw"]) == (22.5, "GOOD", [2250])
    assert read_back["at"] > record["ended_at"]


LOCATION = "Recognisable Holiday Cottage"
SERIAL = 3_141_592_653
PERIPHERAL_SERIAL = 27_182
PASSWORD = 4_321


async def test_diagnostics_of_every_point_and_writes_hold_nothing_that_locates_or_identifies(
    hass: HomeAssistant, controller: SimulatedModbusDevice, clock: FakeClock
) -> None:
    """The serial numbers, the location's name and the Modbus password are recognisable; the name
    and the password are written too, and the name read back."""
    controller.input_registers.update({15: SERIAL >> 16, 16: SERIAL & 0xFFFF, 51203: PERIPHERAL_SERIAL})
    controller.holding_registers.update({6: 0, **dict(enumerate(text(LOCATION), start=10))})
    entry = MockConfigEntry(domain=DOMAIN, title=f"Wavin Sentio {LOCATION}", unique_id=str(SERIAL),
                            data=entry_data())
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    client = entry.runtime_data.client
    assert await client.write(PointKey.LOCATION_NAME, LOCATION.upper())
    assert await client.write(PointKey.MODBUS_PASSWORD, PASSWORD)
    clock.advance(3600)
    await client.refresh()
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    found = json.dumps(diagnostics)
    assert set(diagnostics["values"]) == {
        str(key) for key, point in client.points.items() if point.readable
    }
    (name,) = diagnostics["writes"]["location_name"]
    assert (name["outcome"], name["value"], name["raw"]) == ("taken", REDACTED, REDACTED)
    assert (name["read_back"]["value"], name["read_back"]["raw"]) == (REDACTED, REDACTED)
    (password,) = diagnostics["writes"]["modbus_password"]
    assert (password["outcome"], password["value"], password["raw"]) == ("taken", REDACTED, REDACTED)
    registers = [
        ", ".join(str(register) for register in text(name)[:2])
        for name in (LOCATION, LOCATION.upper())
    ]
    for secret in (HOST, LOCATION, LOCATION.upper(), str(SERIAL), str(PERIPHERAL_SERIAL),
                   f"{SERIAL >> 16}, {SERIAL & 0xFFFF}", str(PASSWORD), *registers):
        assert secret not in found, secret
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
