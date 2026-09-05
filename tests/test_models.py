"""Mapping model tests."""

from __future__ import annotations

import pytest

from sacn_control.const import ChannelMode, PixelLayout
from sacn_control.models import (
    InboundMap,
    NoChannelCapacityError,
    OutboundMap,
    assign_inbound_maps,
    mapping_label,
    mapping_removal_value,
    mapping_token,
    next_free_channel,
    parse_inbound_maps,
    parse_outbound_maps,
    persist_outbound_map_ids,
    remove_mapping_by_token,
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
    assert restored.pixel_count == 1
    assert restored.pixel_layout == PixelLayout.WHOLE


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


def test_remove_inbound_by_stable_token_not_regenerated_map_id() -> None:
    stored = {
        "entity_id": "light.kitchen",
        "universe": 1,
        "start_channel": 1,
        "channel_mode": "rgb_8",
    }
    shown = InboundMap.from_dict(stored)
    submitted = InboundMap.from_dict(stored)
    assert shown.map_id != submitted.map_id
    removed = remove_mapping_by_token(mapping_token(shown), [submitted], [])
    assert removed is not None
    inbound, outbound = removed
    assert inbound == []
    assert outbound == []


def test_remove_outbound_by_token_and_label() -> None:
    mapping = OutboundMap.from_dict(
        {"name": "Stage Wash", "universe": 2, "start_channel": 5, "channel_mode": "rgb_8"}
    )
    by_token = remove_mapping_by_token(mapping_token(mapping), [], [mapping])
    assert by_token is not None
    assert by_token[1] == []
    by_label = remove_mapping_by_token(f"HA → sACN · {mapping_label(mapping)}", [], [mapping])
    assert by_label is not None
    assert by_label[1] == []
    assert remove_mapping_by_token("missing", [], [mapping]) is None


def test_outbound_multi_pixel_channel_count() -> None:
    mapping = OutboundMap.from_dict(
        {
            "name": "Cove",
            "universe": 1,
            "start_channel": 1,
            "channel_mode": "rgb_8",
            "pixel_count": 30,
            "pixel_layout": "full",
        }
    )
    assert mapping.pixel_count == 30
    assert mapping.pixel_layout == PixelLayout.FULL
    assert mapping.channel_count == 90
    assert mapping.end_channel == 90
    assert "30 px" in mapping_label(mapping)
    restored = OutboundMap.from_dict(mapping.to_dict())
    assert restored.pixel_count == 30
    assert restored.pixel_layout == PixelLayout.FULL


def test_outbound_pixel_count_clamps_to_universe() -> None:
    mapping = OutboundMap.from_dict(
        {
            "name": "Tail",
            "universe": 1,
            "start_channel": 500,
            "channel_mode": "rgb_8",
            "pixel_count": 170,
        }
    )
    assert mapping.pixel_count == 4
    assert mapping.end_channel == 511


def test_outbound_zero_capacity_at_channel_max() -> None:
    mapping = OutboundMap.from_dict(
        {
            "name": "Overflow",
            "universe": 1,
            "start_channel": 512,
            "channel_mode": "rgb_8",
            "pixel_count": 8,
        }
    )
    assert mapping.pixel_count == 0
    assert mapping.channel_count == 0


def test_mapping_removal_value_prefers_persisted_map_id() -> None:
    mapping = OutboundMap.from_dict(
        {
            "map_id": "fixture-1",
            "name": "Stage Wash",
            "universe": 2,
            "start_channel": 5,
            "channel_mode": "rgb_8",
        }
    )
    assert mapping_removal_value(mapping) == "out|fixture-1"
    removed = remove_mapping_by_token(mapping_removal_value(mapping), [], [mapping])
    assert removed is not None
    assert removed[1] == []
    by_bare = remove_mapping_by_token("fixture-1", [], [mapping])
    assert by_bare is not None
    assert by_bare[1] == []
    legacy = OutboundMap(
        map_id="",
        name="Legacy",
        universe=1,
        start_channel=1,
        channel_mode=ChannelMode.RGB_8,
        pixel_count=1,
        pixel_layout=PixelLayout.WHOLE,
    )
    assert mapping_removal_value(legacy) == mapping_token(legacy)
    assert mapping_removal_value(
        InboundMap.from_dict({"entity_id": "light.kitchen", "universe": 1, "start_channel": 1})
    ).startswith("in|")


def test_persist_outbound_map_ids_migrates_missing_ids() -> None:
    raw = [{"name": "A", "universe": 1, "start_channel": 1, "channel_mode": "rgb_8"}]
    maps = parse_outbound_maps(raw)
    migrated = persist_outbound_map_ids(raw, maps)
    assert migrated is not None
    assert migrated[0]["map_id"] == maps[0].map_id
    assert persist_outbound_map_ids(migrated, parse_outbound_maps(migrated)) is None
    assert persist_outbound_map_ids(raw, []) is None


def test_remove_colliding_inbound_and_outbound_ids_stays_directional() -> None:
    inbound = InboundMap.from_dict(
        {
            "map_id": "shared",
            "entity_id": "light.kitchen",
            "universe": 1,
            "start_channel": 1,
            "channel_mode": "rgb_8",
        }
    )
    outbound = OutboundMap.from_dict(
        {
            "map_id": "shared",
            "name": "Stage Wash",
            "universe": 2,
            "start_channel": 5,
            "channel_mode": "rgb_8",
        }
    )
    by_out = remove_mapping_by_token(
        mapping_removal_value(outbound), [inbound], [outbound]
    )
    assert by_out is not None
    assert by_out[0] == [inbound]
    assert by_out[1] == []
    by_in = remove_mapping_by_token(
        mapping_removal_value(inbound), [inbound], [outbound]
    )
    assert by_in is not None
    assert by_in[0] == []
    assert by_in[1] == [outbound]
    assert remove_mapping_by_token("shared", [inbound], [outbound]) is None
    namespaced_in = remove_mapping_by_token("in|shared", [inbound], [outbound])
    assert namespaced_in is not None
    assert namespaced_in[0] == []
    assert namespaced_in[1] == [outbound]
