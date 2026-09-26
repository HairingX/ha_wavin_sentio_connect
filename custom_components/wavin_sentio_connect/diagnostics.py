"""What a bug report needs: the installation, every value with its quality, and what is missing."""

from __future__ import annotations

from enum import IntEnum
from typing import Any

from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from modbus_event_connect import Status

from .data import SentioConfigEntry

REDACTED = "**REDACTED**"

REDACTED_VALUES = ("serial_number", "location_name")
"""Values that identify the controller or its owner."""


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SentioConfigEntry
) -> dict[str, Any]:
    """The client's picture of the controller, without its address or identity.

    The entry's title and unique id are left out: they are the location's name and the
    controller's serial number.
    """
    data = entry.runtime_data
    client = data.client
    return {
        "entry": {
            "version": entry.version,
            "minor_version": entry.minor_version,
            "data": {
                key: REDACTED if key == CONF_HOST else setting
                for key, setting in entry.data.items()
            },
        },
        "model": client.model.name,
        "status": {status.name: client.status(status).value for status in Status},
        "rooms": [
            {"number": room.number, "is_dummy": room.is_dummy} for room in data.rooms
        ],
        "peripherals": [
            {"slot": peripheral.slot, "model": peripheral.model, "owner": peripheral.owner}
            for peripheral in data.peripherals
        ],
        "values": {
            str(key): (
                REDACTED
                if key.endswith(REDACTED_VALUES)
                else {
                    "value": _plain(current.value),
                    "quality": current.quality.name,
                    "raw": list(current.raw),
                }
            )
            for key, current in sorted(client.values.items())
        },
        "unavailable": {
            str(key): reason for key, reason in sorted(client.unavailable_reasons.items())
        },
    }


def _plain(value: object) -> object:
    """A value JSON can hold: a state by its name."""
    return value.name if isinstance(value, IntEnum) else value
