"""Mapping model tests."""

from __future__ import annotations

from sacn_control.const import ChannelMode
from sacn_control.models import InboundMap, OutboundMap, parse_inbound_maps, parse_outbound_maps


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
