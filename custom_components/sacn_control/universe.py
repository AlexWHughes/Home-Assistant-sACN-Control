"""Per-universe 512-channel DMX buffers for outbound sACN."""

from __future__ import annotations

import threading

from .const import DMX_CHANNELS


class UniverseStore:
    """Thread-safe 512-byte buffers keyed by universe number."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buffers: dict[int, bytearray] = {}
        self._dirty: set[int] = set()

    def write(self, universe: int, start_channel: int, values: list[int]) -> None:
        """Write values starting at a 1-based DMX channel."""
        if start_channel < 1:
            return
        offset = start_channel - 1
        if offset >= DMX_CHANNELS:
            return
        clipped = values[: DMX_CHANNELS - offset]
        with self._lock:
            buffer = self._buffers.setdefault(universe, bytearray(DMX_CHANNELS))
            buffer[offset : offset + len(clipped)] = (max(0, min(255, int(v))) for v in clipped)
            self._dirty.add(universe)

    def snapshot(self, universe: int) -> tuple[int, ...]:
        """Return a 512-tuple copy of a universe."""
        with self._lock:
            buffer = self._buffers.get(universe)
            if buffer is None:
                return tuple(0 for _ in range(DMX_CHANNELS))
            return tuple(buffer)

    def dirty_universes(self) -> list[int]:
        """Universes written since the last take_dirty call."""
        with self._lock:
            return list(self._dirty)

    def take_dirty(self) -> list[int]:
        """Return and clear the dirty set."""
        with self._lock:
            dirty = list(self._dirty)
            self._dirty.clear()
            return dirty

    def universes(self) -> list[int]:
        """Universes that have been written at least once."""
        with self._lock:
            return list(self._buffers)
