"""Set up a Sentio controller, and change where it is reached."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo

from wavin_sentio_connect import (
    DEFAULT_PORT,
    DEFAULT_UNIT_ID,
    CannotConnectError,
    UnsupportedDeviceError,
)

from .const import CONF_UNIT_ID, DOMAIN
from .data import entry_title, new_client, serial_number

_LOGGER = logging.getLogger(__name__)

SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): vol.All(
            int, vol.Range(min=1, max=65535)
        ),
        # A Modbus TCP unit identifier is one byte.
        vol.Required(CONF_UNIT_ID, default=DEFAULT_UNIT_ID): vol.All(
            int, vol.Range(min=0, max=255)
        ),
    }
)


class NoSerialNumberError(Exception):
    """The controller answered without a serial number, so it cannot be told apart."""


@dataclass(frozen=True)
class Controller:
    """What the flow learns from the controller."""

    serial_number: str
    title: str


async def identify(settings: Mapping[str, Any]) -> Controller:
    """Connect to the controller once, and read its serial number and name.

    Raises:
        CannotConnectError: nothing answered at that address.
        UnsupportedDeviceError: what answered is not a Sentio.
        NoSerialNumberError: the controller gave no serial number.
    """
    client = new_client(settings[CONF_HOST], settings[CONF_PORT], settings[CONF_UNIT_ID])
    await client.connect()
    try:
        found = serial_number(client)
        title = entry_title(client)
    finally:
        await client.disconnect()
    if found is None:
        raise NoSerialNumberError
    return Controller(found, title)


class WavinSentioConnectConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up a controller by its address; it is recognised by its serial number."""

    VERSION = 1
    MINOR_VERSION = 1

    _discovered: dict[str, Any]
    _discovered_title: str

    async def async_step_dhcp(
        self, discovery_info: DhcpServiceInfo
    ) -> ConfigFlowResult:
        """A controller announced its host name on the network; offer to add it.

        It is looked for at the manual's port and unit ID. A configured controller found at a
        new address has its entry moved there.
        """
        settings = {
            CONF_HOST: discovery_info.ip,
            CONF_PORT: DEFAULT_PORT,
            CONF_UNIT_ID: DEFAULT_UNIT_ID,
        }
        # Every address change is announced; one already configured needs no connection.
        self._async_abort_entries_match({CONF_HOST: discovery_info.ip})
        errors: dict[str, str] = {}
        controller = await self._identify(settings, errors)
        if controller is None:
            _LOGGER.debug(
                "Not adding the controller announced at %s: %s",
                discovery_info.ip,
                errors["base"],
            )
            return self.async_abort(reason=errors["base"])
        await self.async_set_unique_id(controller.serial_number)
        self._abort_if_unique_id_configured(updates={CONF_HOST: discovery_info.ip})
        self._discovered = settings
        self._discovered_title = controller.title
        self.context["title_placeholders"] = {"name": controller.title}
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask before adding a discovered controller."""
        if user_input is not None:
            return self.async_create_entry(
                title=self._discovered_title, data=self._discovered
            )
        self._set_confirm_only()
        return self.async_show_form(
            step_id="discovery_confirm",
            description_placeholders={
                "name": self._discovered_title,
                "host": self._discovered[CONF_HOST],
            },
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask where the controller is, and add it."""
        errors: dict[str, str] = {}
        if user_input is not None:
            settings = _settings(user_input)
            controller = await self._identify(settings, errors)
            if controller is not None:
                await self.async_set_unique_id(controller.serial_number)
                # The same controller at a new address: move the entry there.
                self._abort_if_unique_id_configured(updates=settings)
                return self.async_create_entry(title=controller.title, data=settings)
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the address, port or unit id of a configured controller."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            settings = _settings(user_input)
            controller = await self._identify(settings, errors)
            if controller is not None:
                await self.async_set_unique_id(controller.serial_number)
                self._abort_if_unique_id_mismatch(reason="wrong_device")
                return self.async_update_reload_and_abort(entry, data_updates=settings)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                SCHEMA, user_input if user_input is not None else entry.data
            ),
            errors=errors,
        )

    async def _identify(
        self, settings: Mapping[str, Any], errors: dict[str, str]
    ) -> Controller | None:
        """The controller at `settings`, or None with the reason put in `errors`."""
        if not settings[CONF_HOST]:
            errors[CONF_HOST] = "invalid_host"
            return None
        try:
            return await identify(settings)
        except CannotConnectError:
            errors["base"] = "cannot_connect"
        except UnsupportedDeviceError:
            errors["base"] = "unsupported_device"
        except NoSerialNumberError:
            errors["base"] = "no_serial_number"
        except Exception:
            _LOGGER.exception("Unexpected error while connecting to the controller")
            errors["base"] = "unknown"
        return None


def _settings(user_input: Mapping[str, Any]) -> dict[str, Any]:
    return {
        CONF_HOST: str(user_input[CONF_HOST]).strip(),
        CONF_PORT: int(user_input[CONF_PORT]),
        CONF_UNIT_ID: int(user_input[CONF_UNIT_ID]),
    }
