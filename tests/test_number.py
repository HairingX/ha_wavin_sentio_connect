"""The range a number entity offers, from the point it writes."""

from __future__ import annotations

import pytest
from wavin_sentio_connect import DataType, Key, Limits, Point, Transform
from wavin_sentio_connect.testing import HoldingRegister

from custom_components.wavin_sentio_connect.number import value_range

KEY = Key("setting", float)
REGISTER = HoldingRegister(1)


def test_a_point_with_limits_offers_them() -> None:
    point = Point(KEY, read=REGISTER, write=REGISTER, limits=Limits(5, 35, step=0.5))
    assert value_range(point) == (5, 35, 0.5)


def test_a_point_without_limits_offers_what_its_encoding_carries() -> None:
    point = Point(
        KEY, read=REGISTER, write=REGISTER, data_type=DataType.INT16, scale=0.01,
        valid_raw=range(-0x8000, 0x7FFF),
    )
    assert value_range(point) == (-327.68, 327.66, 0.01)


def test_a_point_with_neither_limits_nor_a_range_is_refused() -> None:
    point = Point(KEY, read=REGISTER, write=REGISTER, valid_raw={0, 1})
    with pytest.raises(ValueError, match="neither limits nor a range"):
        value_range(point)


def test_a_transformed_point_is_refused() -> None:
    point = Point(
        KEY, read=REGISTER, write=REGISTER,
        transform=Transform(read=lambda v: v * 2, write=lambda v: v / 2),
    )
    with pytest.raises(ValueError, match="transformed"):
        value_range(point)
