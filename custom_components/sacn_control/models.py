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
    CONF_PIXEL_COUNT,
    CONF_PIXEL_LAYOUT,
    CONF_START_CHANNEL,
    CONF_UNIVERSE,
    UNIVERSE_MAX,
    UNIVERSE_MIN,
    PIXEL_COUNT_MAX,
    PIXEL_COUNT_MIN,
    ChannelMode,
    PixelLayout,
    normalize_channel_mode,
    normalize_pixel_layout,
)
from .dmx import channels_for_mode
from .pixels import clamp_pixel_count


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
    pixel_count: int
    pixel_layout: PixelLayout

    @property
    def channel_count(self) -> int:
        """DMX channels consumed on the wire (one cell per physical pixel)."""
        return channels_for_mode(self.channel_mode) * max(0, self.pixel_count)

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
            CONF_PIXEL_COUNT: self.pixel_count,
            CONF_PIXEL_LAYOUT: self.pixel_layout.value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OutboundMap:
        """Parse a stored outbound mapping."""
        name = str(data.get(CONF_MAP_NAME) or "").strip() or "sACN fixture"
        mode = normalize_channel_mode(data.get(CONF_CHANNEL_MODE))
        start_channel = _clamp_int(
            data.get(CONF_START_CHANNEL), CHANNEL_MIN, CHANNEL_MAX, 1
        )
        return cls(
            map_id=str(data.get(CONF_MAP_ID) or _new_id()),
            name=name,
            universe=_clamp_int(data.get(CONF_UNIVERSE), UNIVERSE_MIN, UNIVERSE_MAX, 1),
            start_channel=start_channel,
            channel_mode=mode,
            pixel_count=clamp_pixel_count(
                _clamp_int(data.get(CONF_PIXEL_COUNT), PIXEL_COUNT_MIN, PIXEL_COUNT_MAX, 1),
                channel_mode=mode,
                start_channel=start_channel,
            ),
            pixel_layout=normalize_pixel_layout(data.get(CONF_PIXEL_LAYOUT)),
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
    if isinstance(mapping, OutboundMap) and mapping.pixel_count > 1:
        return f"{mapping.name} ({span}, {mode}, {mapping.pixel_count} px)"
    return f"{mapping.name} ({span}, {mode})"


_IN_PREFIX = "in|"
_OUT_PREFIX = "out|"


def mapping_token(mapping: InboundMap | OutboundMap) -> str:
    """Legacy remove-form value that does not depend on a regenerated map_id."""
    if isinstance(mapping, InboundMap):
        return f"{_IN_PREFIX}{mapping.entity_id}"
    return (
        f"{_OUT_PREFIX}{mapping.universe}|{mapping.start_channel}|"
        f"{mapping.channel_mode.value}|{mapping.pixel_count}|"
        f"{mapping.pixel_layout.value}|{mapping.name}"
    )


def mapping_removal_value(mapping: InboundMap | OutboundMap) -> str:
    """Select value: direction-namespaced map_id, otherwise the legacy token."""
    if isinstance(mapping, OutboundMap) and mapping.map_id:
        return f"{_OUT_PREFIX}{mapping.map_id}"
    return mapping_token(mapping)


def persist_outbound_map_ids(
    raw: Any, maps: list[OutboundMap]
) -> list[dict[str, Any]] | None:
    """Serialize outbound maps when any stored row is missing a map_id."""
    if not maps:
        return None
    if isinstance(raw, list) and all(
        isinstance(item, dict) and str(item.get(CONF_MAP_ID) or "").strip()
        for item in raw
    ):
        return None
    return [item.to_dict() for item in maps]


def remove_mapping_by_token(
    token: str,
    inbound: list[InboundMap],
    outbound: list[OutboundMap],
) -> tuple[list[InboundMap], list[OutboundMap]] | None:
    """Drop the mapping identified by token, map_id, entity_id, or label. None if nothing matched."""
    raw = str(token or "").strip()
    if not raw:
        return None

    inbound_kept = [item for item in inbound if mapping_token(item) != raw]
    if len(inbound_kept) < len(inbound):
        return inbound_kept, outbound
    outbound_kept = [item for item in outbound if mapping_token(item) != raw]
    if len(outbound_kept) < len(outbound):
        return inbound, outbound_kept

    if raw.startswith(_OUT_PREFIX):
        map_id = raw[len(_OUT_PREFIX) :]
        outbound_kept = [item for item in outbound if item.map_id != map_id]
        if len(outbound_kept) < len(outbound):
            return inbound, outbound_kept
    elif raw.startswith(_IN_PREFIX):
        map_id = raw[len(_IN_PREFIX) :]
        inbound_kept = [item for item in inbound if item.map_id != map_id]
        if len(inbound_kept) < len(inbound):
            return inbound_kept, outbound

    inbound_hits = any(item.map_id == raw for item in inbound)
    outbound_hits = any(item.map_id == raw for item in outbound)
    if inbound_hits and outbound_hits:
        return None
    if inbound_hits:
        return [item for item in inbound if item.map_id != raw], outbound
    if outbound_hits:
        return inbound, [item for item in outbound if item.map_id != raw]

    inbound_kept = [item for item in inbound if item.entity_id != raw]
    if len(inbound_kept) < len(inbound):
        return inbound_kept, outbound

    inbound_kept = [item for item in inbound if mapping_label(item) != raw]
    if len(inbound_kept) < len(inbound):
        return inbound_kept, outbound
    outbound_kept = [item for item in outbound if mapping_label(item) != raw]
    if len(outbound_kept) < len(outbound):
        return inbound, outbound_kept

    prefixed_in = "sACN → HA · "
    prefixed_out = "HA → sACN · "
    if raw.startswith(prefixed_in):
        label = raw[len(prefixed_in) :]
        inbound_kept = [item for item in inbound if mapping_label(item) != label]
        if len(inbound_kept) < len(inbound):
            return inbound_kept, outbound
    if raw.startswith(prefixed_out):
        label = raw[len(prefixed_out) :]
        outbound_kept = [item for item in outbound if mapping_label(item) != label]
        if len(outbound_kept) < len(outbound):
            return inbound, outbound_kept
    return None


def _channel_overlaps(left: InboundMap, universe: int, start: int, span: int) -> bool:
    if left.universe != universe:
        return False
    end = start + span - 1
    return not (left.end_channel < start or left.start_channel > end)


class NoChannelCapacityError(ValueError):
    """No contiguous DMX span remains on the requested universe."""


def next_free_channel(
    existing: list[InboundMap],
    universe: int,
    start_channel: int,
    span: int,
) -> int | None:
    """Return a free start channel, or None if no contiguous span remains."""
    channel = max(CHANNEL_MIN, min(CHANNEL_MAX, start_channel))
    span = max(1, span)
    while channel + span - 1 <= CHANNEL_MAX:
        if not any(_channel_overlaps(item, universe, channel, span) for item in existing):
            return channel
        channel += 1
    return None


def assign_inbound_maps(
    entity_ids: list[str],
    existing: list[InboundMap],
    *,
    universe: int,
    start_channel: int,
    channel_mode: ChannelMode | str,
    brightness: float = 1.0,
) -> list[InboundMap]:
    """Keep patches for still-selected lights; address newly selected lights sequentially."""
    selected = [
        entity_id.strip()
        for entity_id in entity_ids
        if isinstance(entity_id, str) and entity_id.strip().startswith("light.")
    ]
    seen: set[str] = set()
    ordered: list[str] = []
    for entity_id in selected:
        if entity_id in seen:
            continue
        seen.add(entity_id)
        ordered.append(entity_id)

    keep = {item.entity_id: item for item in existing if item.entity_id in seen}
    maps: list[InboundMap] = []
    for entity_id in ordered:
        if entity_id in keep:
            maps.append(keep[entity_id])

    mode = normalize_channel_mode(channel_mode)
    span = channels_for_mode(mode)
    next_channel = start_channel
    for entity_id in ordered:
        if entity_id in keep:
            continue
        next_channel = next_free_channel(maps, universe, next_channel, span)
        if next_channel is None:
            raise NoChannelCapacityError(
                f"No free {span}-channel span remains on universe {universe}"
            )
        maps.append(
            InboundMap.from_dict(
                {
                    CONF_ENTITY_ID: entity_id,
                    CONF_UNIVERSE: universe,
                    CONF_START_CHANNEL: next_channel,
                    CONF_CHANNEL_MODE: mode,
                    CONF_BRIGHTNESS: brightness,
                    CONF_MAP_NAME: entity_id,
                }
            )
        )
        next_channel += span
    return maps
