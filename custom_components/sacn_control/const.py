"""Constants for the sACN Control integration."""

from __future__ import annotations

from enum import StrEnum
from typing import Final

DOMAIN: Final = "sacn_control"
MANUFACTURER: Final = "sACN Control"
DEFAULT_NAME: Final = "sACN Control"

PLATFORMS: Final = ("light", "sensor", "switch")

CONF_BIND_IP: Final = "bind_ip"
CONF_SOURCE_NAME: Final = "source_name"
CONF_PRIORITY: Final = "priority"
CONF_RECEIVE_ENABLED: Final = "receive_enabled"
CONF_SEND_ENABLED: Final = "send_enabled"
CONF_HA_UPDATE_HZ: Final = "ha_update_hz"
CONF_TRANSITION: Final = "transition"
CONF_WHITE_BLEND: Final = "white_blend"
CONF_INBOUND_MAPS: Final = "inbound_maps"
CONF_OUTBOUND_MAPS: Final = "outbound_maps"

CONF_MAP_ID: Final = "map_id"
CONF_ENTITY_ID: Final = "entity_id"
CONF_ENTITY_IDS: Final = "entity_ids"
CONF_NEXT_STEP: Final = "next_step"
CONF_UNIVERSE: Final = "universe"
CONF_START_CHANNEL: Final = "start_channel"
CONF_CHANNEL_MODE: Final = "channel_mode"
CONF_PIXEL_COUNT: Final = "pixel_count"
CONF_PIXEL_LAYOUT: Final = "pixel_layout"
CONF_BRIGHTNESS: Final = "brightness"
CONF_MAP_NAME: Final = "name"

DEFAULT_SOURCE_NAME: Final = "Home Assistant"
DEFAULT_PRIORITY: Final = 100
DEFAULT_HA_UPDATE_HZ: Final = 10
DEFAULT_TRANSITION: Final = 0.05
DEFAULT_WHITE_BLEND: Final = 0.3
DEFAULT_KELVIN: Final = 3500
KELVIN_MIN: Final = 2500
KELVIN_MAX: Final = 9000

UNIVERSE_MIN: Final = 1
UNIVERSE_MAX: Final = 63999
CHANNEL_MIN: Final = 1
CHANNEL_MAX: Final = 512
DMX_CHANNELS: Final = 512
PRIORITY_MIN: Final = 0
PRIORITY_MAX: Final = 200
SOURCE_NAME_MAX: Final = 63

VALUE_CHANGE_THRESHOLD: Final = 1
U16_MAX: Final = 65535
U8_MAX: Final = 255

ATTR_UNIVERSE: Final = "universe"
ATTR_START_CHANNEL: Final = "start_channel"
ATTR_CHANNEL_MODE: Final = "channel_mode"
ATTR_PACKETS: Final = "packets_received"
ATTR_ACTIVE_UNIVERSES: Final = "active_universes"
ATTR_PIXEL_COUNT: Final = "pixel_count"
ATTR_PIXEL_LAYOUT: Final = "pixel_layout"

PIXEL_COUNT_MIN: Final = 1
PIXEL_COUNT_MAX: Final = 170
EFFECT_INTERVAL_S: Final = 0.05

EFFECT_OFF: Final = "off"
EFFECT_RAINBOW: Final = "rainbow"
EFFECT_CHASE: Final = "chase"
EFFECT_COLORLOOP: Final = "colorloop"
EFFECT_STROBE: Final = "strobe"
EFFECT_THEATER: Final = "theater"


class PixelLayout(StrEnum):
    """How a multi-pixel outbound fixture is addressed."""

    WHOLE = "whole"
    FULL = "full"
    GROUP_8 = "group_8"
    GROUP_4 = "group_4"
    GROUP_2 = "group_2"


PIXEL_LAYOUT_LABELS: dict[PixelLayout, str] = {
    PixelLayout.WHOLE: "Whole fixture (same colour on every pixel)",
    PixelLayout.FULL: "Full pixel (one DMX cell per pixel)",
    PixelLayout.GROUP_8: "RGB 8 pixel groups",
    PixelLayout.GROUP_4: "RGB 4 pixel groups",
    PixelLayout.GROUP_2: "RGB 2 pixel groups",
}

PIXEL_GROUP_COUNTS: dict[PixelLayout, int] = {
    PixelLayout.GROUP_8: 8,
    PixelLayout.GROUP_4: 4,
    PixelLayout.GROUP_2: 2,
}


class ChannelKind(StrEnum):
    """DMX personality kind."""

    RGB = "rgb"
    RGB_INTENSITY = "rgb_intensity"
    RGBW = "rgbw"
    HSBK = "hsbk"
    HSBK_INTENSITY = "hsbk_intensity"


class ChannelMode(StrEnum):
    """Stable channel-mode keys stored in config."""

    RGB_8 = "rgb_8"
    RGB_16 = "rgb_16"
    RGB_16_FINE = "rgb_16_fine_first"
    RGB_INTENSITY_8 = "rgb_intensity_8"
    RGBW_8 = "rgbw_8"
    RGBW_16 = "rgbw_16"
    RGBW_16_FINE = "rgbw_16_fine_first"
    HSBK_8 = "hsbk_8"
    HSBK_16 = "hsbk_16"
    HSBK_16_FINE = "hsbk_16_fine_first"
    HSBK_INTENSITY_8 = "hsbk_intensity_8"


# (kind, bit_depth, fine_first) — same personalities as sACN2HomeLX whole-fixture modes.
CHANNEL_MODE_SPEC: dict[ChannelMode, tuple[ChannelKind, int, bool]] = {
    ChannelMode.RGB_8: (ChannelKind.RGB, 8, False),
    ChannelMode.RGB_16: (ChannelKind.RGB, 16, False),
    ChannelMode.RGB_16_FINE: (ChannelKind.RGB, 16, True),
    ChannelMode.RGB_INTENSITY_8: (ChannelKind.RGB_INTENSITY, 8, False),
    ChannelMode.RGBW_8: (ChannelKind.RGBW, 8, False),
    ChannelMode.RGBW_16: (ChannelKind.RGBW, 16, False),
    ChannelMode.RGBW_16_FINE: (ChannelKind.RGBW, 16, True),
    ChannelMode.HSBK_8: (ChannelKind.HSBK, 8, False),
    ChannelMode.HSBK_16: (ChannelKind.HSBK, 16, False),
    ChannelMode.HSBK_16_FINE: (ChannelKind.HSBK, 16, True),
    ChannelMode.HSBK_INTENSITY_8: (ChannelKind.HSBK_INTENSITY, 8, False),
}

CHANNEL_MODE_LABELS: dict[ChannelMode, str] = {
    ChannelMode.RGB_8: "RGB (8bit)",
    ChannelMode.RGB_16: "RGB (16bit)",
    ChannelMode.RGB_16_FINE: "RGB (16bit, fine first)",
    ChannelMode.RGB_INTENSITY_8: "RGB + Intensity (8bit)",
    ChannelMode.RGBW_8: "RGBW (8bit)",
    ChannelMode.RGBW_16: "RGBW (16bit)",
    ChannelMode.RGBW_16_FINE: "RGBW (16bit, fine first)",
    ChannelMode.HSBK_8: "HSBK (8bit)",
    ChannelMode.HSBK_16: "HSBK (16bit)",
    ChannelMode.HSBK_16_FINE: "HSBK (16bit, fine first)",
    ChannelMode.HSBK_INTENSITY_8: "HSBK + Intensity (8bit)",
}

_KIND_BASE_CHANNELS: dict[ChannelKind, int] = {
    ChannelKind.RGB: 3,
    ChannelKind.RGB_INTENSITY: 4,
    ChannelKind.RGBW: 4,
    ChannelKind.HSBK: 4,
    ChannelKind.HSBK_INTENSITY: 5,
}

CHANNELS_FOR_MODE: dict[ChannelMode, int] = {
    mode: _KIND_BASE_CHANNELS[kind] * (2 if bits == 16 else 1)
    for mode, (kind, bits, _fine_first) in CHANNEL_MODE_SPEC.items()
}

# Accept sister-project display labels when importing mappings.
_LABEL_TO_MODE: dict[str, ChannelMode] = {
    label: mode for mode, label in CHANNEL_MODE_LABELS.items()
}

RGB_CAPABLE_HA_MODES: frozenset[str] = frozenset(
    {"rgb", "rgbw", "rgbww", "hs", "xy"}
)
COLOR_TEMP_HA_MODES: frozenset[str] = frozenset({"color_temp", "color_temp_kelvin"})
BRIGHTNESS_HA_MODES: frozenset[str] = (
    frozenset({"brightness"}) | RGB_CAPABLE_HA_MODES | COLOR_TEMP_HA_MODES
)


def normalize_channel_mode(value: str | ChannelMode | None) -> ChannelMode:
    """Resolve a stored key or sACN2HomeLX label to a ChannelMode."""
    if isinstance(value, ChannelMode):
        return value
    if not value:
        return ChannelMode.RGB_8
    raw = str(value).strip()
    try:
        return ChannelMode(raw)
    except ValueError:
        pass
    if raw in _LABEL_TO_MODE:
        return _LABEL_TO_MODE[raw]
    return ChannelMode.RGB_8


def normalize_pixel_layout(value: str | PixelLayout | None) -> PixelLayout:
    """Resolve a stored pixel layout key."""
    if isinstance(value, PixelLayout):
        return value
    if not value:
        return PixelLayout.WHOLE
    raw = str(value).strip()
    try:
        return PixelLayout(raw)
    except ValueError:
        return PixelLayout.WHOLE
