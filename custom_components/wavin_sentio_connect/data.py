"""The client behind a config entry, and how one is made."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from homeassistant.config_entries import ConfigEntry
from modbus_event_connect import Client, Key

from wavin_sentio_connect import (
    LocationPointKey,
    SentioPeripheral,
    SentioRoom,
    create_client,
)

type SentioConfigEntry = ConfigEntry[SentioData]


@dataclass
class SentioData:
    """What a loaded config entry holds."""

    client: Client
    serial_number: str
    """The controller's serial number, which is also the config entry's unique id."""
    rooms: list[SentioRoom]
    """The rooms the controller reported when it connected."""
    peripherals: list[SentioPeripheral]
    """The peripherals paired with the controller when it connected."""
    poller: asyncio.Task[None] | None = field(default=None, repr=False)
    controller_device_id: str = ""
    """The controller's device id, set when the devices are registered."""
    places: dict[int, str] = field(default_factory=dict[int, str])
    """The device id of each place a peripheral can belong to: 0 the controller, 1-16 a room.
    Set when the devices are registered."""


def new_client(host: str, port: int, unit_id: int) -> Client:
    """A client for the controller at `host`, not yet connected."""
    return create_client(host, port=port, unit_id=unit_id)


def value[T](client: Client, key: Key[T]) -> T | None:
    """The current value of `key`: None when it was never read or holds no reading."""
    current = client.value(key)
    return current.value if current is not None else None


def serial_number(client: Client) -> str | None:
    """The controller's serial number as read during connect, or None if it gave none."""
    found = value(client, LocationPointKey.SERIAL_NUMBER)
    return str(found) if found is not None else None


def controller_model(client: Client) -> str | None:
    """The controller's type as it reports it, such as "CCU-208"; None if it reports none."""
    found = value(client, LocationPointKey.DEVICE_TYPE)
    return found.name.replace("_", "-") if found is not None else None


def entry_title(client: Client) -> str:
    """What the entry is called: the product, then the location's name if the controller has
    one, such as "Wavin Sentio Home"."""
    product = f"{client.model.manufacturer} {client.model.name}"
    location = value(client, LocationPointKey.LOCATION_NAME)
    return f"{product} {location}" if location else product
