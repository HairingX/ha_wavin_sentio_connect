"""Adding a controller, and changing where it is reached."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
import voluptuous as vol
from homeassistant.config_entries import (
    SOURCE_DHCP,
    SOURCE_USER,
    ConfigEntry,
    ConfigEntryState,
    ConfigFlowResult,
)
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from modbus_event_connect import Client, Status, UnsupportedDeviceError
from modbus_event_connect.testing import SimulatedModbusDevice
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.wavin_sentio_connect.config_flow import SCHEMA, Controller
from custom_components.wavin_sentio_connect.const import CONF_UNIT_ID, DOMAIN
from custom_components.wavin_sentio_connect.data import SentioData

from .conftest import HOST, SERIAL_NUMBER, entry_data, installation, text


async def _start(hass: HomeAssistant) -> str:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result.get("type") is FlowResultType.FORM
    assert result.get("step_id") == "user"
    return result["flow_id"]


async def _submit(
    hass: HomeAssistant, flow_id: str, user_input: dict[str, Any]
) -> ConfigFlowResult:
    # HA declares the flow manager's user input as a bare `dict`.
    flow: Any = hass.config_entries.flow
    result: ConfigFlowResult = await flow.async_configure(flow_id, user_input)
    return result


def _schema(result: ConfigFlowResult) -> dict[str, vol.Marker]:
    schema = result.get("data_schema")
    assert schema is not None
    markers: dict[str, vol.Marker] = {str(key): key for key in schema.schema}
    return markers


async def test_a_controller_is_added_by_its_serial_number_and_named_as_its_location(
    hass: HomeAssistant, simulated_link: list[Client]
) -> None:
    flow = await _start(hass)
    result = await _submit(
        hass, flow, {CONF_HOST: f"  {HOST} ", CONF_PORT: 502, CONF_UNIT_ID: 1}
    )
    assert result.get("type") is FlowResultType.CREATE_ENTRY
    assert result.get("title") == "Wavin Sentio Home"
    assert result.get("data") == entry_data()
    entry = result.get("result")
    assert isinstance(entry, ConfigEntry)
    assert entry.unique_id == str(SERIAL_NUMBER)
    # The flow lets go of the controller; the config entry makes its own connection.
    flow_client, entry_client = simulated_link
    assert flow_client.status(Status.CONNECTED).value is False
    runtime: SentioData = entry.runtime_data
    assert entry_client is runtime.client


def test_the_form_offers_the_manuals_port_and_unit_id() -> None:
    assert SCHEMA({CONF_HOST: HOST}) == entry_data()


async def test_an_address_where_nothing_answers_is_reported_and_can_be_corrected(
    hass: HomeAssistant,
) -> None:
    flow = await _start(hass)
    result = await _submit(hass, flow, entry_data(host="nothing.example"))
    assert result.get("type") is FlowResultType.FORM
    assert result.get("errors") == {"base": "cannot_connect"}
    result = await _submit(hass, flow, entry_data())
    assert result.get("type") is FlowResultType.CREATE_ENTRY


async def test_a_unit_id_nothing_answers_to_is_reported(hass: HomeAssistant) -> None:
    flow = await _start(hass)
    result = await _submit(hass, flow, {**entry_data(), CONF_UNIT_ID: 2})
    assert result.get("errors") == {"base": "cannot_connect"}


async def test_an_empty_host_is_refused_before_anything_is_sent(
    hass: HomeAssistant, simulated_link: list[Client]
) -> None:
    flow = await _start(hass)
    result = await _submit(hass, flow, {CONF_HOST: "   ", CONF_PORT: 502, CONF_UNIT_ID: 1})
    assert result.get("errors") == {CONF_HOST: "invalid_host"}
    assert simulated_link == []


async def test_a_controller_without_a_serial_number_cannot_be_added(
    hass: HomeAssistant, controller: SimulatedModbusDevice
) -> None:
    controller.input_registers[15] = controller.input_registers[16] = 0xFFFF
    flow = await _start(hass)
    result = await _submit(hass, flow, entry_data())
    assert result.get("errors") == {"base": "no_serial_number"}


async def test_a_controller_without_a_location_name_is_titled_by_the_product(
    hass: HomeAssistant, controller: SimulatedModbusDevice
) -> None:
    controller.holding_registers.update(dict(enumerate(text(""), start=10)))
    flow = await _start(hass)
    result = await _submit(hass, flow, entry_data())
    assert result.get("title") == "Wavin Sentio"


async def test_adding_a_configured_controller_again_moves_it_to_the_new_address(
    hass: HomeAssistant,
) -> None:
    old = MockConfigEntry(
        domain=DOMAIN,
        unique_id=str(SERIAL_NUMBER),
        data={CONF_HOST: "old.example", CONF_PORT: 502, CONF_UNIT_ID: 1},
    )
    old.add_to_hass(hass)
    flow = await _start(hass)
    result = await _submit(hass, flow, entry_data())
    assert result.get("type") is FlowResultType.ABORT
    assert result.get("reason") == "already_configured"
    assert old.data[CONF_HOST] == HOST


async def test_reconfigure_shows_the_current_settings(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reconfigure_flow(hass)
    assert result.get("step_id") == "reconfigure"
    suggested: dict[str, Any] = {}
    for name, marker in _schema(result).items():
        description: dict[str, Any] = marker.description or {}
        suggested[name] = description.get("suggested_value")
    assert suggested == entry_data()


async def test_reconfigure_moves_a_loaded_controller_to_its_new_address(
    hass: HomeAssistant, config_entry: MockConfigEntry, simulated_link: list[Client]
) -> None:
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry, data={**config_entry.data, CONF_HOST: "old.example"}
    )
    await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY

    result = await config_entry.start_reconfigure_flow(hass)
    result = await _submit(hass, result["flow_id"], entry_data())
    assert result.get("type") is FlowResultType.ABORT
    assert result.get("reason") == "reconfigure_successful"
    await hass.async_block_till_done()
    assert config_entry.data == entry_data()
    assert config_entry.unique_id == str(SERIAL_NUMBER)
    assert config_entry.state is ConfigEntryState.LOADED
    runtime: SentioData = config_entry.runtime_data
    assert runtime.client.status(Status.CONNECTED).value is True
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_reconfigure_refuses_another_controller(
    hass: HomeAssistant, config_entry: MockConfigEntry, controller: SimulatedModbusDevice
) -> None:
    config_entry.add_to_hass(hass)
    controller.input_registers.update(installation(serial_number=9999).input_registers)
    result = await config_entry.start_reconfigure_flow(hass)
    result = await _submit(hass, result["flow_id"], entry_data())
    assert result.get("type") is FlowResultType.ABORT
    assert result.get("reason") == "wrong_device"
    assert config_entry.unique_id == str(SERIAL_NUMBER)


async def test_reconfigure_reports_an_address_where_nothing_answers(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reconfigure_flow(hass)
    result = await _submit(hass, result["flow_id"], entry_data(host="nothing.example"))
    assert result.get("type") is FlowResultType.FORM
    assert result.get("errors") == {"base": "cannot_connect"}
    assert config_entry.data[CONF_HOST] == HOST


async def test_a_device_the_library_does_not_support_is_reported(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def unsupported(settings: Mapping[str, Any]) -> Controller:
        raise UnsupportedDeviceError("simulated")

    monkeypatch.setattr(
        "custom_components.wavin_sentio_connect.config_flow.identify", unsupported
    )
    flow = await _start(hass)
    result = await _submit(hass, flow, entry_data())
    assert result.get("errors") == {"base": "unsupported_device"}


async def test_an_unexpected_error_is_logged_and_reported(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def failing(settings: Mapping[str, Any]) -> Controller:
        raise RuntimeError("simulated")

    monkeypatch.setattr(
        "custom_components.wavin_sentio_connect.config_flow.identify", failing
    )
    flow = await _start(hass)
    result = await _submit(hass, flow, entry_data())
    assert result.get("errors") == {"base": "unknown"}
    assert "Unexpected error while connecting to the controller" in caplog.text


def _announced(ip: str = HOST) -> DhcpServiceInfo:
    """A controller's DHCP announcement, as Home Assistant hands it on (host name lower case)."""
    return DhcpServiceInfo(ip=ip, hostname="wavin sentio ccu#1234", macaddress="aabbcc123456")


async def _discover(hass: HomeAssistant, ip: str = HOST) -> ConfigFlowResult:
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_DHCP}, data=_announced(ip)
    )


async def test_a_discovered_controller_is_added_once_the_user_confirms(
    hass: HomeAssistant,
) -> None:
    result = await _discover(hass)
    assert result.get("type") is FlowResultType.FORM
    assert result.get("step_id") == "discovery_confirm"
    assert result.get("description_placeholders") == {"name": "Wavin Sentio Home", "host": HOST}
    result = await _submit(hass, result["flow_id"], {})
    assert result.get("type") is FlowResultType.CREATE_ENTRY
    assert result.get("title") == "Wavin Sentio Home"
    assert result.get("data") == entry_data()
    entry = result.get("result")
    assert isinstance(entry, ConfigEntry) and entry.unique_id == str(SERIAL_NUMBER)


async def test_a_configured_controller_discovered_at_a_new_address_moves_there(
    hass: HomeAssistant,
) -> None:
    old = MockConfigEntry(
        domain=DOMAIN,
        unique_id=str(SERIAL_NUMBER),
        data={CONF_HOST: "old.example", CONF_PORT: 502, CONF_UNIT_ID: 1},
    )
    old.add_to_hass(hass)
    result = await _discover(hass)
    assert result.get("type") is FlowResultType.ABORT
    assert result.get("reason") == "already_configured"
    assert old.data[CONF_HOST] == HOST


async def test_a_controller_discovered_at_its_configured_address_is_not_contacted(
    hass: HomeAssistant, config_entry: MockConfigEntry, simulated_link: list[Client]
) -> None:
    config_entry.add_to_hass(hass)
    result = await _discover(hass)
    assert result.get("reason") == "already_configured"
    assert simulated_link == []


async def test_a_discovered_address_where_nothing_answers_is_dropped(
    hass: HomeAssistant,
) -> None:
    result = await _discover(hass, ip="nothing.example")
    assert result.get("type") is FlowResultType.ABORT
    assert result.get("reason") == "cannot_connect"
