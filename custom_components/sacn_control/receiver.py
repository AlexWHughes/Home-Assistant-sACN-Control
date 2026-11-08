"""sACN (E1.31) receiver wrapper around the sacn library."""

from __future__ import annotations

import logging
import socket
import threading
import time
from collections.abc import Callable, Sequence
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
OnLost = Callable[[int], None]
OnTerminated = Callable[[int], None]


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
        on_lost: OnLost | None = None,
        on_terminated: OnTerminated | None = None,
    ) -> None:
        self._bind_ip = bind_ip or None
        self._on_dmx = on_dmx
        self._on_lost = on_lost
        self._on_terminated = on_terminated
        self._ignore_cid = ignore_cid
        self._lock = threading.RLock()
        self._receiver: Any = None
        self._handlers: dict[int, Callable[[Any], None]] = {}
        self._universes: set[int] = set()
        self._running = False
        self.packets_received = 0
        self.last_packet_time: float | None = None
        self.active_universes: set[int] = set()
        self.packets_per_universe: dict[int, int] = {}

    @property
    def running(self) -> bool:
        """True while the receiver socket is open."""
        return self._running

    @property
    def receiving(self) -> bool:
        """True if a packet arrived in the last two seconds."""
        if not self._running or self.last_packet_time is None:
            return False
        return (time.time() - self.last_packet_time) < 2.0

    def start(self, universes: set[int], join_order: Sequence[int] | None = None) -> None:
        """Start the receiver and subscribe to universes."""
        if sacn is None:
            raise RuntimeError("The sacn package is not installed")
        with self._lock:
            self.stop()
            self._universes = set(universes)
            self._receiver = sacn.sACNreceiver()
            self._handlers = {}
            self._apply_multicast_interface()
            self._install_termination_hook()
            self._receiver.register_listener("availability", self._handle_availability)
            self._receiver.start()
            for universe in _join_sequence(self._universes, join_order):
                self._register(universe)
            self._running = True
            _LOGGER.info(
                "sACN receiver started on %s for universes %s",
                self._bind_ip or "all interfaces",
                sorted(self._universes),
            )

    def update_universes(self, universes: set[int], join_order: Sequence[int] | None = None) -> None:
        """Change subscriptions on the running receiver without reopening the socket.

        Reopening would drop the library's per-universe state, so a stream
        that ended during the gap would never report a timeout. sacn 1.11.0
        iterates its callback lists with no lock, so the receive thread is
        paused before those lists are edited.
        """
        with self._lock:
            wanted = set(universes)
            if not self._running or self._receiver is None:
                self._universes = wanted
                return
            if wanted == self._universes:
                return
            pause = self._pause_receive_loop()
            if pause == "restart":
                _LOGGER.warning("Restarting sACN receiver to change universe subscriptions")
                self.start(wanted, join_order)
                return
            if pause == "skipped":
                return
            if pause not in ("idle", "paused"):
                raise RuntimeError(f"Unexpected sACN pause state {pause}")
            try:
                for universe in sorted(self._universes - wanted):
                    self._unregister(universe)
                additions = wanted - self._universes
                for universe in _join_sequence(additions, join_order):
                    self._register(universe)
                self._universes = wanted
            finally:
                if pause == "paused":
                    self._resume_receive_loop()

    def sync(self, universes: set[int], join_order: Sequence[int] | None = None) -> None:
        """Run with exactly these universes: start, resubscribe or stop as needed."""
        with self._lock:
            if not universes:
                self.stop()
            elif self._running:
                self.update_universes(universes, join_order)
            else:
                self.start(universes, join_order)

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

    def _receive_socket(self) -> Any:
        """UDP socket used by the sacn receive thread, if the library exposed it."""
        return getattr(getattr(self._receiver, "_handler", None), "socket", None)

    def _install_termination_hook(self) -> None:
        """Invoke termination handling before sacn filters unchanged DMX.

        `fire_callbacks_universe` only notifies universe listeners when
        `dmxData` differs from the previous frame. A Stream_Terminated packet
        often repeats that frame, so the library would fire the availability
        timeout alone and never reach `_handle_packet`. Data-loss timeouts
        still come only from the availability listener.
        """
        handler = getattr(self._receiver, "_handler", None)
        original = getattr(handler, "fire_callbacks_universe", None)
        if handler is None or not callable(original):
            return

        def fire_callbacks_universe(packet: Any) -> None:
            if getattr(packet, "option_StreamTerminated", False):
                self._handle_packet(packet.universe, packet)
                return
            original(packet)

        handler.fire_callbacks_universe = fire_callbacks_universe

    def _pause_receive_loop(self) -> str:
        """Stop the receive thread without closing the socket.

        Returns "paused" when the caller must resume it, "idle" when no thread
        is running, "restart" when the only safe option is a new socket, and
        "skipped" when subscriptions must be left unchanged.
        """
        sock = self._receive_socket()
        thread = getattr(sock, "_thread", None) if sock is not None else None
        if thread is None or not getattr(thread, "is_alive", lambda: False)():
            return "idle"
        if thread is threading.current_thread():
            _LOGGER.error("Refusing to change sACN subscriptions from the receiver thread")
            return "skipped"
        if not hasattr(sock, "_enabled_flag"):
            return "restart"
        sock._enabled_flag = False
        thread.join(timeout=0.5)
        if thread.is_alive():
            # receive_loop sets the flag true as it starts. A second request
            # covers that window, then recv's 100ms timeout lets the thread exit.
            sock._enabled_flag = False
            thread.join(timeout=0.5)
        if thread.is_alive():
            # The thread is still inside a callback. Put it back into its loop.
            # Joining with no timeout would block the executor for good.
            sock._enabled_flag = True
            _LOGGER.error("sACN receiver thread did not pause; leaving subscriptions unchanged")
            return "skipped"
        return "paused"

    def _resume_receive_loop(self) -> None:
        """Restart the receive thread after a successful pause."""
        sock = self._receive_socket()
        if sock is None or not hasattr(sock, "start"):
            return
        thread = getattr(sock, "_thread", None)
        if thread is not None and thread.is_alive():
            return
        sock.start()

    def _membership_ips(self) -> list[str]:
        """Interfaces used for IGMP joins: the bind IP, or every non-loopback."""
        if self._bind_ip:
            return [self._bind_ip]
        addresses = local_ipv4_addresses()
        return addresses or ["0.0.0.0"]

    def _apply_multicast_interface(self) -> None:
        """Point the library socket at the preferred membership interface."""
        sock_impl = getattr(getattr(self._receiver, "_handler", None), "socket", None)
        if sock_impl is None:
            return
        try:
            sock_impl._bind_address = self._membership_ips()[0]
        except AttributeError:
            _LOGGER.debug("sACN receiver is missing multicast socket internals")

    def _register(self, universe: int) -> None:
        """Subscribe to one universe and join its multicast group."""
        def handle_dmx(packet: Any) -> None:
            self._handle_packet(universe, packet)

        self._handlers[universe] = handle_dmx
        self._receiver.register_listener("universe", handle_dmx, universe=universe)
        self._join_multicast(universe)

    def _unregister(self, universe: int) -> None:
        """Drop universe listeners and leave its multicast group."""
        handler = self._handlers.pop(universe, None)
        if handler is not None:
            # register_listener also files the handler under the trigger name,
            # which remove_listener_from_universe leaves behind.
            self._receiver.remove_listener(handler)
        self._receiver.remove_listener_from_universe(universe)
        try:
            self._receiver.leave_multicast(universe)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Could not leave multicast for universe %s: %s", universe, err)
        sock_impl = getattr(getattr(self._receiver, "_handler", None), "socket", None)
        raw = getattr(sock_impl, "_socket", None)
        ips = self._membership_ips()
        if calculate_multicast_addr is None or raw is None or len(ips) <= 1:
            return
        mcast = calculate_multicast_addr(universe)
        for ip in ips[1:]:
            try:
                raw.setsockopt(
                    socket.IPPROTO_IP,
                    socket.IP_DROP_MEMBERSHIP,
                    socket.inet_aton(mcast) + socket.inet_aton(ip),
                )
            except OSError:
                pass

    def _join_multicast(self, universe: int) -> None:
        """Join the E1.31 multicast group on every membership interface."""
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

    def _handle_availability(self, universe: int, changed: str) -> None:
        """The sacn library reports 'timeout' on data loss or stream termination."""
        if changed == "available":
            # The library only delivers data that differs from the last data it
            # saw on the universe, and keeps that across a timeout, so a stream
            # resuming with the same look would never be delivered. This runs
            # on the receiver thread before the packet's data is compared.
            handler = getattr(self._receiver, "_handler", None)
            previous = getattr(handler, "_previousData", None)
            if isinstance(previous, dict):
                previous.pop(universe, None)
            return
        if not self._running or changed != "timeout" or self._on_lost is None:
            return
        try:
            self._on_lost(universe)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Error delivering sACN stream loss for universe %s", universe)

    def _handle_packet(self, universe: int, packet: Any) -> None:
        """Deliver DMX, or termination, from one accepted universe packet."""
        if not self._running:
            return
        cid = _packet_cid(packet)
        if self._ignore_cid is not None and cid == self._ignore_cid:
            return
        if getattr(packet, "option_StreamTerminated", False):
            # E1.31 6.2.6: property values in a terminating packet are ignored.
            # The sacn library reports the stream lost and then still delivers
            # this packet's data, which would revive a stream that has ended.
            # on_terminated lets the bridge turn inbound lights off. The packet
            # values themselves are not applied.
            if self._on_terminated is not None:
                try:
                    self._on_terminated(universe)
                except Exception:  # noqa: BLE001
                    _LOGGER.exception(
                        "Error delivering sACN stream termination for universe %s",
                        universe,
                    )
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


def _join_sequence(universes: set[int], join_order: Sequence[int] | None) -> list[int]:
    """Universes in join order. Entries listed in `join_order` come first."""
    if not join_order:
        return sorted(universes)
    preferred = [universe for universe in join_order if universe in universes]
    return preferred + sorted(universes.difference(preferred))


def _packet_cid(packet: Any) -> tuple[int, ...] | None:
    """Normalise a packet CID to a comparable tuple of ints."""
    cid = getattr(packet, "cid", None)
    if cid is None:
        return None
    if isinstance(cid, (bytes, bytearray)):
        return tuple(cid)
    if isinstance(cid, (list, tuple)):
        return tuple(int(part) for part in cid)
    return None


def _extract_dmx(packet: Any) -> list[int] | None:
    """Read 512 clamped channel values from a sacn packet or raw sequence."""
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
