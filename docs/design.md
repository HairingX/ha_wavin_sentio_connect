# Design

How the integration is built, and the facts each choice rests on. Home Assistant facts are from
its 2026.9.3 source, the release the tests run; the Sentio's from its Modbus manual, as modelled
by `wavin_sentio_connect`.

## A client, not a coordinator

The library's client plans every read itself: each point has a poll rate, only what is subscribed
to is read, and a poll with nothing due sends nothing. The integration therefore owns no update
interval. It runs one background task per config entry that calls `client.poll()` and sleeps
until the client has something due, at most `POLL_TICK`, as a new subscription or a write's
read-back can make a point due while it sleeps.

- The task is made with `ConfigEntry.async_create_background_task`, which Home Assistant cancels
  when the entry unloads (`config_entries.py`, `_async_process_on_unload`). That cancellation
  runs after `async_unload_entry` returns, so unloading cancels the task itself and awaits it
  before disconnecting: no read runs against a closing connection.
- A poll that raises is logged and the loop goes on; the client reports an unanswering
  controller through its status, not by raising.
- `DataUpdateCoordinator` is not used: it refreshes on its own interval, which would duplicate the
  client's plan.

## Setup and errors

| What happens at setup | Home Assistant is told | Effect |
|---|---|---|
| Nothing answers (`CannotConnectError`) | `ConfigEntryNotReady` | retried later |
| What answers is no Sentio (`UnsupportedDeviceError`) | `ConfigEntryError` | not retried |
| Another controller's serial number | `ConfigEntryError` | not retried; reconfigure it |

The config entry is keyed by the controller's serial number (`LocationPointKey.SERIAL_NUMBER`),
so its address can change without losing anything: the reconfigure step changes host, port and
unit ID, refusing a controller with another serial number (`_abort_if_unique_id_mismatch`), and
adding the same controller again moves the entry to the new address
(`_abort_if_unique_id_configured(updates=...)`).

## Devices

The controller is registered first; each room as a child device of it, and each peripheral
with `via_device_id` pointing to it. HA's device registry documentation: `via_device_id` is "the
device id of a device that routes messages between this device and Home Assistant", and "to model
the logical parts of a single product, use a child device instead". A room is a part of the
controller; a peripheral reaches Home Assistant through the controller, not through its room.
Where a peripheral belongs is its `owner`, shown as a Room sensor with the name HA shows for that
room, so that a move is in its history.

- `ChildDeviceInfo` and `async_get_or_create_child` are in HA 2026.9.3. A child device has no
  manufacturer, model or serial number, and cannot be a `via_device_id`
  (`DeviceInfoError`), so a peripheral cannot be placed under its room.
- `async_get_or_create_child` converts a device registered with the same identifiers into a
  child device, keeping its id - unless the same setup of the entry already registered it as a
  device (`DeviceInfoError`).
- `DeviceInfo` in 2026.9 has `via_device_id`, a device registry id; the older `via_device`
  identifier is reported as deprecated, to stop working in 2027.8.0. Entities name their device
  by its identifiers, and a room's entities also by the controller's device id.

- Identifiers carry the controller's serial number: `<serial>`, `<serial>_room_<n>`,
  `<serial>_peripheral_<peripheral serial>`. A peripheral is identified by its own serial number,
  as the controller renumbers its slots on a relearn; one that reports none gets no device.
- The controller is named by the `controller` device translation, *Wavin Sentio Controller*: it
  is the controller itself, which every device is part of or connected through. The entry is
  titled *Wavin Sentio*, followed by the controller's location name when it has one.
- A room never named on the controller is named by the `room` device translation.
- The controller's names only name a room or peripheral when its device is created; after that
  the name in HA is the truth, and a name on the controller is never shown again. A device is
  registered again at every setup, so the name is passed only when the device does not exist.
- A new peripheral is named after the room it belongs to, as HA shows that room, then its name on
  the controller (a CCU-208 holds the model there): `Bathroom 1 RT-250IR`. A name that already
  starts with the room's is kept, and one that belongs to the controller (`owner` 0) keeps its
  own.
- The Room diagnostic shows the name HA shows for the place, and follows it when it is renamed
  (`async_track_device_registry_updated_event`, which fires for child devices too).
- No suggested area: with a room's name as its suggested area, Home Assistant 2026.9.3 built
  entity IDs such as `sensor.kitchen_kitchen_air_temperature`.
- A device the installation no longer has is removed whenever the entry sets up
  (`async_remove_device`; in 2026.9 a device belongs to one config entry, and removing an entry
  from it with `async_update_device` is reported as deprecated, to stop working in 2027.8.0).
  One it still has cannot be deleted by the user (`async_remove_config_entry_device`).
- The entry reloads (`async_schedule_reload`) when the client reports points gained or lost
  (`subscribe_points`), or a peripheral's type, serial number or owner changes: what a device's
  identity and place are built from. Devices and entities are then built by the one path that
  builds them at setup.

## Entities

Each platform describes its entities once per point - for the location, every room or every
peripheral - and creates one wherever the installation has that point. The client's `points` are
exactly what this installation has: a dummy room has no measurements, a room not associated with
a function has no state for it, and a register the controller refuses is not there.

An entity subscribes to its keys and to the client's `CONNECTED` status, and sets its `_attr_`
values in `_show` on every change. It sets them in its constructor too: Home Assistant reads
capability attributes such as a thermostat's `hvac_modes` when it adds the entity, before
`async_added_to_hass` (`entity_platform.py`, `_async_add_entity`). Properties are not overridden:
Home Assistant declares them as `cached_property`, which pyright strict will not let a `property`
override.

| Quality of the value | The entity |
|---|---|
| `GOOD` | shows it |
| `NO_DATA` | is unknown |
| `STALE` | shows the last good value |
| `OFFLINE`, `MISSING`, or the controller does not answer | is unavailable |

States are enum sensors and selects, with the enum member's lower-case name as the state and a
translation for each. Units come from the library's points, mapped to Home Assistant's spelling;
every unit a Sentio point has is mapped (`UNITS`).

### The thermostat

- The target shown is `temp_air_target_active`, the one the controller regulates to. Setting it
  writes the room's setpoint, `temp_air_target`, which the manual says is not used in SCHEDULE,
  under vacation or standby, or a temporary override.
- `AUTO` is the room's SCHEDULE mode. Home Assistant defines `AUTO` as "set based on a schedule
  ... User is not able to adjust the temperature" (`climate/const.py`), so setting the
  temperature in `AUTO` is refused. `HEAT` or `COOL` is the MANUAL mode, as the location is
  heating or cooling.
- The action is heating, cooling or idle from the room's state; a blocked room is idle, and the
  manual's NONE ("not used in this room, or no load detected") shows no action.

## Writes

The client sends writes in order and folds a queued setting into a newer one, so every platform
has `PARALLEL_UPDATES = 0` and passes actions straight on. A write is refused before it is sent
while the controller's Modbus mode forbids it (disabled, read only, or write with password, which
this integration does not handle), and a value the point cannot take, or a write the controller
does not accept, is an error the user reads.

## Dependencies

- `manifest.json` pins the library with `==`, as the manifest documentation asks.
- Home Assistant installs requirements under its package constraints
  (`homeassistant/package_constraints.txt`), which pin `pymodbus`; the tests run that version.
- The brand icon ships in `brand/`, which Home Assistant serves for custom integrations since
  2026.3 and which HACS's validation accepts in place of an entry in the brands repository.
