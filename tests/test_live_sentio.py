"""The integration against a real Sentio, read-only: added through its config flow, loaded,
every room a thermostat, and unloaded again.

Skipped unless a controller is configured, as an IP address:

    SENTIO_HOST=<device-ip>              (environment variable)
    SENTIO_HOST = "<device-ip>"          (in mysecrets.py, which is gitignored)

The client is read-only, so every write is refused before it reaches the controller.
"""

from __future__ import annotations

import importlib
import os
from collections.abc import Iterator
from typing import Any

import pytest
import pytest_socket
from homeassistant.config_entries import (
    SOURCE_USER,
    ConfigEntry,
    ConfigEntryState,
    ConfigFlowResult,
)
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from modbus_event_connect import Client, Status
from wavin_sentio_connect import create_client

from custom_components.wavin_sentio_connect.const import CONF_UNIT_ID, DOMAIN
from custom_components.wavin_sentio_connect.data import SentioData


def _host() -> str | None:
    if host := os.environ.get("SENTIO_HOST"):
        return host
    try:
        secrets = importlib.import_module("mysecrets")
    except ModuleNotFoundError:
        return None
    found = getattr(secrets, "SENTIO_HOST", None)
    return found if isinstance(found, str) else None


HOST = _host()

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(HOST is None, reason="no Sentio configured (SENTIO_HOST)"),
]


@pytest.fixture
def real_link(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[Client]]:
    """Every client the integration makes reaches the real controller, read-only."""
    assert HOST is not None
    pytest_socket.enable_socket()
    pytest_socket.socket_allow_hosts([HOST, "127.0.0.1"])
    made: list[Client] = []

    def read_only(host: str, *, port: int, unit_id: int, **_: Any) -> Client:
        client = create_client(host, port=port, unit_id=unit_id, read_only=True)
        made.append(client)
        return client

    monkeypatch.setattr(
        "custom_components.wavin_sentio_connect.data.create_client", read_only
    )
    yield made


async def test_a_real_controller_is_added_and_every_room_is_a_thermostat(
    hass: HomeAssistant, real_link: list[Client]
) -> None:
    started = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    # HA declares the flow manager's user input as a bare `dict`.
    flow: Any = hass.config_entries.flow
    result: ConfigFlowResult = await flow.async_configure(
        started["flow_id"], {CONF_HOST: HOST, CONF_PORT: 502, CONF_UNIT_ID: 1}
    )
    assert result.get("type") is FlowResultType.CREATE_ENTRY, result
    entry = result.get("result")
    assert isinstance(entry, ConfigEntry)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    data: SentioData = entry.runtime_data
    assert data.client.status(Status.CONNECTED).value is True
    climates = hass.states.async_all("climate")
    assert len(climates) == len(data.rooms) > 0
    assert all(state.state != "unavailable" for state in climates)
    assert all(not client.status(Status.WRITE_PENDING).value for client in real_link)

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert data.client.status(Status.CONNECTED).value is False
