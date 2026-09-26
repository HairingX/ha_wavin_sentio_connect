"""The Wavin Sentio Connect integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr

from wavin_sentio_connect import (
    CannotConnectError,
    Client,
    DataValue,
    Key,
    PeripheralPointKey,
    PointKey,
    UnsupportedDeviceError,
    peripheral_key,
    peripherals,
    rooms,
)

from .const import CONF_UNIT_ID, DOMAIN, POLL_TICK
from .data import SentioConfigEntry, SentioData, new_client, serial_number
from .devices import current_identifiers, register_devices

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.CLIMATE,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(hass: HomeAssistant, entry: SentioConfigEntry) -> bool:
    """Connect to the controller, create its entities and start reading it."""
    host: str = entry.data[CONF_HOST]
    client = new_client(host, entry.data[CONF_PORT], entry.data[CONF_UNIT_ID])
    try:
        await client.connect()
    except CannotConnectError as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
            translation_placeholders={"host": host},
        ) from err
    except UnsupportedDeviceError as err:
        raise ConfigEntryError(
            translation_domain=DOMAIN, translation_key="unsupported_device"
        ) from err

    try:
        found = serial_number(client)
        if found is None or found != entry.unique_id:
            # Another controller now answers at this address; its entities would take over
            # the configured one's.
            raise ConfigEntryError(
                translation_domain=DOMAIN,
                translation_key="wrong_device",
                translation_placeholders={
                    "expected": str(entry.unique_id),
                    "found": found or "-",
                },
            )
        entry.runtime_data = SentioData(
            client=client,
            serial_number=found,
            rooms=rooms(client),
            peripherals=peripherals(client),
        )
        register_devices(hass, entry, entry.runtime_data)
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        await client.disconnect()
        raise

    _reload_when_the_installation_changes(hass, entry)
    # With polling disabled in the entry's system options, only what is asked for is read:
    # homeassistant.update_entity, and the read-back of a write. Changing it reloads the entry.
    client.set_scheduled_polling(not entry.pref_disable_polling)
    # Polling starts once the entities have subscribed: the client reads what is wanted.
    entry.runtime_data.poller = entry.async_create_background_task(
        hass, _poll(client), f"{DOMAIN} poll {entry.title}"
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SentioConfigEntry) -> bool:
    """Stop reading the controller and let go of it."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    data = entry.runtime_data
    if data.poller is not None:
        # Stopped before the disconnect, so no read runs against a closing connection.
        data.poller.cancel()
        await asyncio.wait([data.poller])
    await data.client.disconnect()
    return True


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: SentioConfigEntry, device: dr.AnyDeviceEntry
) -> bool:
    """Allow removing a device only when the installation no longer has it."""
    return not device.identifiers & current_identifiers(entry.runtime_data)


@callback
def _reload_when_the_installation_changes(
    hass: HomeAssistant, entry: SentioConfigEntry
) -> None:
    """Reload the entry when the controller gains or loses points - a room or peripheral set up
    or taken away - or a slot holds another peripheral, or its peripheral moves to another room.
    """
    data = entry.runtime_data
    client = data.client
    reloading = False

    @callback
    def reload() -> None:
        nonlocal reloading
        if not reloading:
            reloading = True
            _LOGGER.info("The installation of %s has changed; reloading it", entry.title)
            hass.config_entries.async_schedule_reload(entry.entry_id)

    @callback
    def points_changed(gained: frozenset[Key[Any]], lost: frozenset[Key[Any]]) -> None:
        reload()

    @callback
    def peripheral_changed(
        key: Key[Any], old: DataValue[Any] | None, new: DataValue[Any]
    ) -> None:
        if peripherals(client) != data.peripherals:
            reload()

    def watch[T](slot: int, point: PointKey[T]) -> None:
        # Only a change matters here, so nothing asks for the point to be polled.
        key = peripheral_key(slot, point)
        entry.async_on_unload(client.subscribe(key, peripheral_changed, poll=False))

    entry.async_on_unload(client.subscribe_points(points_changed))
    for peripheral in data.peripherals:
        watch(peripheral.slot, PeripheralPointKey.TYPE)
        watch(peripheral.slot, PeripheralPointKey.SERIAL_NUMBER)
        watch(peripheral.slot, PeripheralPointKey.OWNER)


async def _poll(client: Client) -> None:
    """Read whatever the client has due, for as long as the entry is loaded."""
    while True:
        try:
            await client.poll()
        except Exception:
            _LOGGER.exception("Reading the controller failed")
            delay = POLL_TICK
        else:
            delay = client.seconds_until_next_poll()
        await asyncio.sleep(POLL_TICK if delay is None else min(delay, POLL_TICK))
