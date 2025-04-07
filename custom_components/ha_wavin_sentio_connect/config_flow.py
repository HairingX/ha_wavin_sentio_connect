"""Config flow for Wavin Sentio Connect integration."""

from __future__ import annotations

import logging
from typing import Any, Dict, Mapping

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from wavin_sentio_connect import WavinSentioTCPConnect, ModbusTCPErrorCode

from .const import DOMAIN, CONF_DEVICE_ID, CONF_DEVICE_IP, CONF_DEVICE_PORT, CONF_UNIT_ID

_LOGGER = logging.getLogger(__name__)


class WavinSentioConnectConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow for Wavin Sentio Connect."""

    VERSION = 1
    _device:WavinSentioTCPConnect
    _device_id:str = ""
    _device_ip:str = ""
    _device_port:int
    _device_unit_id:int

    def __init__(self) -> None:
        """Initialize."""
        _LOGGER.info("Starting config flow")
        self._device = WavinSentioTCPConnect()
        self._device_id = "WavinSentio"
        self._device_port = self._device.DEFAULT_PORT
        self._device_unit_id = self._device.DEFAULT_UNIT_ID

    async def async_step_user(self, user_input: Dict[str, Any] | None = None) -> ConfigFlowResult:
        """Invoked when a user initiates a flow via the user interface."""
        return self.async_show_manual_form()

    def async_show_manual_form(self, connection_failed:bool=False, connection_timeout:bool=False, deviceid_already_in_use:bool=False, deviceid_invalid:bool=False, deviceip_invalid:bool=False) -> ConfigFlowResult:
        """Show the manual form."""
        data_schema:Dict[vol.Required|vol.Optional, type] = {
            vol.Required(CONF_DEVICE_ID, default=self._device_id): str,
            vol.Required(CONF_DEVICE_IP, default=self._device_ip): str,
            vol.Required(CONF_UNIT_ID, default=self._device_unit_id): int,
            vol.Required(CONF_DEVICE_PORT, default=self._device_port): int,
        }

        errors:Dict[str,str] = {}
        if connection_failed:
            errors["base"] = "cannot_connect"
        if connection_timeout:
            errors["base"] = "cannot_connect"
        if deviceid_already_in_use:
            errors["base"] = "deviceid_already_in_use"
        if deviceid_invalid:
            errors["base"] = "deviceid_invalid"
        if deviceip_invalid:
            errors["base"] = "deviceip_invalid"

        return self.async_show_form(step_id="manual", data_schema=vol.Schema(data_schema), errors=errors)

    async def async_step_manual(self, user_input:Dict[str, Any]) -> ConfigFlowResult:
        """After user has provided their ip, port and email. Try to connect and see if email is correct."""
        _LOGGER.info("Async step manual - user has picked {%s}", user_input)

        #Check if the device id is already in use. If so, show the manual form again.
        device_id = user_input.get(CONF_DEVICE_ID, self._device_id) or ""
        _device_ip = user_input.get(CONF_DEVICE_IP, self._device_ip) or ""
        if len(device_id.strip()) == 0: return self.async_show_manual_form(deviceid_invalid=True)
        if len(_device_ip.strip()) == 0: return self.async_show_manual_form(deviceip_invalid=True)
        config_entry = await self.async_set_unique_id(device_id)
        if config_entry: return self.async_show_manual_form(deviceid_already_in_use=True)

        connected = await self._async_connect_with_settings(user_input)
        device = self._device
        if not connected:
            if device.last_error is ModbusTCPErrorCode.TIMEOUT:
                return self.async_show_manual_form(connection_timeout=True)
            elif device.last_error is ModbusTCPErrorCode.UNSUPPORTED_MODEL:
                _LOGGER.error(f"Model could not be initialized for {device_id}. Software version: {device.device_info.version.software_major}.{device.device_info.version.software_minor}.{device.device_info.version.software_patch}, hardware version: {device.device_info.version.hardware_major}.{device.device_info.version.hardware_minor}.{device.device_info.version}, register version: {device.device_info.version.datapoint_major}.{device.device_info.version.datapoint_minor}.{device.device_info.version.datapoint_patch}")
                return self.async_abort(reason="unsupported_model")
            else:
                return self.async_show_manual_form(connection_failed=True)

        config_data:Mapping[str, Any] = {
            CONF_DEVICE_ID: self._device_id,
            CONF_UNIT_ID: self._device_unit_id,
            CONF_DEVICE_IP: self._device_ip,
            CONF_DEVICE_PORT: self._device_port,
        }
        return self.async_create_entry(title=self._device_id, data=config_data)

    async def _async_connect_with_settings(self, user_input:Dict[str, Any]) -> bool:

        self._device_id = user_input.get(CONF_DEVICE_ID, self._device_id) or ""
        self._device_ip = user_input.get(CONF_DEVICE_IP, self._device_ip)
        self._device_unit_id = int(user_input.get(CONF_DEVICE_IP, self._device_unit_id))
        self._device_port = int(user_input.get(CONF_DEVICE_PORT, self._device_port))

        self._device_id = self._device_id.strip()
        self._device_ip = self._device_ip.strip()

        _LOGGER.info("User provided id: %s, ip: %s, port: %s, unit id: %s", self._device_id, self._device_ip, self._device_port, self._device_unit_id)

        connected = await self._device.connect(device_id=self._device_id, host=self._device_ip, port=self._device_port, unit_id=self._device_unit_id)
        if not connected:
            _LOGGER.info("Failed to connected to device.")
        else:
            _LOGGER.info("Successfully connected to device.")
        return connected

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the reconfigure step."""

        ## Get the config entry data
        if "entry_id" not in self.context: return self.async_abort(reason="missing_entry_id")
        config_entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        if config_entry is None: return self.async_abort(reason="missing entry data")
        data = config_entry.data

        if user_input is not None:
            # user has input his values
            connected = await self._async_connect_with_settings(user_input)
            device_id = user_input.get(CONF_DEVICE_ID, self._device_id) or ""
            device = self._device
            if not connected:
                if device.last_error is ModbusTCPErrorCode.TIMEOUT:
                    return self.async_show_reconfigure_form(connection_timeout=True)
                elif device.last_error is ModbusTCPErrorCode.UNSUPPORTED_MODEL:
                    _LOGGER.error(f"Model could not be initialized for {device_id}. Software version: {device.device_info.version.software_major}.{device.device_info.version.software_minor}.{device.device_info.version.software_patch}, hardware version: {device.device_info.version.hardware_major}.{device.device_info.version.hardware_minor}.{device.device_info.version}, register version: {device.device_info.version.datapoint_major}.{device.device_info.version.datapoint_minor}.{device.device_info.version.datapoint_patch}")
                    return self.async_abort(reason="unsupported_model")
                else:
                    return self.async_show_reconfigure_form(connection_failed=True)
            else:
                # reconfigure successful
                _LOGGER.info("Successfully reconfigured device.")
                config_data:Mapping[str, Any] = {
                    CONF_DEVICE_ID: self._device_id,
                    CONF_UNIT_ID: self._device_unit_id,
                    CONF_DEVICE_IP: self._device_ip,
                    CONF_DEVICE_PORT: self._device_port,
                }
                return self.async_update_reload_and_abort( # type: ignore
                        entry=config_entry,
                        unique_id=config_entry.unique_id,
                        data=config_data,
                        reason="reconfigure_successful",
                    )

        # user has just initiated reconfigure

        self._device_id = data.get(CONF_DEVICE_ID, "").strip()
        self._device_ip = data.get(CONF_DEVICE_IP, "").strip()
        self._device_port = int(data.get(CONF_DEVICE_PORT, self._device_port))

        return self.async_show_reconfigure_form()

    def async_show_reconfigure_form(self, connection_failed:bool=False, connection_timeout:bool=False, deviceid_already_in_use:bool=False, deviceid_invalid:bool=False, deviceip_invalid:bool=False) -> ConfigFlowResult:
        """Show the reconfig form."""
        # process user input
        data_schema:Dict[vol.Required|vol.Optional, type] = {
            # vol.Required(CONF_DEVICE_ID, default=self._device_id): str, # deviceid may not be reconfigured
            vol.Required(CONF_DEVICE_IP, default=self._device_ip): str,
            vol.Required(CONF_UNIT_ID, default=self._device_unit_id): int,
            vol.Required(CONF_DEVICE_PORT, default=self._device_port): int,
        }

        errors:Dict[str,str] = {}
        if connection_failed:
            errors["base"] = "cannot_connect"
        if connection_timeout:
            errors["base"] = "cannot_connect"
        if deviceid_already_in_use:
            errors["base"] = "deviceid_already_in_use"
        if deviceid_invalid:
            errors["base"] = "deviceid_invalid"
        if deviceip_invalid:
            errors["base"] = "deviceip_invalid"

        return self.async_show_form(step_id="reconfigure", data_schema=vol.Schema(data_schema), errors=errors)