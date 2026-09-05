"""Universe buffer tests."""

from __future__ import annotations

from sacn_control.universe import UniverseStore


def test_write_is_one_based() -> None:
    store = UniverseStore()
    store.write(1, 1, [10, 20, 30])
    snapshot = store.snapshot(1)
    assert snapshot[0:3] == (10, 20, 30)
    assert snapshot[3] == 0
    assert len(snapshot) == 512


def test_write_clips_and_clamps() -> None:
    store = UniverseStore()
    store.write(3, 511, [100, 200, 300])
    snapshot = store.snapshot(3)
    assert snapshot[510] == 100
    assert snapshot[511] == 200


def test_dirty_tracking() -> None:
    store = UniverseStore()
    assert store.take_dirty() == []
    store.write(1, 1, [1])
    store.write(2, 1, [2])
    dirty = set(store.take_dirty())
    assert dirty == {1, 2}
    assert store.take_dirty() == []
