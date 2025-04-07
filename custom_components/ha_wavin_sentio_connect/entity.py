"""WavinSentioConnect base entity class"""

import logging
from typing import TypeVar, Generic

from wavin_sentio_connect import WavinSentioTCPConnect, UOM, WavinSentioDatapointKey, WavinSentioSetpointKey, ModbusPointKey, MODBUS_VALUE_TYPES # type: ignore

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.const import (
        UnitOfTime,
        UnitOfTemperature,
        PERCENTAGE,
        CONCENTRATION_PARTS_PER_MILLION,
        REVOLUTIONS_PER_MINUTE,
        CONTENT_TYPE_TEXT_PLAIN,
    )

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

VALUE_KEY_TYPE = TypeVar("VALUE_KEY_TYPE", WavinSentioDatapointKey, WavinSentioSetpointKey, None)
T = TypeVar("T")

class WavinSentioConnectEntityBase(Generic[VALUE_KEY_TYPE], Entity):
    """Base for all entities"""

    _attr_has_entity_name = True
    _unit_of_measurement:str|None
    _value_key:  VALUE_KEY_TYPE
    device: WavinSentioTCPConnect

    def __init__(
        self,
        device: WavinSentioTCPConnect,
        name: str,
        value_key: VALUE_KEY_TYPE,
        use_default_update_handler: bool = True,
        default_enabled:bool|None = None,
        default_visible:bool|None = None
    ) -> None:
        if default_enabled is not None: self._attr_entity_registry_enabled_default = default_enabled
        if default_visible is not None: self._attr_entity_registry_visible_default = default_visible
        self.device = device
        self._attr_translation_key = name
        self._attr_unique_id = f"{device.device_id}_{self._attr_translation_key.split("__")[0]}"
        self._attr_should_poll = False #set to False, we push changes to HA.
        self._value_key = value_key
        self._unit_of_measurement = UOM.UNKNOWN
        self._use_default_update_handler = use_default_update_handler
        if value_key is not None:
            self._unit_of_measurement = device.get_unit_of_measure(value_key)
            self.set_unit_of_measurement(self._unit_of_measurement)

    async def async_added_to_hass(self) -> None:
        if self._use_default_update_handler and self._value_key is not None:
            self.device.subscribe(self._value_key, self._on_change)

    async def async_will_remove_from_hass(self) -> None:
        if self._use_default_update_handler and self._value_key is not None:
            self.device.unsubscribe(self._value_key, self._on_change)

    def set_unit_of_measurement(self, uom:str|None):
        # self._attr_unit_of_measurement = self.parseUnitOfMeasure(uom)
        return

    def parse_unit_of_measure(self, uom:str|None, default:T = None) -> str|T:
        match uom:
            case UOM.SECONDS:     return UnitOfTime.SECONDS
            case UOM.MINUTES:     return UnitOfTime.MINUTES
            case UOM.HOURS:     return UnitOfTime.HOURS
            case UOM.DAYS:     return UnitOfTime.DAYS
            case UOM.MONTHS:   return UnitOfTime.MONTHS
            case UOM.YEARS:    return UnitOfTime.YEARS
            case UOM.CELSIUS:  return UnitOfTemperature.CELSIUS
            case UOM.PCT:      return PERCENTAGE
            case UOM.PPM:      return CONCENTRATION_PARTS_PER_MILLION
            case UOM.RPM:      return REVOLUTIONS_PER_MINUTE
            case UOM.TEXT:     return CONTENT_TYPE_TEXT_PLAIN
            case _:
                return default

    def _on_change(self, key:ModbusPointKey, old_value:MODBUS_VALUE_TYPES|None, new_value:MODBUS_VALUE_TYPES|None):
        """Notify HA of changes"""
        if self.hass is None: return # type: ignore
        _LOGGER.debug(f"Value Update: {self._attr_translation_key}: {old_value} -> {new_value}")
        self.schedule_update_ha_state(force_refresh=True)

    @property
    def device_info(self) -> DeviceInfo: # type: ignore
        info: DeviceInfo = {
            "identifiers": {(DOMAIN, self.device.device_id)},
            "name": self.device.device_id,
            "manufacturer": self.device.manufacturer,
            "model": self.device.model_name,
            "hw_version": f"M: {self.device.device_info.model_name}, {self.device.device_info.version.hardware_major}.{self.device.device_info.version.hardware_major}",
            "sw_version": f"SW: {self.device.device_info.version.software_major}.{self.device.device_info.version.software_minor}.{self.device.device_info.version.software_patch}, DATA: {self.device.device_info.version.datapoint_major}.{self.device.device_info.version.datapoint_minor}.{self.device.device_info.version.datapoint_patch}, SET: {self.device.device_info.version.setpoint_major}.{self.device.device_info.version.setpoint_minor}.{self.device.device_info.version.setpoint_patch}",
        }
        return info
