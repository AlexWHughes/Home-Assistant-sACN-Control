"""Mapping model tests."""

from __future__ import annotations

import pytest

from sacn_control.const import ChannelMode
from sacn_control.models import (
    InboundMap,
    NoChannelCapacityError,
    OutboundMap,
    assign_inbound_maps,
    next_free_channel,
    parse_inbound_maps,
    parse_outbound_maps,
)


def test_inbound_from_sister_label() -> None:
    mapping = InboundMap.from_dict(
        {
            "entity_id": "light.living_room",
            "universe": 1,
            "start_channel": 10,
            "channel_mode": "RGB (8bit)",
            "brightness": 0.8,
            "name": "Living Room",
        }
    )
    assert mapping.channel_mode == ChannelMode.RGB_8
    assert mapping.channel_count == 3
    assert mapping.end_channel == 12
    assert mapping.entity_id == "light.living_room"


def test_parse_inbound_skips_non_lights() -> None:
    maps = parse_inbound_maps(
        [
            {"entity_id": "switch.kitchen", "universe": 1, "start_channel": 1},
            {"entity_id": "light.kitchen", "universe": 1, "start_channel": 1},
        ]
    )
    assert len(maps) == 1
    assert maps[0].entity_id == "light.kitchen"


def test_outbound_round_trip() -> None:
    mapping = OutboundMap.from_dict(
        {
            "name": "Stage Wash",
            "universe": 2,
            "start_channel": 5,
            "channel_mode": "hsbk_8",
        }
    )
    restored = OutboundMap.from_dict(mapping.to_dict())
    assert restored.name == "Stage Wash"
    assert restored.universe == 2
    assert restored.start_channel == 5
    assert restored.channel_mode == ChannelMode.HSBK_8
    assert restored.channel_count == 4


def test_parse_outbound_ignores_junk() -> None:
    assert parse_outbound_maps(None) == []
    assert parse_outbound_maps("nope") == []
    assert len(parse_outbound_maps([{"name": "A", "universe": 1, "start_channel": 1}])) == 1


def test_assign_inbound_keeps_existing_and_addresses_new() -> None:
    existing = [
        InboundMap.from_dict(
            {
                "entity_id": "light.kitchen",
                "universe": 1,
                "start_channel": 1,
                "channel_mode": "rgb_8",
            }
        )
    ]
    maps = assign_inbound_maps(
        ["light.kitchen", "light.lounge", "light.bedroom"],
        existing,
        universe=1,
        start_channel=1,
        channel_mode=ChannelMode.RGB_8,
    )
    by_id = {item.entity_id: item for item in maps}
    assert by_id["light.kitchen"].start_channel == 1
    assert by_id["light.lounge"].start_channel == 4
    assert by_id["light.bedroom"].start_channel == 7
    assert by_id["light.lounge"].universe == 1


def test_assign_inbound_drops_deselected() -> None:
    existing = [
        InboundMap.from_dict({"entity_id": "light.keep", "universe": 1, "start_channel": 1}),
        InboundMap.from_dict({"entity_id": "light.drop", "universe": 1, "start_channel": 4}),
    ]
    maps = assign_inbound_maps(
        ["light.keep"],
        existing,
        universe=1,
        start_channel=1,
        channel_mode="rgb_8",
    )
    assert [item.entity_id for item in maps] == ["light.keep"]


def test_next_free_channel_returns_none_when_tail_is_occupied() -> None:
    existing = [
        InboundMap.from_dict(
            {
                "entity_id": "light.tail",
                "universe": 1,
                "start_channel": 510,
                "channel_mode": "rgb_8",
            }
        )
    ]
    assert next_free_channel(existing, 1, 510, 3) is None


def test_assign_inbound_raises_instead_of_colliding() -> None:
    existing = [
        InboundMap.from_dict(
            {
                "entity_id": "light.tail",
                "universe": 1,
                "start_channel": 510,
                "channel_mode": "rgb_8",
            }
        )
    ]
    with pytest.raises(NoChannelCapacityError):
        assign_inbound_maps(
            ["light.tail", "light.overflow"],
            existing,
            universe=1,
            start_channel=510,
            channel_mode=ChannelMode.RGB_8,
        )
