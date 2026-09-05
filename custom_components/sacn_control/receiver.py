"""sACN (E1.31) receiver wrapper around the sacn library."""

from __future__ import annotations

import logging
import socket
import threading
import time
from collections.abc import Callable
from typing import Any

from .const import DMX_CHANNELS

_LOGGER = logging.getLogger(__name__)

try:
    import ifaddr
except ImportError:  # pragma: no cover - optional at unit-test time
    ifaddr = None

try:
    import sacn
    from sacn.messages.data_packet import calculate_multicast_addr
except ImportError:  # pragma: no cover
    sacn = None
    calculate_multicast_addr = None


OnDmx = Callable[[int, list[int], tuple[int, ...] | None], None]


def local_ipv4_addresses() -> list[str]:
    """Non-loopback IPv4 addresses for multicast membership and the config flow."""
    addresses: list[str] = []
    seen: set[str] = set()
    if ifaddr is None:
        return addresses
    try:
        for adapter in ifaddr.get_adapters():
            for ip_info in adapter.ips:
                ip = ip_info.ip
                if not isinstance(ip, str) or ip.startswith("127.") or ip in seen:
                    continue
                seen.add(ip)
                addresses.append(ip)
    except Exception:  # noqa: BLE001 - discovery must not raise
        return []
    return addresses


class SacnReceiver:
    """Listen for E1.31 packets and deliver DMX frames on a background thread."""

    def __init__(
        self,
        bind_ip: str | None,
        on_dmx: OnDmx,
        ignore_cid: tuple[int, ...] | None = None,
    ) -> None:
        self._bind_ip = bind_ip or None
        self._on_dmx = on_dmx
        self._ignore_cid = ignore_cid
        self._lock = threading.RLock()
        self._receiver: Any = None
        self._universes: set[int] = set()
        self._running = False
        self.packets_received = 0
        self.last_packet_time: float | None = None
        self.active_universes: set[int] = set()
        self.packets_per_universe: dict[int, int] = {}

    @property
    def receiving(self) -> bool:
        """True if a packet arrived in the last two seconds."""
        if not self._running or self.last_packet_time is None:
            return False
        return (time.time() - self.last_packet_time) < 2.0

    def start(self, universes: set[int]) -> None:
        """Start the receiver and subscribe to universes."""
        if sacn is None:
            raise RuntimeError("The sacn package is not installed")
        with self._lock:
            self.stop()
            self._universes = set(universes)
            self._receiver = sacn.sACNreceiver()
            self._apply_multicast_interface()
            self._receiver.start()
            for universe in sorted(self._universes):
                self._register(universe)
            self._running = True
            _LOGGER.info(
                "sACN receiver started on %s for universes %s",
                self._bind_ip or "all interfaces",
                sorted(self._universes),
            )

    def update_universes(self, universes: set[int]) -> None:
        """Restart subscriptions when the mapped universe set changes."""
        with self._lock:
            if universes == self._universes and self._running:
                return
            if not self._running:
                self._universes = set(universes)
                return
            self.start(universes)

    def stop(self) -> None:
        """Stop the receiver."""
        with self._lock:
            self._running = False
            receiver = self._receiver
            self._receiver = None
        if receiver is not None:
            try:
                receiver.stop()
            except Exception:  # noqa: BLE001
                _LOGGER.debug("Error stopping sACN receiver", exc_info=True)

    def _membership_ips(self) -> list[str]:
        if self._bind_ip:
            return [self._bind_ip]
        addresses = local_ipv4_addresses()
        return addresses or ["0.0.0.0"]

    def _apply_multicast_interface(self) -> None:
        sock_impl = getattr(getattr(self._receiver, "_handler", None), "socket", None)
        if sock_impl is None:
            return
        try:
            sock_impl._bind_address = self._membership_ips()[0]
        except AttributeError:
            _LOGGER.debug("sACN receiver is missing multicast socket internals")

    def _register(self, universe: int) -> None:
        def handle_dmx(packet: Any) -> None:
            self._handle_packet(universe, packet)

        self._receiver.register_listener("universe", handle_dmx, universe=universe)
        self._join_multicast(universe)

    def _join_multicast(self, universe: int) -> None:
        ips = self._membership_ips()
        sock_impl = getattr(getattr(self._receiver, "_handler", None), "socket", None)
        if sock_impl is not None:
            try:
                sock_impl._bind_address = ips[0]
            except AttributeError:
                pass
        try:
            self._receiver.join_multicast(universe)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Could not join multicast for universe %s: %s", universe, err)
        if calculate_multicast_addr is None or sock_impl is None or len(ips) <= 1:
            return
        raw = getattr(sock_impl, "_socket", None)
        if raw is None:
            return
        mcast = calculate_multicast_addr(universe)
        for ip in ips[1:]:
            try:
                raw.setsockopt(
                    socket.IPPROTO_IP,
                    socket.IP_ADD_MEMBERSHIP,
                    socket.inet_aton(mcast) + socket.inet_aton(ip),
                )
            except OSError as err:
                _LOGGER.debug(
                    "Extra multicast join for universe %s on %s failed: %s",
                    universe,
                    ip,
                    err,
                )

    def _handle_packet(self, universe: int, packet: Any) -> None:
        if not self._running:
            return
        cid = _packet_cid(packet)
        if self._ignore_cid is not None and cid == self._ignore_cid:
            return
        dmx = _extract_dmx(packet)
        if dmx is None:
            return
        now = time.time()
        self.packets_received += 1
        self.last_packet_time = now
        self.active_universes.add(universe)
        self.packets_per_universe[universe] = self.packets_per_universe.get(universe, 0) + 1
        try:
            self._on_dmx(universe, dmx, cid)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Error delivering sACN packet for universe %s", universe)


def _packet_cid(packet: Any) -> tuple[int, ...] | None:
    cid = getattr(packet, "cid", None)
    if cid is None:
        return None
    if isinstance(cid, (bytes, bytearray)):
        return tuple(cid)
    if isinstance(cid, (list, tuple)):
        return tuple(int(part) for part in cid)
    return None


def _extract_dmx(packet: Any) -> list[int] | None:
    if hasattr(packet, "dmxData"):
        data = packet.dmxData
    elif hasattr(packet, "dmx_data"):
        data = packet.dmx_data
    elif hasattr(packet, "dmx"):
        data = packet.dmx
    elif isinstance(packet, (list, tuple)):
        data = packet
    else:
        return None
    values = [max(0, min(255, int(value))) for value in list(data)[:DMX_CHANNELS]]
    if len(values) < DMX_CHANNELS:
        values.extend([0] * (DMX_CHANNELS - len(values)))
    return values
