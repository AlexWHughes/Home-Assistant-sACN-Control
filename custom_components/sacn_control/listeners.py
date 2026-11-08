"""Raw DMX listeners: lets other integrations consume universes from the one receiver."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
import logging
from typing import Any

from .const import UNIVERSE_MAX, UNIVERSE_MIN

_LOGGER = logging.getLogger(__name__)

OnListenerDmx = Callable[[int, tuple[int, ...]], None]
OnListenerLost = Callable[[int], None]
FrameSource = Callable[[int], Sequence[int] | None]


@dataclass(frozen=True, slots=True, eq=False)
class _Listener:
    universes: frozenset[int]
    on_dmx: OnListenerDmx
    on_lost: OnListenerLost | None


class DmxListenerRegistry:
    """Subscribers to raw DMX, keyed by universe.

    Lives for as long as the integration is loaded, not per config entry, so
    subscriptions survive the entry reloading when mappings change. All methods
    are meant to be called from the Home Assistant event loop, except
    `has_universe`, which the receiver thread reads.

    A new subscriber is sent the current frame of each live universe straight
    away, taken from the frame source the bridge sets: the receiver only reports
    changes, so a static scene would otherwise reach it only when something
    moved. `schedule(fn, *args)` defers that replay so `register` never calls
    back into its caller; Home Assistant passes `loop.call_soon`.
    """

    def __init__(self, schedule: Callable[..., Any] | None = None) -> None:
        self._listeners: list[_Listener] = []
        self._universes: frozenset[int] = frozenset()
        self._on_change: Callable[[], None] | None = None
        self._frame_source: FrameSource | None = None
        self._schedule = schedule if schedule is not None else lambda fn, *args: fn(*args)

    def register(
        self,
        universes: Iterable[int],
        on_dmx: OnListenerDmx,
        on_lost: OnListenerLost | None = None,
    ) -> Callable[[], None]:
        """Subscribe to universes and return a function that unsubscribes.

        `on_dmx(universe, dmx)` gets all 512 slots as a tuple whenever the data
        on that universe changes, and the current frame of any live universe
        shortly after subscribing. `on_lost(universe)` is called when the
        universe's stream stops (E1.31 data loss timeout or stream termination)
        or reception stops (switched off, or the config entry unloading).
        """
        wanted = frozenset(int(universe) for universe in universes)
        if not wanted:
            raise ValueError("At least one universe is required")
        bad = sorted(u for u in wanted if not UNIVERSE_MIN <= u <= UNIVERSE_MAX)
        if bad:
            raise ValueError(f"Universes out of range {UNIVERSE_MIN}-{UNIVERSE_MAX}: {bad}")
        listener = _Listener(wanted, on_dmx, on_lost)
        self._listeners.append(listener)
        self._refresh()
        if self._frame_source is not None:
            self._schedule(self._replay, listener)

        def unregister() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)
                self._refresh()

        return unregister

    def set_change_callback(self, callback: Callable[[], None] | None) -> None:
        """Called whenever the set of subscribed universes changes."""
        self._on_change = callback

    def set_frame_source(self, source: FrameSource | None) -> None:
        """Where `register` finds the current frame of a live universe, or None."""
        self._frame_source = source

    @property
    def universes(self) -> frozenset[int]:
        """Union of every listener's universes."""
        return self._universes

    @property
    def count(self) -> int:
        """Number of registered listeners."""
        return len(self._listeners)

    def has_universe(self, universe: int) -> bool:
        """Thread-safe: reads an immutable snapshot."""
        return universe in self._universes

    def dispatch(self, universe: int, dmx: Sequence[int]) -> None:
        """Deliver a frame to the listeners of its universe."""
        frame = tuple(dmx)
        for listener in tuple(self._listeners):
            # Re-check membership: an earlier callback may have unsubscribed it.
            if universe in listener.universes and listener in self._listeners:
                try:
                    listener.on_dmx(universe, frame)
                except Exception:  # noqa: BLE001 - one bad listener must not starve the rest
                    _LOGGER.exception("sACN DMX listener failed on universe %s", universe)

    def lost(self, universe: int) -> None:
        """Tell the listeners of a universe that its stream stopped."""
        for listener in tuple(self._listeners):
            if (
                universe in listener.universes
                and listener.on_lost is not None
                and listener in self._listeners
            ):
                try:
                    listener.on_lost(universe)
                except Exception:  # noqa: BLE001
                    _LOGGER.exception("sACN DMX listener failed handling loss of universe %s", universe)

    def lost_all(self) -> None:
        """Tell every listener its universes stopped, e.g. when reception is switched off."""
        for universe in sorted(self._universes):
            self.lost(universe)

    def _replay(self, listener: _Listener) -> None:
        for universe in sorted(listener.universes):
            source = self._frame_source
            frame = source(universe) if source is not None else None
            if frame is None or listener not in self._listeners:
                continue
            try:
                listener.on_dmx(universe, tuple(frame))
            except Exception:  # noqa: BLE001
                _LOGGER.exception("sACN DMX listener failed on universe %s", universe)

    def _refresh(self) -> None:
        universes = frozenset().union(*(listener.universes for listener in self._listeners))
        if universes == self._universes:
            return
        self._universes = universes
        if self._on_change is not None:
            self._on_change()
