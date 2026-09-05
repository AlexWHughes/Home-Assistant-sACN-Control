"""sACN (E1.31) sender wrapper around the sacn library."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from .universe import UniverseStore

_LOGGER = logging.getLogger(__name__)

try:
    import sacn
except ImportError:  # pragma: no cover
    sacn = None


class SacnSender:
    """Transmit DMX universes over multicast sACN."""

    def __init__(
        self,
        bind_ip: str | None,
        source_name: str,
        priority: int,
        cid: tuple[int, ...] | None = None,
    ) -> None:
        self._bind_ip = bind_ip or "0.0.0.0"
        self._source_name = source_name[:63]
        self._priority = max(0, min(200, int(priority)))
        self._cid = cid or tuple(uuid.uuid4().bytes)
        self._sender: Any = None
        self._active: set[int] = set()

    @property
    def cid(self) -> tuple[int, ...]:
        """E1.31 CID used so the receiver can ignore our own packets."""
        return self._cid

    def start(self) -> None:
        """Start the sender process."""
        if sacn is None:
            raise RuntimeError("The sacn package is not installed")
        self.stop()
        kwargs: dict[str, Any] = {
            "bind_address": self._bind_ip,
            "source_name": self._source_name,
            # Receiver owns UDP 5568; send from another port so both can run on one host.
            "bind_port": 5569,
            "fps": 40,
        }
        try:
            self._sender = sacn.sACNsender(cid=self._cid, **kwargs)
        except TypeError:
            self._sender = sacn.sACNsender(**kwargs)
        self._sender.start()
        _LOGGER.info(
            "sACN sender started (%s) priority=%s bind=%s",
            self._source_name,
            self._priority,
            self._bind_ip,
        )

    def stop(self) -> None:
        """Stop the sender and deactivate outputs."""
        sender = self._sender
        self._sender = None
        self._active.clear()
        if sender is None:
            return
        try:
            sender.stop()
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Error stopping sACN sender", exc_info=True)

    def sync_universes(self, universes: set[int], store: UniverseStore) -> None:
        """Activate mapped universes and push current buffers."""
        if self._sender is None:
            return
        for universe in list(self._active - universes):
            try:
                self._sender.deactivate_output(universe)
            except Exception:  # noqa: BLE001
                _LOGGER.debug("Could not deactivate universe %s", universe, exc_info=True)
            self._active.discard(universe)
        for universe in universes:
            if universe not in self._active:
                try:
                    self._sender.activate_output(universe)
                    output = self._sender[universe]
                    output.multicast = True
                    output.priority = self._priority
                    self._active.add(universe)
                except Exception:  # noqa: BLE001
                    _LOGGER.warning("Could not activate sACN output for universe %s", universe)
                    continue
            self.update_universe(universe, store)

    def update_universe(self, universe: int, store: UniverseStore) -> None:
        """Push one universe snapshot to the sender."""
        if self._sender is None or universe not in self._active:
            return
        try:
            self._sender[universe].dmx_data = store.snapshot(universe)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Could not write DMX for universe %s", universe, exc_info=True)
