"""Pixel expansion and effect tests."""

from __future__ import annotations

from sacn_control.const import (
    EFFECT_CHASE,
    EFFECT_COLORLOOP,
    EFFECT_OFF,
    EFFECT_RAINBOW,
    EFFECT_STROBE,
    EFFECT_THEATER,
    PixelLayout,
)
from sacn_control.dmx import ColorCommand
from sacn_control.pixels import clamp_pixel_count, control_cell_count, expand_cells, render_effect


def _base() -> ColorCommand:
    return ColorCommand(
        red=1.0,
        green=0.0,
        blue=0.0,
        white=0.0,
        hue=0.0,
        saturation=1.0,
        brightness=1.0,
        kelvin=3500,
        intensity=1.0,
    )


def test_control_cell_count() -> None:
    assert control_cell_count(PixelLayout.WHOLE, 30) == 1
    assert control_cell_count(PixelLayout.FULL, 30) == 30
    assert control_cell_count(PixelLayout.GROUP_8, 30) == 8
    assert control_cell_count(PixelLayout.GROUP_4, 30) == 4
    assert control_cell_count(PixelLayout.GROUP_2, 30) == 2
    assert control_cell_count(PixelLayout.GROUP_8, 3) == 3
    assert control_cell_count(PixelLayout.FULL, 1) == 1


def test_clamp_pixel_count_fits_universe() -> None:
    assert clamp_pixel_count(30, channel_mode="rgb_8", start_channel=1) == 30
    assert clamp_pixel_count(170, channel_mode="rgb_8", start_channel=1) == 170
    assert clamp_pixel_count(200, channel_mode="rgb_8", start_channel=1) == 170
    assert clamp_pixel_count(170, channel_mode="rgb_8", start_channel=500) == 4
    assert clamp_pixel_count(20, channel_mode="rgb_16", start_channel=1) == 20
    assert clamp_pixel_count(10, channel_mode="rgb_8", start_channel=512) == 0
    assert clamp_pixel_count(10, channel_mode="rgb_8", start_channel=511) == 0
    assert clamp_pixel_count(10, channel_mode="rgb_8", start_channel=510) == 1


def test_expand_cells_repeats_and_tiles() -> None:
    red = _base()
    blue = ColorCommand(
        red=0.0,
        green=0.0,
        blue=1.0,
        white=0.0,
        hue=0.66,
        saturation=1.0,
        brightness=1.0,
        kelvin=3500,
        intensity=1.0,
    )
    assert expand_cells([red], 4) == [red, red, red, red]
    assert expand_cells([red, blue], 2) == [red, blue]
    tiled = expand_cells([red, blue], 4)
    assert tiled == [red, red, blue, blue]


def test_render_off_and_strobe() -> None:
    command = _base()
    assert render_effect(
        EFFECT_OFF, command=command, pixel_count=4, layout=PixelLayout.FULL, frame=0
    ) == [command] * 4
    on = render_effect(
        EFFECT_STROBE, command=command, pixel_count=3, layout=PixelLayout.WHOLE, frame=0
    )
    off = render_effect(
        EFFECT_STROBE, command=command, pixel_count=3, layout=PixelLayout.WHOLE, frame=2
    )
    assert on == [command] * 3
    assert all(cell.brightness == 0.0 for cell in off)


def test_render_rainbow_uses_layout_cells() -> None:
    command = _base()
    whole = render_effect(
        EFFECT_RAINBOW, command=command, pixel_count=8, layout=PixelLayout.WHOLE, frame=0
    )
    assert len(whole) == 8
    assert all(cell == whole[0] for cell in whole)
    full = render_effect(
        EFFECT_RAINBOW, command=command, pixel_count=8, layout=PixelLayout.FULL, frame=0
    )
    assert len(full) == 8
    assert full[0].hue != full[1].hue


def test_render_chase_and_theater_move() -> None:
    command = _base()
    chase_a = render_effect(
        EFFECT_CHASE, command=command, pixel_count=6, layout=PixelLayout.FULL, frame=0
    )
    chase_b = render_effect(
        EFFECT_CHASE, command=command, pixel_count=6, layout=PixelLayout.FULL, frame=1
    )
    assert chase_a[0].brightness > chase_a[1].brightness
    assert chase_b[1].brightness > chase_b[0].brightness
    theater = render_effect(
        EFFECT_THEATER, command=command, pixel_count=6, layout=PixelLayout.FULL, frame=0
    )
    assert theater[0] == command
    assert theater[1].brightness < command.brightness
    assert theater[3] == command


def test_render_colorloop_shifts_hue() -> None:
    command = _base()
    first = render_effect(
        EFFECT_COLORLOOP, command=command, pixel_count=4, layout=PixelLayout.WHOLE, frame=0
    )
    later = render_effect(
        EFFECT_COLORLOOP, command=command, pixel_count=4, layout=PixelLayout.WHOLE, frame=10
    )
    assert first[0].hue != later[0].hue
    assert all(cell.hue == first[0].hue for cell in first)
