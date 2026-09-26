"""Constants for the Wavin Sentio Connect integration."""

from typing import Final

DOMAIN: Final = "wavin_sentio_connect"

CONF_UNIT_ID: Final = "unit_id"
"""The Modbus unit id of the controller, kept in the config entry next to host and port."""

POLL_TICK: Final = 1.0
"""Longest wait, in seconds, between two calls to the client's poll.

The client plans every read itself, and a poll with nothing due sends nothing. The wait is
capped because a new subscription or a write's read-back can make a point due while the
loop sleeps.
"""
