"""The range a number entity offers, from the point it writes."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from wavin_sentio_connect import Point, RoomPointKey, room_key

from custom_components.wavin_sentio_connect.data import SentioData
from custom_components.wavin_sentio_connect.entity import Target, all_targets
from custom_components.wavin_sentio_connect.number import (
    NUMBERS,
    SentioNumber,
    SentioNumberDescription,
)

VACATION = room_key(1, RoomPointKey.TEMP_VACATION)


def _number_of(data: SentioData, key: str) -> tuple[Target, SentioNumberDescription]:
    return next(
        (target, description)
        for target, description in all_targets(data, NUMBERS)
        if target.key == key
    )


async def test_every_number_offers_the_values_its_point_can_be_written_with(
    hass: HomeAssistant, loaded: SentioData
) -> None:
    targets = all_targets(loaded, NUMBERS)
    assert targets
    for target, description in targets:
        number = SentioNumber(loaded, target, description)
        span = loaded.client.points[target.key].write_range()
        assert span is not None, target.key
        offered = (number.native_min_value, number.native_max_value, number.native_step)
        assert offered == (span.min, span.max, span.step), target.key


async def test_a_number_of_a_point_written_with_any_value_in_its_range_has_no_step_of_its_own(
    hass: HomeAssistant, loaded: SentioData, monkeypatch: pytest.MonkeyPatch
) -> None:
    point = loaded.client.points[VACATION]
    span = point.write_range()
    assert span is not None

    def any_value(self: Point[Any]):
        return dataclasses.replace(span, step=None)

    monkeypatch.setattr(type(point), "write_range", any_value)
    number = SentioNumber(loaded, *_number_of(loaded, VACATION))
    assert not hasattr(number, "_attr_native_step")


async def test_a_number_of_a_point_without_a_range_to_write_is_refused(
    hass: HomeAssistant, loaded: SentioData, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_range(self: Point[Any]) -> None:
        return None

    monkeypatch.setattr(type(loaded.client.points[VACATION]), "write_range", no_range)
    with pytest.raises(ValueError, match=str(VACATION)):
        SentioNumber(loaded, *_number_of(loaded, VACATION))
