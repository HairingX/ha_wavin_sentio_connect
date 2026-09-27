# Wavin Sentio Connect for Home Assistant

A Home Assistant integration for **Wavin Sentio** (the CCU-208 control unit), over
Modbus TCP on your own network - no cloud. Built on
[wavin_sentio_connect](https://github.com/HairingX/wavin_sentio_connect).

Every room becomes a thermostat and a part of the controller with its measurements, states and
settings; every paired thermostat, display and module becomes a device of its own, which shows
the room it belongs to.

## What it is for

- See every room's temperature, humidity and whether it is heating, in one place, with history.
- Change a room's temperature, or switch it between its schedule and manual control.
- Put the whole house in vacation or standby from an automation, a scene or your phone.
- Be told when a thermostat's battery runs low, a thermostat stops answering, or the controller
  reports a problem.

## Supported devices

- **Wavin Sentio CCU-208**, the controller. The integration uses the CCU-208 register map of the
  Sentio Modbus manual (address space 3.2 and newer) and has been run against a CCU-208 with
  address space 3.7.
- Through it, every peripheral paired with it: thermostats (RT-201, RT-250, RT-250IR), room
  sensors (RS-211, RS-251), displays (LCD-200), extension modules (EU-208-A, EU-206-VFR), outdoor
  sensors (ET-250, ET-210) and radiator thermostats (VH-250), as the controller reports them.
- The controller's other objects, where it has them: the outdoor zone, heating/cooling circuits,
  the heating/cooling source, the boiler or heat pump and the thermistor inputs have been run
  against a CCU-208. **The hot water tank, inlet temperature controllers, buffer tank,
  ventilation units and dehumidifiers are built from the manual alone and have not been run
  against a controller that has them.**
- Not supported: the DHW-201 (Calefa) hot water controller, which the manual lists as another
  device type.

## Requirements

- Home Assistant 2026.9.3 or newer.
- Modbus TCP enabled on the controller. It is **disabled by default**; enable it from a Sentio
  display: `System | Installer settings | Modbus configuration | Modbus TCP`. The controller
  restarts afterwards.
- For changing anything from Home Assistant, the controller's Modbus mode must be *read and
  write*. In *read only* it can be monitored; *write with password* is not supported.

## Installation

### With HACS

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=HairingX&repository=ha_wavin_sentio_connect&category=integration)

1. Select the button to open this repository in [HACS](https://hacs.xyz). Or add it yourself: in
   HACS, the three dots > **Custom repositories**, the repository
   `https://github.com/HairingX/ha_wavin_sentio_connect` and the type **Integration**.
2. Download **Wavin Sentio Connect**.
3. Restart Home Assistant.

HACS offers the releases; a pre-release only with **Show beta versions** switched on for the
repository.

### Manually

1. Download the source code of the
   [latest release](https://github.com/HairingX/ha_wavin_sentio_connect/releases/latest).
2. Copy its `custom_components/wavin_sentio_connect` folder into the `custom_components` folder
   of your Home Assistant configuration.
3. Restart Home Assistant.

## Setup

**Discovered:** a controller that gets its address over DHCP sends the host name
`Wavin Sentio CCU#` followed by the last four digits of its serial number. Home Assistant's DHCP
discovery sees it when the controller asks for an address, and offers it under Settings >
Devices & services > Discovered; confirm it there. It is looked for on port `502` with unit ID
`1`. A controller already added that turns up at a new address is moved there by itself.

**By its address:**

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=wavin_sentio_connect)

Select the button, or go to Settings > Devices & services > Add integration >
**Wavin Sentio Connect**.

| Field | |
|---|---|
| Host | The controller's IP address or host name. |
| Port | The Modbus TCP port; `502` unless you changed it. |
| Unit ID | The Modbus unit ID; `1` unless you changed it. |

The controller is recognised by its **serial number**, not its address. So when it gets a new
address:

- **Reconfigure** the entry (Settings > Devices & services > Wavin Sentio Connect > the three
  dots > Reconfigure) and enter the new address. Every device, entity and its history stays.
- Or add it again at the new address: the existing entry moves there.

Reconfigure refuses an address where another controller answers.

## What you get

**The controller** - the device *Wavin Sentio Controller*, with its software and hardware version
and serial number. The entry it is set up as is called *Wavin Sentio*, followed by the
controller's location name when it has one:

- Standby and vacation switches.
- The heating/cooling mode, the system's warning and error.
- Diagnostic and configuration entities, some disabled by default: the Modbus mode, daylight
  saving time, the update mode, the heating/cooling override, the outdoor temperature limits.

**Each room** - a part of the controller's device, named as on the controller:

- A **thermostat**: the air temperature and humidity, the target the controller regulates to,
  and whether it is heating or cooling. *Heat* (or *Cool*) is the room's manual mode with its
  own setpoint; *Auto* is its schedule, in which the temperature cannot be set here. Eco,
  Comfort and Extra comfort presets, where the controller offers them.
- Everything the thermostat shows is also an entity of its own, with its own history and a plain
  action for scripts: sensors for the air temperature, the humidity and the **target
  temperature** the controller regulates to now; the **setpoint**, the room's own temperature,
  which can be set even while the room follows its schedule and is used once it no longer does;
  the **mode** (schedule or manual) and the **preset**, where the controller offers presets.
- Sensors for floor temperature and dew point, the room's state and what blocks it.
- The thermostat lock, and the standby and vacation temperatures.
- Warning, error, low battery and peripheral-lost alarms.
- Disabled by default: the state and blocking source of each function - radiators, underfloor
  heating, drying, thermal integration and ventilation - and the installer's thresholds and
  hysteresis settings.

Only what the controller reports is created: a room with no thermostat or sensor (a *dummy*
room) has no measurements, and a room not using radiators, underfloor heating or another
function has no entities for it. An entity for something the controller no longer reports - a
measurement of a room made a dummy - is removed.

**Each thermostat, display and module** - a device with its model and serial number, reached
through the controller and named after its room, such as *Bathroom 1 RT-250IR*: its signal
strength and its alarms, and, as a diagnostic with its history, the room it belongs to (or the
controller itself).

**The controller's other objects** - each one the controller has, named as on the controller or
else by its kind:

- Parts of the controller's device: the **outdoor** zone (air temperature), each
  **heating/cooling circuit** and **inlet temperature controller** (inlet and return
  temperatures, state, pump), the **heating/cooling source**, the **boiler / heat pump**, the
  **buffer tank**, the **hot water tank** (temperature, state and circulation; its mode,
  setpoint, and vacation and standby temperatures) and the **thermistor inputs**.
- Devices of their own, reached through the controller, with the model they report: each
  **ventilation unit** (state, fan speeds, air temperatures) and **dehumidifier** (drying and
  thermal integration state).
- Each object's alarms.
- Disabled by default: the heat curves and the installer's settings, the thermistor inputs, and
  codes and values mostly of use when setting up.

## How data is updated

Home Assistant does not poll the entities. The integration reads the controller over Modbus and
updates an entity when its value changes:

- Each value is read on its own schedule: a room's state and what blocks it most often, then
  temperatures and humidity, then settings, and signal strength least often. Versions, names and
  room types are read once, when the integration starts.
- Only what an enabled entity shows is read. Enabling an entity starts reading its value.
- The system's warning and error, and the Modbus mode, are always read. When the warning or the
  error changes, every alarm an enabled entity shows is read at once.
- A change made in Home Assistant is read back from the controller, so the entity shows what the
  controller holds. Changing vacation, standby or a room's mode, setpoint or preset also reads
  the rooms' targets again.
- With **Enable polling for changes** turned off (the entry's three dots > System options),
  nothing is read on a schedule. `homeassistant.update_entity` reads an entity at once, polling
  on or off, and a change made in Home Assistant is still read back from the controller. A room
  or peripheral taken away is found when its values are read; a new one when the integration is
  reloaded.
- The rooms and peripherals are found when the integration starts, and checked again while it
  reads. When a room is set up or taken away, or a thermostat is paired, replaced, removed or
  moved to another room, the integration reloads itself: new devices and entities appear, and
  devices the installation no longer has are removed.

What an entity shows:

- A value the controller reports as "no reading" - a missing sensor, an unset limit - shows as
  *unknown*.
- While the controller does not answer, every entity is *unavailable*.
- A read that fails while the controller still answers keeps the last value.

## Examples

Put the house in vacation mode when everyone has left:

```yaml
automation:
  - alias: "Heating: vacation while away"
    triggers:
      - trigger: state
        entity_id: zone.home
        to: "0"
        for: "24:00:00"
    actions:
      - action: switch.turn_on
        target:
          entity_id: switch.home_vacation   # your controller's Vacation switch
```

Be told when a thermostat's battery runs low:

```yaml
automation:
  - alias: "Heating: low battery"
    triggers:
      - trigger: state
        entity_id: binary_sensor.kitchen_battery   # a room's Battery sensor
        to: "on"
    actions:
      - action: notify.notify
        data:
          message: "A thermostat in the kitchen has a low battery."
```

## Troubleshooting

- **"Nothing answered at this address, port and unit ID."** Check that Modbus TCP is enabled on
  the controller (see Requirements), and that the address is the controller's current one. The
  port is `502` and the unit ID `1` by default; the manual gives `255` as the unit ID for Modbus
  TCP "if needed".
- **The controller got a new address.** Reconfigure the entry (see Setup).
- **The controller is not discovered.** Home Assistant sees a DHCP host name only when the
  controller asks for an address, as when it starts, and only if Home Assistant receives the
  network's DHCP traffic. What its DHCP discovery has seen since Home Assistant started - address,
  host name and hardware address - is listed at `/config/dhcp` on your Home Assistant; the
  controller's address should be there with its `wavin sentio ccu#` host name. For more, log
  `homeassistant.components.dhcp` and `custom_components.wavin_sentio_connect` at debug level
  (Developer tools > Actions > `logger.set_level`): each DHCP packet shows as
  `Processing updated address data`, a match with this integration as `Matched ...
  wavin_sentio_connect`, and a controller the integration then does not add as `Not adding the
  controller announced at ...`.
- **"The controller's Modbus mode is READ_ONLY"** when changing something: set the Modbus mode to
  read and write on the controller's display.
- **A room has no temperature entities.** The controller reports it as a room with no thermostat
  or sensor.
- **A display's or module's signal strength is unknown.** The controller reports no signal
  strength for a wired peripheral.
- Anything else: download the diagnostics and a debug log (below) and open an issue.

## Diagnostics and debug logging

- **Download diagnostics** from the integration's menu: every value the controller reports, with
  its quality, and what it does not have. The address, serial number and location name are left
  out.
- **Enable debug logging** from the same menu to log the integration and the libraries it uses.

## Known limits

- The hot water tank, inlet temperature controllers, buffer tank, ventilation units and
  dehumidifiers are built from the manual alone: no controller that has them has been read. If
  you have one, please report what it shows.
- Not shown: when a ventilation unit's or dehumidifier's air filter was last changed (the manual
  does not give how the time is encoded), and a ventilation unit's feature bits.
- The Modbus register map has no floor temperature setpoint.
- The controller's names for its rooms and peripherals only name a device when it is first
  added; after that, the name in Home Assistant is the one used, and renaming on the controller
  changes nothing. A thermostat moved to another room keeps its name; its Room diagnostic shows
  where it is now.
- Discovery finds a controller only on port `502` with unit ID `1`, and only where Home
  Assistant sees the network's DHCP traffic.

## Removing the integration

Settings > Devices & services > Wavin Sentio Connect > the three dots > Delete. Uninstall it in
HACS, or delete `custom_components/wavin_sentio_connect`, and restart Home Assistant.

A thermostat or module that is no longer paired, and a room taken away, are removed by
themselves.

## Disclaimer

Provided "as is", without warranty of any kind. This project is not affiliated with or endorsed
by Wavin.
