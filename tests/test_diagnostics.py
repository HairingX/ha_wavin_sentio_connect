"""A bug report's diagnostics: complete, without the address or the controller's identity."""

from __future__ import annotations

import json

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.wavin_sentio_connect.data import SentioData
from custom_components.wavin_sentio_connect.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .conftest import HOST, SERIAL_NUMBER


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
    assert values["room_1_state"] == {"value": "HEATING", "quality": "GOOD", "raw": [2]}
    assert diagnostics["status"] == {"CONNECTED": True, "WRITE_PENDING": False}
