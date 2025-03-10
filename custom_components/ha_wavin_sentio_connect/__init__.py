"""The Nilan Connect integration."""

from __future__ import annotations
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady, ConfigEntryAuthFailed

from custom_components.ha_wavin_sentio_connect.data import WavinSentioConnectHassData, get_hass_data, remove_hass_data, set_hass_data # type: ignore
from .const import DOMAIN, CONF_DEVICE_ID, CONF_DEVICE_IP, CONF_DEVICE_PORT
from wavin_sentio_connect import WavinSentioConnect, ModbusTCPErrorCode, ModbusExceptCode

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.CLIMATE,
    Platform.SWITCH,
    Platform.NUMBER,
    Platform.BUTTON,
    Platform.SELECT,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Nilan Connect from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    device = WavinSentioConnect()
    device_id = str(entry.data.get(CONF_DEVICE_ID))
    device_ip = str(entry.data.get(CONF_DEVICE_IP))
    device_port = int(entry.data.get(CONF_DEVICE_PORT, 0))
    is_connected = await device.connect(device_id, device_ip, device_port)
    if not is_connected:
        raise ConfigEntryNotReady(f"Timed out while trying to connect to {device.device_id} as {device.host}:{device.port}")

    _LOGGER.info(f"Controller model: {device.model_name}")
    if device.last_error != ModbusTCPErrorCode.NONE:
        if device.last_error is ModbusTCPErrorCode.TIMEOUT:
            raise ConfigEntryNotReady(f"Timed out while trying to connect to {device_id}")
        if device.last_error is ModbusTCPErrorCode.UNSUPPORTED_MODEL:
            raise ConfigEntryNotReady(
                f"Timed out while trying to get data from {device_id} did not correctly load a model for Model no: {device.model_name}, software version: {device.device_info.version.software_major}.{device.device_info.version.software_minor}.{device.device_info.version.software_patch}, hardware version: {device.device_info.version.hardware_major}.{device.device_info.version.hardware_minor}.{device.device_info.version}, register version: {device.device_info.version.datapoint_major}.{device.device_info.version.datapoint_minor}.{device.device_info.version.datapoint_patch}"
            )

    # dataResult = await device.request_datapoint_read()
    # if dataResult is False:  # Waits for NilanProxy to get fresh data
    #     if device.get_loaded_model_name() is None:
    #         raise ConfigEntryNotReady(
    #             f"Timed out while trying to get data from {device_id} did not correctly load a model for Model no: {device.get_device_model()}, device number: {device.get_device_number()} and slavedevice number: {device.get_slave_device_number()}"
    #         )
    #     _LOGGER.error(f"Could not get data from {device_id} has loaded model for {device.get_loaded_model_name()}")
    #     raise ConfigEntryNotReady(
    #         f"Timed out while trying to get data from {device_id} has loaded model for {device.get_loaded_model_name()}"
    #     )

    data = WavinSentioConnectHassData(device=device)
    set_hass_data(hass, entry, data)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await device.request_datapoint_read()
    await device.request_setpoint_read()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    data = get_hass_data(hass, entry)
    data["proxy"].stop_listening()
    remove_hass_data(hass, entry)
    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)