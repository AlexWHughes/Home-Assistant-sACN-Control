"""DMX encode/decode tests aligned with sACN2HomeLX personalities."""

from __future__ import annotations

import pytest

from sacn_control.const import CHANNELS_FOR_MODE, DEFAULT_KELVIN, DEFAULT_WHITE_BLEND, ChannelMode
from sacn_control.dmx import (
    ColorCommand,
    command_from_ha,
    decode,
    encode,
    kelvin_from_unit,
    values_changed,
)


def test_channel_counts() -> None:
    assert CHANNELS_FOR_MODE[ChannelMode.RGB_8] == 3
    assert CHANNELS_FOR_MODE[ChannelMode.RGB_16] == 6
    assert CHANNELS_FOR_MODE[ChannelMode.RGB_16_FINE] == 6
    assert CHANNELS_FOR_MODE[ChannelMode.RGB_INTENSITY_8] == 4
    assert CHANNELS_FOR_MODE[ChannelMode.RGBW_8] == 4
    assert CHANNELS_FOR_MODE[ChannelMode.RGBW_16] == 8
    assert CHANNELS_FOR_MODE[ChannelMode.RGBW_16_FINE] == 8
    assert CHANNELS_FOR_MODE[ChannelMode.HSBK_8] == 4
    assert CHANNELS_FOR_MODE[ChannelMode.HSBK_16] == 8
    assert CHANNELS_FOR_MODE[ChannelMode.HSBK_16_FINE] == 8
    assert CHANNELS_FOR_MODE[ChannelMode.HSBK_INTENSITY_8] == 5


def test_rgb_8bit_full_red() -> None:
    command = decode("RGB (8bit)", [255, 0, 0], 1.0)
    assert command.red == pytest.approx(1.0)
    assert command.green == pytest.approx(0.0)
    assert command.blue == pytest.approx(0.0)
    assert command.kelvin == DEFAULT_KELVIN
    assert command.brightness == pytest.approx(1.0)
    assert command.rgb8 == (255, 0, 0)


def test_rgb_16bit_msb_first() -> None:
    command = decode(ChannelMode.RGB_16, [255, 255, 0, 0, 0, 0], 0.5)
    assert command.red == pytest.approx(1.0)
    assert command.green == pytest.approx(0.0)
    assert command.blue == pytest.approx(0.0)
    assert command.brightness == pytest.approx(0.5)


def test_rgb_16bit_fine_first_differs_from_msb() -> None:
    values = [0x34, 0x12, 0, 0, 0, 0]
    msb = decode(ChannelMode.RGB_16, values, 1.0)
    fine = decode(ChannelMode.RGB_16_FINE, values, 1.0)
    assert msb.red != pytest.approx(fine.red)
    assert fine.red == pytest.approx(0x1234 / 65535.0)


def test_rgb_plus_intensity() -> None:
    command = decode(ChannelMode.RGB_INTENSITY_8, [255, 255, 255, 128], 1.0)
    assert command.red == pytest.approx(128 / 255.0)
    assert command.green == pytest.approx(128 / 255.0)
    assert command.blue == pytest.approx(128 / 255.0)


def test_rgbw_blends_white() -> None:
    command = decode(ChannelMode.RGBW_8, [255, 0, 0, 255], 1.0)
    assert command.red == pytest.approx(1.0)
    assert command.green == pytest.approx(DEFAULT_WHITE_BLEND)
    assert command.blue == pytest.approx(DEFAULT_WHITE_BLEND)


def test_hsbk_8bit_full_value_white() -> None:
    command = decode(ChannelMode.HSBK_8, [0, 0, 255, 0], 1.0)
    assert command.red == pytest.approx(1.0)
    assert command.green == pytest.approx(1.0)
    assert command.blue == pytest.approx(1.0)
    assert command.kelvin == 2500
    assert command.brightness == pytest.approx(1.0)


def test_hsbk_intensity_scales_brightness() -> None:
    command = decode(ChannelMode.HSBK_INTENSITY_8, [0, 0, 255, 0, 128], 1.0)
    assert command.brightness == pytest.approx(128 / 255.0)


def test_8bit_change_threshold() -> None:
    assert not values_changed(ChannelMode.RGB_8, [10, 10, 10], [10, 10, 10])
    assert values_changed(ChannelMode.RGB_8, [11, 10, 10], [10, 10, 10])


def test_16bit_change_uses_combined_value() -> None:
    prev = [0x12, 0x34, 0, 0, 0, 0]
    assert not values_changed(ChannelMode.RGB_16, prev, prev)
    assert values_changed(ChannelMode.RGB_16, [0x12, 0x35, 0, 0, 0, 0], prev)


def test_black_command_is_off() -> None:
    command = decode(ChannelMode.RGB_8, [0, 0, 0], 1.0)
    assert command.is_black
    assert command.ha_brightness == 0


def test_kelvin_round_trip() -> None:
    assert kelvin_from_unit(0.0) == 2500
    assert kelvin_from_unit(1.0) == 9000


def test_encode_rgb_scales_brightness() -> None:
    command = command_from_ha(rgb=(255, 0, 0), brightness=128, is_on=True)
    assert encode(ChannelMode.RGB_8, command) == [128, 0, 0]


def test_encode_rgb_intensity_keeps_colour() -> None:
    command = command_from_ha(rgb=(255, 128, 0), brightness=64, is_on=True)
    encoded = encode(ChannelMode.RGB_INTENSITY_8, command)
    assert encoded[:3] == [255, 128, 0]
    assert encoded[3] == 64


def test_command_from_ha_off_is_black() -> None:
    command = command_from_ha(rgb=(255, 255, 255), is_on=False)
    assert command.is_black
    assert encode(ChannelMode.RGB_8, command) == [0, 0, 0]


def test_hsbk_encode_uses_value_channel() -> None:
    command = ColorCommand(
        red=1.0,
        green=0.0,
        blue=0.0,
        white=0.0,
        hue=0.0,
        saturation=1.0,
        brightness=0.5,
        kelvin=2500,
    )
    encoded = encode(ChannelMode.HSBK_8, command)
    assert encoded[0] == 0
    assert encoded[1] == 255
    assert encoded[2] == 128
    assert encoded[3] == 0
