from typing import TypedDict

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from wavin_sentio_connect import WavinSentioConnect # type: ignore

from custom_components.ha_wavin_sentio_connect.const import DOMAIN # type: ignore

class WavinSentioConnectHassData(TypedDict):
    device: WavinSentioConnect

def get_hass_data(hass: HomeAssistant, entry: ConfigEntry) -> WavinSentioConnectHassData:
    return hass.data[DOMAIN][entry.entry_id]

def get_device(hass: HomeAssistant, entry: ConfigEntry) -> WavinSentioConnect:
    data:WavinSentioConnectHassData = hass.data[DOMAIN][entry.entry_id]
    return data["device"]

def remove_hass_data(hass: HomeAssistant, entry: ConfigEntry) -> WavinSentioConnectHassData:
    return hass.data[DOMAIN].pop(entry.entry_id)

def set_hass_data(hass: HomeAssistant, entry: ConfigEntry, data:WavinSentioConnectHassData) -> None:
    hass.data[DOMAIN][entry.entry_id] = data
