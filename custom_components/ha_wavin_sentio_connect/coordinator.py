
from datetime import timedelta
import logging
import async_timeout
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
# from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .data import get_device

_LOGGER = logging.getLogger(__name__)

class Coordinator(DataUpdateCoordinator):
    """My custom coordinator."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        """Initialize my coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            # Name of the data. For logging purposes.
            name="Wavin Sentio Connect",
            config_entry=entry,
            # Polling interval. Will only be polled if there are subscribers.
            update_interval=timedelta(seconds=10),
            # Set always_update to `False` if the data returned from the
            # api can be compared via `__eq__` to avoid duplicate updates
            # being dispatched to listeners
            always_update=True
        )
        self._device = get_device(hass, entry)

    # async def _async_setup(self):
    #     """Set up the coordinator

    #     This is the place to set up your coordinator,
    #     or to load data, that only needs to be loaded once.

    #     This method will be called automatically during
    #     coordinator.async_config_entry_first_refresh.
    #     """
    #     # await self._device.request_datapoint_read()
    #     # await self._device.request_setpoint_read()

    async def _async_update_data(self):
        """Fetch data from API endpoint.

        This is the place to pre-process the data to lookup tables
        so entities can quickly look up their data.
        """
        try:
            # Note: asyncio.TimeoutError and aiohttp.ClientError are already
            # handled by the data update coordinator.
            async with async_timeout.timeout(10):
                # Grab active context variables to limit data required to be fetched from API
                # Note: using context is not required if there is no need or ability to limit
                # data retrieved from API.
                # listening_idx = set(self.async_contexts())
                await self._device.request_datapoint_read()
                await self._device.request_setpoint_read()
                return dict[str,str]()
        except err: # type: ignore
            # Raising ConfigEntryAuthFailed will cancel future updates
            # and start a config flow with SOURCE_REAUTH (async_step_reauth)
            # raise ConfigEntryAuthFailed from err
            raise UpdateFailed(f"Error communicating with API: {err}") # type: ignore
        # except ApiError as err:

