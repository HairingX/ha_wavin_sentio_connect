"""The devices of an installation: the controller, its rooms, and the peripherals it reaches."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.typing import UNDEFINED

from wavin_sentio_connect import LocationPointKey, SentioPeripheral

from .const import DOMAIN
from .data import SentioData, controller_model, value


def controller_identifier(data: SentioData) -> tuple[str, str]:
    return (DOMAIN, data.serial_number)


def room_identifier(data: SentioData, number: int) -> tuple[str, str]:
    return (DOMAIN, f"{data.serial_number}_room_{number}")


def peripheral_identifier(data: SentioData, serial_number: int) -> tuple[str, str]:
    return (DOMAIN, f"{data.serial_number}_peripheral_{serial_number}")


def current_identifiers(data: SentioData) -> set[tuple[str, str]]:
    """The identifiers of every device this installation has now."""
    return {
        controller_identifier(data),
        *(room_identifier(data, room.number) for room in data.rooms),
        *(
            peripheral_identifier(data, peripheral.serial_number)
            for peripheral in data.peripherals
            if peripheral.serial_number is not None
        ),
    }


@callback
def register_devices(hass: HomeAssistant, entry: ConfigEntry, data: SentioData) -> None:
    """Register the controller, each room as a part of it, and each peripheral through it;
    remove the devices the installation no longer has.

    The controller's names for its rooms and peripherals only name a device when it is created;
    after that, its name in Home Assistant is the one used. Records the device id of the
    controller and of each place in `data`. A peripheral that reports no serial number is left
    out: its slot is not a stable identity.
    """
    registry = dr.async_get(hass)
    client = data.client
    manufacturer = client.model.manufacturer
    software = (
        value(client, LocationPointKey.SOFTWARE_MAJOR),
        value(client, LocationPointKey.SOFTWARE_MINOR),
    )
    hardware = value(client, LocationPointKey.HARDWARE_MAJOR)
    controller = registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={controller_identifier(data)},
        manufacturer=manufacturer,
        model=controller_model(client),
        translation_key="controller",
        serial_number=data.serial_number,
        sw_version=f"{software[0]}.{software[1]}" if None not in software else None,
        hw_version=str(hardware) if hardware is not None else None,
    )

    data.controller_device_id = controller.id
    data.places = {0: controller.id}
    room_names: dict[int, str] = {}
    for room in data.rooms:
        identifier = room_identifier(data, room.number)
        new = registry.async_get_child_device_by_identifier(identifier, entry.entry_id) is None
        numbered = new and not room.name
        # A room is a part of the controller, not a device it reaches.
        part = registry.async_get_or_create_child(
            config_entry_id=entry.entry_id,
            identifiers={identifier},
            parent_device_id=controller.id,
            name=(room.name or None) if new else UNDEFINED,
            # A room never named on the controller is named by its number.
            translation_key="room" if numbered else None,
            translation_placeholders={"number": str(room.number)} if numbered else None,
        )
        data.places[room.number] = part.id
        room_names[room.number] = part.name_by_user or part.name or ""

    for peripheral in data.peripherals:
        if peripheral.serial_number is None:
            continue
        identifier = peripheral_identifier(data, peripheral.serial_number)
        new = registry.async_get_device_by_identifier(identifier, entry.entry_id) is None
        registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={identifier},
            manufacturer=manufacturer,
            model=peripheral.model,
            name=_peripheral_name(peripheral, room_names) if new else UNDEFINED,
            serial_number=str(peripheral.serial_number),
            via_device_id=controller.id,
        )

    current = current_identifiers(data)
    devices: list[dr.AnyDeviceEntry] = [
        *dr.async_entries_for_config_entry(registry, entry.entry_id),
        *dr.async_child_entries_for_config_entry(registry, entry.entry_id),
    ]
    for device in devices:
        if not device.identifiers & current:
            registry.async_remove_device(device.id)


def _peripheral_name(peripheral: SentioPeripheral, room_names: dict[int, str]) -> str:
    """The peripheral's name on the controller, or its model, after the room it belongs to.

    One that belongs to the controller itself, or whose name already starts with its room's,
    keeps its own.
    """
    own = peripheral.name or peripheral.model
    room = room_names.get(peripheral.owner) if peripheral.owner else None
    return own if not room or own.startswith(room) else f"{room} {own}"
