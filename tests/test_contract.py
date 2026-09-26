"""The integration against what it is built on: every library point, unit and state, the
translations, the manifest and the Home Assistant it is tested with."""

from __future__ import annotations

import ast
import fnmatch
import importlib.metadata
import json
import re
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, cast

import homeassistant
import pytest
import yaml
from homeassistant.const import __version__ as HA_VERSION
from wavin_sentio_connect import (
    UNITS,
    LocationPointKey,
    PeripheralPointKey,
    RoomPointKey,
)

from custom_components.wavin_sentio_connect.binary_sensor import BINARY_SENSORS
from custom_components.wavin_sentio_connect.climate import PRESETS
from custom_components.wavin_sentio_connect.entity import (
    Scope,
    SentioEntityDescription,
    point_name,
)
from custom_components.wavin_sentio_connect.number import NUMBERS
from custom_components.wavin_sentio_connect.select import SELECTS
from custom_components.wavin_sentio_connect.sensor import SENSORS
from custom_components.wavin_sentio_connect.switch import SWITCHES
from custom_components.wavin_sentio_connect.units import HA_UNITS

INTEGRATION = Path(__file__).parents[1] / "custom_components" / "wavin_sentio_connect"
REPOSITORY = INTEGRATION.parents[1]

PLATFORMS: dict[str, tuple[SentioEntityDescription, ...]] = {
    "binary_sensor": BINARY_SENSORS,
    "number": NUMBERS,
    "select": SELECTS,
    "sensor": SENSORS,
    "switch": SWITCHES,
}

NOT_AN_ENTITY: dict[Scope, dict[str, str]] = {
    Scope.LOCATION: {
        "datapoint_major": "the address space version, which the scan checks",
        "datapoint_minor": "the address space version, which the scan checks",
        "setpoint_major": "the address space version, again among the holding registers",
        "setpoint_minor": "the address space version, again among the holding registers",
        "device_type": "the controller device's model",
        "hardware_major": "the controller device's hardware version",
        "software_major": "the controller device's software version",
        "software_minor": "the controller device's software version",
        "serial_number": "the controller device's serial number and the entry's unique id",
        "serial_number_prefix": "the manual gives it as 1530",
        "location_name": "the controller device's name and the entry's title",
        "modbus_password": "write-only; this integration does not write passwords",
        "datetime_unix": "the manual: local time including daylight saving, not a Unix time",
        "timezone": "a number into the manual's timezone table",
    },
    Scope.ROOM: {
        "type": "decides whether the room has measurements",
        "name": "the room device's name",
        "associated_radiators": "decides whether the room has that function's entities",
        "associated_ufhc": "decides whether the room has that function's entities",
        "associated_drying": "decides whether the room has that function's entities",
        "associated_thermal_integration": "decides whether the room has that function's "
        "entities",
        "associated_ventilation": "decides whether the room has that function's entities",
        "associated_heating_source": "the address of another Modbus object",
        "drying_state": "the manual gives it other states than RoomState, which the "
        "library reads it as",
        "ventilation_state": "the manual gives it other states than RoomState, which the "
        "library reads it as",
    },
    Scope.PERIPHERAL: {
        "type": "the peripheral device's model",
        "serial_number": "the peripheral device's identity",
        "name": "the peripheral device's name",
    },
}


def _library_points() -> dict[Scope, set[str]]:
    return {
        Scope.LOCATION: {str(key) for key in LocationPointKey.all()},
        Scope.ROOM: {point.name for point in RoomPointKey.all()},
        Scope.PERIPHERAL: {point.name for point in PeripheralPointKey.all()},
    }


def _described() -> dict[Scope, set[str]]:
    found: dict[Scope, set[str]] = {scope: set() for scope in Scope}
    for descriptions in PLATFORMS.values():
        for description in descriptions:
            found[description.scope].add(point_name(description.point))
    return found


@pytest.mark.parametrize("scope", list(Scope))
def test_every_library_point_is_an_entity_or_has_a_reason_not_to_be(scope: Scope) -> None:
    library = _library_points()[scope]
    described = _described()[scope]
    excluded = set(NOT_AN_ENTITY[scope])
    assert library - described - excluded == set(), "points no entity handles"
    assert (described | excluded) - library == set(), "points the library does not have"
    assert described & excluded == set()


def test_every_unit_of_the_library_has_its_home_assistant_unit() -> None:
    assert UNITS <= set(HA_UNITS)


def _translations(language: str) -> dict[str, Any]:
    path = INTEGRATION / "translations" / f"{language}.json"
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def _paths(tree: Mapping[str, Any], prefix: str = "") -> Iterator[str]:
    """Every leaf of a JSON tree, as its dotted path."""
    for key, value in tree.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            yield from _paths(cast(dict[str, Any], value), path)
        else:
            yield path


def test_danish_translates_exactly_what_english_does() -> None:
    assert set(_paths(_translations("da"))) == set(_paths(_translations("en")))


@pytest.mark.parametrize("platform", list(PLATFORMS))
def test_every_entity_and_state_has_a_name(platform: str) -> None:
    names = _translations("en")["entity"][platform]
    for description in PLATFORMS[platform]:
        key = description.translation_key
        assert key is not None and key in names, key
        options: list[str] | None = getattr(description, "options", None)
        if options is not None:
            assert set(names[key]["state"]) == set(options), key


def test_every_preset_has_a_name() -> None:
    names = _translations("en")["entity"]["climate"]["room"]["state_attributes"]
    assert set(names["preset_mode"]["state"]) == set(PRESETS.values())


def test_every_icon_belongs_to_a_translated_entity() -> None:
    icons = json.loads((INTEGRATION / "icons.json").read_text(encoding="utf-8"))
    names = _translations("en")["entity"]
    for platform, entities in icons["entity"].items():
        for key, icon in entities.items():
            assert key in names[platform], f"{platform}.{key}"
            for state in icon.get("state", {}):
                if platform in ("sensor", "select"):
                    assert state in names[platform][key]["state"], f"{key}.{state}"


def _manifest() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(
        (INTEGRATION / "manifest.json").read_text(encoding="utf-8")
    )
    return loaded


def test_the_manifest_pins_the_library_version_the_tests_run() -> None:
    installed = importlib.metadata.version("wavin_sentio_connect")
    assert _manifest()["requirements"] == [f"wavin_sentio_connect=={installed}"]


def test_the_tests_run_the_pymodbus_home_assistant_installs() -> None:
    """Home Assistant installs requirements under its package constraints, pymodbus among them."""
    constraints = Path(homeassistant.__file__).parent / "package_constraints.txt"
    pins = [
        line
        for line in constraints.read_text(encoding="utf-8").splitlines()
        if line.startswith("pymodbus==")
    ]
    assert pins == [f"pymodbus=={importlib.metadata.version('pymodbus')}"]


def test_hacs_requires_the_home_assistant_the_tests_run() -> None:
    hacs = json.loads((REPOSITORY / "hacs.json").read_text(encoding="utf-8"))
    assert hacs["homeassistant"] == HA_VERSION


def test_the_library_is_imported_from_its_package_not_from_the_integration() -> None:
    import wavin_sentio_connect

    assert INTEGRATION not in Path(wavin_sentio_connect.__file__).parents


QUALITY_SCALE_RULES = frozenset({
    # Bronze
    "action-setup", "appropriate-polling", "brands", "common-modules",
    "config-flow-test-coverage", "config-flow", "dependency-transparency", "docs-actions",
    "docs-conditions", "docs-high-level-description", "docs-installation-instructions",
    "docs-removal-instructions", "docs-triggers", "entity-event-setup", "entity-unique-id",
    "has-entity-name", "runtime-data", "test-before-configure", "test-before-setup",
    "unique-config-entry",
    # Silver
    "action-exceptions", "config-entry-unloading", "docs-configuration-parameters",
    "docs-installation-parameters", "entity-unavailable", "integration-owner",
    "log-when-unavailable", "parallel-updates", "reauthentication-flow", "test-coverage",
    # Gold
    "devices", "diagnostics", "discovery-update-info", "discovery", "docs-data-update",
    "docs-examples", "docs-known-limitations", "docs-supported-devices",
    "docs-supported-functions", "docs-troubleshooting", "docs-use-cases", "dynamic-devices",
    "entity-category", "entity-device-class", "entity-disabled-by-default",
    "entity-translations", "exception-translations", "icon-translations",
    "reconfiguration-flow", "repair-issues", "stale-devices",
    # Platinum
    "async-dependency", "inject-websession", "strict-typing",
})
"""The rules of Home Assistant's Integration Quality Scale, as its developer documentation lists
them. hassfest does not check this file for a custom integration, so this test does."""


def test_the_quality_scale_states_every_rule_and_explains_every_exemption() -> None:
    text = (INTEGRATION / "quality_scale.yaml").read_text(encoding="utf-8")
    rules = cast(dict[str, Any], yaml.safe_load(text)["rules"])
    assert set(rules) == QUALITY_SCALE_RULES
    for rule, state in rules.items():
        if state == "done":
            continue
        assert isinstance(state, dict), rule
        entry = cast(dict[str, Any], state)
        assert entry["status"] in ("done", "exempt", "todo"), rule
        if entry["status"] != "done":
            assert entry.get("comment"), f"{rule} is {entry['status']} without a reason"


@pytest.mark.parametrize("hostname", ["Wavin Sentio CCU#1234", "Wavin Sentio CCU#0007"])
def test_the_manifest_matches_the_host_name_the_manual_gives(hostname: str) -> None:
    """The manual: "Wavin Sentio CCU#[last four S/N digits]". Home Assistant lower-cases the
    host name and matches it with fnmatch."""
    patterns = [matcher["hostname"] for matcher in _manifest()["dhcp"]]
    assert any(re.match(fnmatch.translate(p), hostname.lower()) for p in patterns)


def test_the_manifest_does_not_match_another_host_name() -> None:
    patterns = [matcher["hostname"] for matcher in _manifest()["dhcp"]]
    assert not any(re.match(fnmatch.translate(p), "wavin-hub") for p in patterns)


THERMOSTAT_SHOWS: tuple[tuple[Scope, str], ...] = (
    (Scope.ROOM, "temp_air_current"),
    (Scope.ROOM, "humidity_current"),
    (Scope.ROOM, "temp_air_target_active"),
    (Scope.ROOM, "temp_air_target"),
    (Scope.ROOM, "mode"),
    (Scope.ROOM, "state"),
    (Scope.ROOM, "temp_preset"),
    (Scope.LOCATION, "heating_cooling_mode"),
)
"""Every point the thermostat shows or writes."""


@pytest.mark.parametrize(("scope", "point"), THERMOSTAT_SHOWS)
def test_everything_the_thermostat_shows_is_also_an_entity_of_its_own(
    scope: Scope, point: str
) -> None:
    """Each has a history of its own, and a plain action for scripts."""
    assert point in _described()[scope]


def test_nothing_imports_modbus_event_connect_itself() -> None:
    """wavin_sentio_connect gives the integration and its tests everything they use."""
    found: list[str] = []
    for path in [*INTEGRATION.rglob("*.py"), *Path(__file__).parent.rglob("*.py")]:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            modules = (
                [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else []
            )
            found += [f"{path.name}: {m}" for m in modules if m.startswith("modbus_event_connect")]
    assert found == []
