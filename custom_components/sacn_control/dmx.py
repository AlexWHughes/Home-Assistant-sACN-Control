"""DMX encode/decode for sACN2HomeLX-compatible whole-fixture personalities."""

from __future__ import annotations

import colorsys
from dataclasses import dataclass
from typing import Never, Sequence

from .const import (
    CHANNEL_MODE_SPEC,
    CHANNELS_FOR_MODE,
    DEFAULT_KELVIN,
    DEFAULT_WHITE_BLEND,
    KELVIN_MAX,
    KELVIN_MIN,
    U16_MAX,
    U8_MAX,
    VALUE_CHANGE_THRESHOLD,
    ChannelKind,
    ChannelMode,
    normalize_channel_mode,
)


def clamp01(value: float) -> float:
    """Clamp a float to 0..1."""
    return max(0.0, min(1.0, float(value)))


def clamp_u8(value: float) -> int:
    """Clamp to an 8-bit DMX channel."""
    return max(0, min(U8_MAX, int(round(value))))


def channels_for_mode(mode: str | ChannelMode) -> int:
    """Return the DMX channel span for a whole-fixture mode."""
    return CHANNELS_FOR_MODE[normalize_channel_mode(mode)]


def mode_spec(mode: str | ChannelMode) -> tuple[ChannelKind, int, bool]:
    """Return (kind, bit depth, fine-first) for a mode."""
    return CHANNEL_MODE_SPEC[normalize_channel_mode(mode)]


def dmx_u16(first: int, second: int, fine_first: bool) -> int:
    """Combine two DMX bytes into 0..65535."""
    if fine_first:
        return ((second & 0xFF) << 8) | (first & 0xFF)
    return ((first & 0xFF) << 8) | (second & 0xFF)


def u16_to_bytes(value: int, fine_first: bool) -> tuple[int, int]:
    """Split 0..65535 into a coarse/fine or fine/coarse pair."""
    clamped = max(0, min(U16_MAX, int(value)))
    msb = (clamped >> 8) & 0xFF
    lsb = clamped & 0xFF
    if fine_first:
        return lsb, msb
    return msb, lsb


def kelvin_from_unit(unit: float) -> int:
    """Map 0..1 onto the 2500..9000 K console range used by sACN2HomeLX."""
    return int(
        max(KELVIN_MIN, min(KELVIN_MAX, KELVIN_MIN + clamp01(unit) * (KELVIN_MAX - KELVIN_MIN)))
    )


def unit_from_kelvin(kelvin: int) -> float:
    """Map kelvin back onto 0..1 using the same 2500..9000 K range."""
    span = float(KELVIN_MAX - KELVIN_MIN)
    return clamp01((int(kelvin) - KELVIN_MIN) / span)


def blend_white(
    red: float,
    green: float,
    blue: float,
    white: float,
    coeff: float = DEFAULT_WHITE_BLEND,
) -> tuple[float, float, float]:
    """Mix a white channel into RGB the same way sACN2HomeLX does."""
    mix = clamp01(coeff)
    return (
        min(1.0, red + white * mix),
        min(1.0, green + white * mix),
        min(1.0, blue + white * mix),
    )


def _param_unit(values: Sequence[int], index: int, bits: int, fine_first: bool) -> float:
    if bits == 16:
        start = index * 2
        return clamp01(dmx_u16(values[start], values[start + 1], fine_first) / U16_MAX)
    return clamp01(values[index] / U8_MAX)


def _append_param(out: list[int], unit: float, bits: int, fine_first: bool) -> None:
    clamped = clamp01(unit)
    if bits == 16:
        out.extend(u16_to_bytes(int(round(clamped * U16_MAX)), fine_first))
        return
    out.append(clamp_u8(clamped * U8_MAX))


@dataclass(frozen=True, slots=True)
class ColorCommand:
    """Decoded fixture colour used by inbound HA updates and outbound encode."""

    red: float
    green: float
    blue: float
    white: float
    hue: float
    saturation: float
    brightness: float
    kelvin: int
    intensity: float = 1.0

    @property
    def rgb8(self) -> tuple[int, int, int]:
        """RGB 0..255 after brightness is applied."""
        scale = clamp01(self.brightness)
        return (
            clamp_u8(self.red * scale * U8_MAX),
            clamp_u8(self.green * scale * U8_MAX),
            clamp_u8(self.blue * scale * U8_MAX),
        )

    @property
    def ha_brightness(self) -> int:
        """Home Assistant brightness 0..255 from the brightest RGB component."""
        return max(self.rgb8)

    @property
    def is_black(self) -> bool:
        """True when the fixture should be turned off."""
        return self.ha_brightness <= 0 or (
            self.rgb8 == (0, 0, 0) and self.white <= 0 and self.brightness <= 0
        )


def decode(
    mode: str | ChannelMode,
    channel_values: Sequence[int],
    brightness: float = 1.0,
    white_blend: float = DEFAULT_WHITE_BLEND,
) -> ColorCommand:
    """Map DMX bytes to a colour command (sACN2HomeLX-compatible)."""
    resolved = normalize_channel_mode(mode)
    kind, bits, fine_first = mode_spec(resolved)
    needed = channels_for_mode(resolved)
    if len(channel_values) < needed:
        raise ValueError(f"{resolved} needs {needed} channels, got {len(channel_values)}")

    def unit(index: int) -> float:
        return _param_unit(channel_values, index, bits, fine_first)

    mapping_bri = clamp01(brightness)

    if kind is ChannelKind.RGB:
        red, green, blue = unit(0), unit(1), unit(2)
        hue, saturation = colorsys.rgb_to_hsv(red, green, blue)[:2]
        return ColorCommand(
            red=red,
            green=green,
            blue=blue,
            white=0.0,
            hue=hue,
            saturation=saturation,
            brightness=mapping_bri,
            kelvin=DEFAULT_KELVIN,
        )

    if kind is ChannelKind.RGB_INTENSITY:
        intensity = unit(3)
        red, green, blue = unit(0) * intensity, unit(1) * intensity, unit(2) * intensity
        hue, saturation = colorsys.rgb_to_hsv(
            unit(0), unit(1), unit(2)
        )[:2]
        return ColorCommand(
            red=red,
            green=green,
            blue=blue,
            white=0.0,
            hue=hue,
            saturation=saturation,
            brightness=mapping_bri,
            kelvin=DEFAULT_KELVIN,
            intensity=intensity,
        )

    if kind is ChannelKind.RGBW:
        white = unit(3)
        red, green, blue = blend_white(unit(0), unit(1), unit(2), white, white_blend)
        hue, saturation = colorsys.rgb_to_hsv(red, green, blue)[:2]
        return ColorCommand(
            red=red,
            green=green,
            blue=blue,
            white=white,
            hue=hue,
            saturation=saturation,
            brightness=mapping_bri,
            kelvin=DEFAULT_KELVIN,
        )

    if kind is ChannelKind.HSBK:
        hue, saturation, value = unit(0), unit(1), unit(2)
        red, green, blue = colorsys.hsv_to_rgb(hue, saturation, 1.0)
        return ColorCommand(
            red=red,
            green=green,
            blue=blue,
            white=0.0,
            hue=hue,
            saturation=saturation,
            brightness=mapping_bri * value,
            kelvin=kelvin_from_unit(unit(3)),
        )

    if kind is ChannelKind.HSBK_INTENSITY:
        hue, saturation, value = unit(0), unit(1), unit(2)
        intensity = unit(4)
        red, green, blue = colorsys.hsv_to_rgb(hue, saturation, 1.0)
        return ColorCommand(
            red=red,
            green=green,
            blue=blue,
            white=0.0,
            hue=hue,
            saturation=saturation,
            brightness=mapping_bri * value * intensity,
            kelvin=kelvin_from_unit(unit(3)),
            intensity=intensity,
        )

    unreachable: Never = kind
    raise ValueError(f"Unhandled channel kind: {unreachable}")


def encode(
    mode: str | ChannelMode,
    command: ColorCommand,
) -> list[int]:
    """Map a colour command back to DMX bytes."""
    resolved = normalize_channel_mode(mode)
    kind, bits, fine_first = mode_spec(resolved)
    out: list[int] = []

    if kind is ChannelKind.RGB:
        scale = clamp01(command.brightness)
        _append_param(out, command.red * scale, bits, fine_first)
        _append_param(out, command.green * scale, bits, fine_first)
        _append_param(out, command.blue * scale, bits, fine_first)
        return out

    if kind is ChannelKind.RGB_INTENSITY:
        _append_param(out, command.red, bits, fine_first)
        _append_param(out, command.green, bits, fine_first)
        _append_param(out, command.blue, bits, fine_first)
        _append_param(out, command.intensity * clamp01(command.brightness), bits, fine_first)
        return out

    if kind is ChannelKind.RGBW:
        scale = clamp01(command.brightness)
        _append_param(out, command.red * scale, bits, fine_first)
        _append_param(out, command.green * scale, bits, fine_first)
        _append_param(out, command.blue * scale, bits, fine_first)
        _append_param(out, command.white * scale, bits, fine_first)
        return out

    if kind is ChannelKind.HSBK:
        _append_param(out, command.hue, bits, fine_first)
        _append_param(out, command.saturation, bits, fine_first)
        _append_param(out, command.brightness, bits, fine_first)
        _append_param(out, unit_from_kelvin(command.kelvin), bits, fine_first)
        return out

    if kind is ChannelKind.HSBK_INTENSITY:
        _append_param(out, command.hue, bits, fine_first)
        _append_param(out, command.saturation, bits, fine_first)
        _append_param(out, command.brightness, bits, fine_first)
        _append_param(out, unit_from_kelvin(command.kelvin), bits, fine_first)
        _append_param(out, command.intensity, bits, fine_first)
        return out

    unreachable: Never = kind
    raise ValueError(f"Unhandled channel kind: {unreachable}")


def values_changed(
    mode: str | ChannelMode,
    channel_values: Sequence[int],
    last_values: Sequence[int],
) -> bool:
    """True if DMX values changed enough to warrant an update."""
    resolved = normalize_channel_mode(mode)
    _kind, bits, fine_first = mode_spec(resolved)
    needed = channels_for_mode(resolved)
    if bits == 16 and len(channel_values) >= needed and len(last_values) >= needed:
        pairs = needed // 2
        for pair in range(pairs):
            index = pair * 2
            current = dmx_u16(channel_values[index], channel_values[index + 1], fine_first)
            previous = dmx_u16(last_values[index], last_values[index + 1], fine_first)
            if abs(current - previous) >= 1:
                return True
        return False
    for index, value in enumerate(channel_values):
        if index >= len(last_values):
            return True
        if abs(int(value) - int(last_values[index])) >= VALUE_CHANGE_THRESHOLD:
            return True
    return False


def command_from_ha(
    *,
    rgb: tuple[int, int, int] | None = None,
    rgbw: tuple[int, int, int, int] | None = None,
    hs: tuple[float, float] | None = None,
    brightness: int | None = None,
    kelvin: int | None = None,
    is_on: bool = True,
) -> ColorCommand:
    """Build a ColorCommand from a Home Assistant light turn-on payload."""
    bri_unit = 0.0 if not is_on else clamp01((brightness if brightness is not None else U8_MAX) / U8_MAX)
    if not is_on:
        return ColorCommand(
            red=0.0,
            green=0.0,
            blue=0.0,
            white=0.0,
            hue=0.0,
            saturation=0.0,
            brightness=0.0,
            kelvin=kelvin or DEFAULT_KELVIN,
            intensity=0.0,
        )

    if rgbw is not None:
        red, green, blue, white = (c / U8_MAX for c in rgbw)
        hue, saturation = colorsys.rgb_to_hsv(red, green, blue)[:2]
        return ColorCommand(
            red=red,
            green=green,
            blue=blue,
            white=white,
            hue=hue,
            saturation=saturation,
            brightness=bri_unit,
            kelvin=kelvin or DEFAULT_KELVIN,
            intensity=1.0,
        )

    if rgb is not None:
        red, green, blue = (c / U8_MAX for c in rgb)
        hue, saturation = colorsys.rgb_to_hsv(red, green, blue)[:2]
        return ColorCommand(
            red=red,
            green=green,
            blue=blue,
            white=0.0,
            hue=hue,
            saturation=saturation,
            brightness=bri_unit,
            kelvin=kelvin or DEFAULT_KELVIN,
            intensity=1.0,
        )

    if hs is not None:
        hue_deg, sat_pct = hs
        hue = clamp01(hue_deg / 360.0)
        saturation = clamp01(sat_pct / 100.0)
        red, green, blue = colorsys.hsv_to_rgb(hue, saturation, 1.0)
        return ColorCommand(
            red=red,
            green=green,
            blue=blue,
            white=0.0,
            hue=hue,
            saturation=saturation,
            brightness=bri_unit,
            kelvin=kelvin or DEFAULT_KELVIN,
            intensity=1.0,
        )

    # Brightness / color-temp only.
    return ColorCommand(
        red=1.0,
        green=1.0,
        blue=1.0,
        white=1.0,
        hue=0.0,
        saturation=0.0,
        brightness=bri_unit,
        kelvin=kelvin or DEFAULT_KELVIN,
        intensity=1.0,
    )
