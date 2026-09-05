"""Config mapping models for inbound and outbound sACN patches."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from .const import (
    CHANNEL_MAX,
    CHANNEL_MIN,
    CONF_BRIGHTNESS,
    CONF_CHANNEL_MODE,
    CONF_ENTITY_ID,
    CONF_MAP_ID,
    CONF_MAP_NAME,
    CONF_START_CHANNEL,
    CONF_UNIVERSE,
    UNIVERSE_MAX,
    UNIVERSE_MIN,
    ChannelMode,
    normalize_channel_mode,
)
from .dmx import channels_for_mode


def _new_id() -> str:
    return uuid4().hex[:12]


def _clamp_int(value: Any, minimum: int, maximum: int, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _clamp_float(value: Any, minimum: float, maximum: float, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


@dataclass(frozen=True, slots=True)
class InboundMap:
    """sACN universe/channel → existing Home Assistant light."""

    map_id: str
    entity_id: str
    universe: int
    start_channel: int
    channel_mode: ChannelMode
    brightness: float
    name: str

    @property
    def channel_count(self) -> int:
        """DMX channels consumed by this patch."""
        return channels_for_mode(self.channel_mode)

    @property
    def end_channel(self) -> int:
        """Inclusive last DMX channel."""
        return self.start_channel + self.channel_count - 1

    def to_dict(self) -> dict[str, Any]:
        """Serialize for config entry options."""
        return {
            CONF_MAP_ID: self.map_id,
            CONF_ENTITY_ID: self.entity_id,
            CONF_UNIVERSE: self.universe,
            CONF_START_CHANNEL: self.start_channel,
            CONF_CHANNEL_MODE: self.channel_mode.value,
            CONF_BRIGHTNESS: self.brightness,
            CONF_MAP_NAME: self.name,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InboundMap:
        """Parse a stored inbound mapping."""
        entity_id = str(data.get(CONF_ENTITY_ID) or "").strip()
        name = str(data.get(CONF_MAP_NAME) or "").strip() or entity_id
        return cls(
            map_id=str(data.get(CONF_MAP_ID) or _new_id()),
            entity_id=entity_id,
            universe=_clamp_int(data.get(CONF_UNIVERSE), UNIVERSE_MIN, UNIVERSE_MAX, 1),
            start_channel=_clamp_int(
                data.get(CONF_START_CHANNEL), CHANNEL_MIN, CHANNEL_MAX, 1
            ),
            channel_mode=normalize_channel_mode(data.get(CONF_CHANNEL_MODE)),
            brightness=_clamp_float(data.get(CONF_BRIGHTNESS), 0.0, 1.0, 1.0),
            name=name,
        )


@dataclass(frozen=True, slots=True)
class OutboundMap:
    """Home Assistant light entity → sACN fixture."""

    map_id: str
    name: str
    universe: int
    start_channel: int
    channel_mode: ChannelMode

    @property
    def channel_count(self) -> int:
        """DMX channels consumed by this fixture."""
        return channels_for_mode(self.channel_mode)

    @property
    def end_channel(self) -> int:
        """Inclusive last DMX channel."""
        return self.start_channel + self.channel_count - 1

    def to_dict(self) -> dict[str, Any]:
        """Serialize for config entry options."""
        return {
            CONF_MAP_ID: self.map_id,
            CONF_MAP_NAME: self.name,
            CONF_UNIVERSE: self.universe,
            CONF_START_CHANNEL: self.start_channel,
            CONF_CHANNEL_MODE: self.channel_mode.value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OutboundMap:
        """Parse a stored outbound mapping."""
        name = str(data.get(CONF_MAP_NAME) or "").strip() or "sACN fixture"
        return cls(
            map_id=str(data.get(CONF_MAP_ID) or _new_id()),
            name=name,
            universe=_clamp_int(data.get(CONF_UNIVERSE), UNIVERSE_MIN, UNIVERSE_MAX, 1),
            start_channel=_clamp_int(
                data.get(CONF_START_CHANNEL), CHANNEL_MIN, CHANNEL_MAX, 1
            ),
            channel_mode=normalize_channel_mode(data.get(CONF_CHANNEL_MODE)),
        )


def parse_inbound_maps(raw: Any) -> list[InboundMap]:
    """Parse inbound mappings from options, skipping invalid rows."""
    if not isinstance(raw, list):
        return []
    maps: list[InboundMap] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        parsed = InboundMap.from_dict(item)
        if parsed.entity_id.startswith("light."):
            maps.append(parsed)
    return maps


def parse_outbound_maps(raw: Any) -> list[OutboundMap]:
    """Parse outbound mappings from options."""
    if not isinstance(raw, list):
        return []
    maps: list[OutboundMap] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        maps.append(OutboundMap.from_dict(item))
    return maps


def mapping_label(mapping: InboundMap | OutboundMap) -> str:
    """Human label for options-flow removal lists."""
    mode = mapping.channel_mode.value
    span = f"U{mapping.universe} Ch {mapping.start_channel}–{mapping.end_channel}"
    return f"{mapping.name} ({span}, {mode})"
