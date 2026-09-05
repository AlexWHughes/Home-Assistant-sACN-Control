"""Pixel expansion and basic fixture effects for outbound sACN lights."""

from __future__ import annotations

import colorsys
from typing import Never

from .const import (
    CHANNEL_MAX,
    CHANNEL_MIN,
    EFFECT_CHASE,
    EFFECT_COLORLOOP,
    EFFECT_OFF,
    EFFECT_RAINBOW,
    EFFECT_STROBE,
    EFFECT_THEATER,
    PIXEL_COUNT_MAX,
    PIXEL_COUNT_MIN,
    PIXEL_GROUP_COUNTS,
    PixelLayout,
    normalize_channel_mode,
    normalize_pixel_layout,
)
from .dmx import ColorCommand, channels_for_mode, clamp01


EFFECT_LIST: tuple[str, ...] = (
    EFFECT_OFF,
    EFFECT_RAINBOW,
    EFFECT_CHASE,
    EFFECT_COLORLOOP,
    EFFECT_STROBE,
    EFFECT_THEATER,
)


def control_cell_count(layout: PixelLayout | str | None, pixel_count: int) -> int:
    """How many logical cells an effect should paint before expansion."""
    resolved = normalize_pixel_layout(layout)
    pixels = max(PIXEL_COUNT_MIN, int(pixel_count))
    if pixels <= 1:
        return 1
    match resolved:
        case PixelLayout.WHOLE:
            return 1
        case PixelLayout.FULL:
            return pixels
        case PixelLayout.GROUP_8 | PixelLayout.GROUP_4 | PixelLayout.GROUP_2:
            return max(1, min(PIXEL_GROUP_COUNTS[resolved], pixels))
        case _:
            unreachable: Never = resolved
            raise ValueError(f"Unhandled pixel layout: {unreachable}")


def clamp_pixel_count(
    pixel_count: int,
    *,
    channel_mode: str,
    start_channel: int,
) -> int:
    """Keep the fixture inside one 512-channel universe."""
    cell = max(1, channels_for_mode(normalize_channel_mode(channel_mode)))
    start = max(CHANNEL_MIN, int(start_channel))
    remaining = CHANNEL_MAX - start + 1
    room = max(0, remaining // cell)
    requested = int(pixel_count)
    if room <= 0 or requested <= 0:
        return 0
    return max(PIXEL_COUNT_MIN, min(PIXEL_COUNT_MAX, room, requested))


def expand_cells(cells: list[ColorCommand], pixel_count: int) -> list[ColorCommand]:
    """Repeat grouped control cells across physical pixels."""
    pixels = max(PIXEL_COUNT_MIN, int(pixel_count))
    if not cells:
        return []
    if len(cells) == 1:
        return list(cells) * pixels
    if len(cells) >= pixels:
        return list(cells[:pixels])
    return [cells[min(len(cells) - 1, i * len(cells) // pixels)] for i in range(pixels)]


def _command_with_rgb(
    base: ColorCommand,
    red: float,
    green: float,
    blue: float,
    brightness: float | None = None,
) -> ColorCommand:
    hue, saturation = colorsys.rgb_to_hsv(red, green, blue)[:2]
    return ColorCommand(
        red=red,
        green=green,
        blue=blue,
        white=base.white,
        hue=hue,
        saturation=saturation,
        brightness=base.brightness if brightness is None else clamp01(brightness),
        kelvin=base.kelvin,
        intensity=base.intensity,
    )


def _hsv_command(base: ColorCommand, hue: float) -> ColorCommand:
    red, green, blue = colorsys.hsv_to_rgb(hue % 1.0, 1.0, 1.0)
    return _command_with_rgb(base, red, green, blue)


def render_effect(
    effect: str,
    *,
    command: ColorCommand,
    pixel_count: int,
    layout: PixelLayout | str | None,
    frame: int,
) -> list[ColorCommand]:
    """Return one physical-pixel frame for the selected effect."""
    pixels = max(PIXEL_COUNT_MIN, int(pixel_count))
    cells = control_cell_count(layout, pixels)
    brightness = command.brightness
    name = effect or EFFECT_OFF

    if name == EFFECT_OFF:
        return expand_cells([command], pixels)

    if name == EFFECT_COLORLOOP:
        looped = _hsv_command(command, command.hue + frame * 0.02)
        return expand_cells([looped], pixels)

    if name == EFFECT_STROBE:
        if (frame // 2) % 2 == 0:
            return expand_cells([command], pixels)
        off = _command_with_rgb(command, 0.0, 0.0, 0.0, brightness=0.0)
        return expand_cells([off], pixels)

    if name == EFFECT_RAINBOW:
        offset = (frame % max(1, cells)) / max(1, cells)
        painted = [_hsv_command(command, i / max(1, cells) - offset) for i in range(cells)]
        return expand_cells(painted, pixels)

    if name == EFFECT_CHASE:
        dim = _command_with_rgb(command, 0.12, 0.32, 0.95, brightness=brightness * 0.35)
        hot = _command_with_rgb(command, 1.0, 1.0, 1.0)
        painted = [dim for _ in range(cells)]
        painted[frame % cells] = hot
        return expand_cells(painted, pixels)

    if name == EFFECT_THEATER:
        dim = _command_with_rgb(command, command.red, command.green, command.blue, brightness=brightness * 0.15)
        painted = [dim for _ in range(cells)]
        for index in range((frame % 3), cells, 3):
            painted[index] = command
        return expand_cells(painted, pixels)

    return expand_cells([command], pixels)
