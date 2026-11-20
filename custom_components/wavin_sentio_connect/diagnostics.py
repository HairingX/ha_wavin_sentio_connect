"""What a bug report needs to show the controller works: the versions, the installation, every
value with its quality, what is missing, the latest writes with how each ended, and how the link
answers."""

from __future__ import annotations

from enum import Enum
from importlib import metadata
from typing import Any, cast

from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration
from wavin_sentio_connect import Client, DataValue, Key, Status

from .const import DOMAIN
from .data import SentioConfigEntry

REDACTED = "**REDACTED**"

REDACTED_VALUES = ("serial_number", "location_name", "modbus_password")
"""The ends of the keys whose values identify the controller or its owner, or are a credential."""

LIBRARIES = ("wavin_sentio_connect", "modbus_event_connect", "event_connect")
"""The libraries whose installed versions a report names."""


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SentioConfigEntry
) -> dict[str, Any]:
    """The client's picture of the controller and the writes sent to it, without its address or
    identity.

    The entry's title and unique id are left out: they are the location's name and the
    controller's serial number. `writes` holds the latest writes of each key, the newest last,
    each with how it ended and the first read of the key after it.
    """
    data = entry.runtime_data
    client = data.client
    integration = await async_get_integration(hass, DOMAIN)
    link = dict(client.diagnostics())
    level = link.pop("level")
    writes = cast(dict[str, list[dict[str, Any]]], link.pop("writes"))
    return {
        "entry": {
            "version": entry.version,
            "minor_version": entry.minor_version,
            "data": {
                key: REDACTED if key == CONF_HOST else setting
                for key, setting in entry.data.items()
            },
        },
        "integration_version": None if integration.version is None else str(integration.version),
        "libraries": {name: _version(name) for name in LIBRARIES},
        "model": client.model.name,
        "identity": {
            name: REDACTED if name.endswith(REDACTED_VALUES) else found
            for name, found in client.identity.items()
        },
        "level": level,
        "status": {status.name: client.status(status).value for status in Status},
        "seconds_until_next_poll": client.seconds_until_next_poll(),
        "silent": client.silent,
        "silent_for": client.silent_for,
        "values": {
            str(key): _hidden(key, _value(client, key, current))
            for key, current in sorted(client.values.items())
        },
        "unavailable": {
            str(key): reason for key, reason in sorted(client.unavailable_reasons.items())
        },
        "writes": {
            key: [_write(key, record) for record in records] for key, records in writes.items()
        },
        "link": link,
        "rooms": [
            {"number": room.number, "is_dummy": room.is_dummy} for room in data.rooms
        ],
        "peripherals": [
            {"slot": peripheral.slot, "model": peripheral.model, "owner": peripheral.owner}
            for peripheral in data.peripherals
        ],
    }


def _value(client: Client, key: Key[Any], current: DataValue[Any]) -> dict[str, Any]:
    """`current`, the value of `key`, as plain data: when the controller last answered it, and
    how many reads of it have failed since."""
    point = client.points.get(key)
    return {
        "value": _plain(current.value),
        "raw": list(current.raw),
        "quality": current.quality.name,
        "certainty": None if point is None else str(point.certainty),
        "at": current.timestamp.isoformat(),
        "consecutive_failures": client.consecutive_failures(str(key)),
    }


def _write(key: str, record: dict[str, Any]) -> dict[str, Any]:
    """The write `record` of `key`, its read-back included, with what identifies left out."""
    read_back = cast(dict[str, Any] | None, record["read_back"])
    return {**_hidden(key, record), "read_back": None if read_back is None else _hidden(key, read_back)}


def _hidden(key: str, found: dict[str, Any]) -> dict[str, Any]:
    """`found` with its `value` and `raw` left out where `key`'s value identifies the controller
    or its owner, or is a credential; a value that is None stays, as it says nothing."""
    if found["value"] is None or not key.endswith(REDACTED_VALUES):
        return found
    return {**found, "value": REDACTED, "raw": REDACTED}


def _plain(value: object) -> object:
    """`value` as JSON holds it: a state by its name."""
    return value.name if isinstance(value, Enum) else value


def _version(name: str) -> str | None:
    """The installed version of the package `name`; None if it is not installed."""
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None
