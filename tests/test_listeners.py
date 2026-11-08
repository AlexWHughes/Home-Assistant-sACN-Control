"""DMX listener registry tests."""

from __future__ import annotations

import pytest

from sacn_control.listeners import DmxListenerRegistry
from sacn_control.receiver import SacnReceiver


def test_dispatch_reaches_only_subscribers_of_that_universe() -> None:
    registry = DmxListenerRegistry()
    got: list[tuple[str, int, list[int]]] = []
    registry.register([1], lambda u, d: got.append(("a", u, d)))
    registry.register([1, 2], lambda u, d: got.append(("b", u, d)))
    registry.dispatch(2, [7])
    registry.dispatch(3, [9])
    assert got == [("b", 2, (7,))]  # frames arrive as immutable tuples
    registry.dispatch(1, [5])
    assert [name for name, _, _ in got[1:]] == ["a", "b"]


def test_universes_union_and_change_callback() -> None:
    registry = DmxListenerRegistry()
    changes: list[frozenset[int]] = []
    registry.set_change_callback(lambda: changes.append(registry.universes))
    unsub_a = registry.register([1, 2], lambda u, d: None)
    unsub_b = registry.register([2, 3], lambda u, d: None)
    assert registry.universes == {1, 2, 3}
    assert registry.count == 2
    unsub_b()
    assert registry.universes == {1, 2}
    unsub_b()  # idempotent
    unsub_a()
    assert registry.universes == frozenset()
    assert changes == [frozenset({1, 2}), frozenset({1, 2, 3}), frozenset({1, 2}), frozenset()]


def test_no_change_callback_when_union_is_unchanged() -> None:
    registry = DmxListenerRegistry()
    registry.register([1], lambda u, d: None)
    changes: list[int] = []
    registry.set_change_callback(lambda: changes.append(1))
    unsub = registry.register([1], lambda u, d: None)
    unsub()
    assert changes == []


def test_has_universe_reads_snapshot() -> None:
    registry = DmxListenerRegistry()
    assert not registry.has_universe(4)
    registry.register([4], lambda u, d: None)
    assert registry.has_universe(4)


@pytest.mark.parametrize("universes", [[], [0], [64000]])
def test_register_rejects_bad_universes(universes: list[int]) -> None:
    with pytest.raises(ValueError):
        DmxListenerRegistry().register(universes, lambda u, d: None)


def test_a_failing_listener_does_not_starve_the_rest() -> None:
    registry = DmxListenerRegistry()
    got: list[int] = []

    def boom(_u: int, _d: list[int]) -> None:
        raise RuntimeError("boom")

    registry.register([1], boom)
    registry.register([1], lambda u, d: got.append(u))
    registry.dispatch(1, [0])
    assert got == [1]


def test_lost_and_lost_all() -> None:
    registry = DmxListenerRegistry()
    lost: list[tuple[str, int]] = []
    registry.register([1, 2], lambda u, d: None, lambda u: lost.append(("a", u)))
    registry.register([2], lambda u, d: None)  # no on_lost: skipped
    registry.lost(2)
    assert lost == [("a", 2)]
    lost.clear()
    registry.lost_all()
    assert lost == [("a", 1), ("a", 2)]


def test_receiver_reports_stream_timeout_only_while_running() -> None:
    lost: list[int] = []
    receiver = SacnReceiver(bind_ip=None, on_dmx=lambda *_: None, on_lost=lost.append)
    receiver._handle_availability(universe=3, changed="timeout")
    assert lost == []  # not running
    receiver._running = True
    receiver._handle_availability(universe=3, changed="available")
    receiver._handle_availability(universe=3, changed="timeout")
    assert lost == [3]
    assert receiver.running


class _Packet:
    def __init__(self, terminated: bool) -> None:
        self.dmxData = (1, 2, 3)
        self.option_StreamTerminated = terminated


def test_receiver_ignores_data_in_stream_termination_packets() -> None:
    got: list[int] = []
    receiver = SacnReceiver(bind_ip=None, on_dmx=lambda universe, dmx, cid: got.append(universe))
    receiver._running = True
    receiver._handle_packet(1, _Packet(terminated=True))
    assert got == []
    receiver._handle_packet(1, _Packet(terminated=False))
    assert got == [1]


class _FakeSacnLib:
    """Stands in for sacn.sACNreceiver, recording what the wrapper asks of it."""

    def __init__(self) -> None:
        self.callbacks: dict[int, list] = {}
        self.joined: set[int] = set()
        self.availability = None
        self.running = False

    def register_listener(self, trigger: str, func, **kwargs) -> None:
        if trigger == "availability":
            self.availability = func
        else:
            self.callbacks.setdefault(kwargs["universe"], []).append(func)

    def remove_listener(self, func) -> None:
        for funcs in self.callbacks.values():
            while func in funcs:
                funcs.remove(func)

    def remove_listener_from_universe(self, universe: int) -> None:
        self.callbacks.pop(universe, None)

    def join_multicast(self, universe: int) -> None:
        self.joined.add(universe)

    def leave_multicast(self, universe: int) -> None:
        self.joined.discard(universe)

    def start(self) -> None:
        self.running = True

    def stop(self) -> None:
        self.running = False


@pytest.fixture
def fake_sacn(monkeypatch: pytest.MonkeyPatch) -> list[_FakeSacnLib]:
    import sacn_control.receiver as receiver_module

    made: list[_FakeSacnLib] = []

    def factory() -> _FakeSacnLib:
        made.append(_FakeSacnLib())
        return made[-1]

    monkeypatch.setattr(receiver_module, "sacn", type("sacn", (), {"sACNreceiver": staticmethod(factory)}))
    return made


def test_sync_resubscribes_without_reopening_the_socket(fake_sacn: list[_FakeSacnLib]) -> None:
    receiver = SacnReceiver(bind_ip="127.0.0.1", on_dmx=lambda *_: None)
    receiver.sync({1})
    assert len(fake_sacn) == 1 and receiver.running
    lib = fake_sacn[0]
    assert set(lib.callbacks) == {1} and lib.joined == {1} and lib.availability is not None

    receiver.sync({1, 2})
    receiver.sync({2})
    assert len(fake_sacn) == 1  # same socket throughout
    assert set(lib.callbacks) == {2} and lib.joined == {2}

    receiver.sync(set())
    assert not receiver.running and not lib.running


def test_update_universes_while_stopped_only_records_them(fake_sacn: list[_FakeSacnLib]) -> None:
    receiver = SacnReceiver(bind_ip="127.0.0.1", on_dmx=lambda *_: None)
    receiver.update_universes({5})
    assert fake_sacn == [] and not receiver.running


def test_new_subscriber_gets_the_current_frame_via_schedule() -> None:
    queued: list = []
    live = {1: [9, 8]}
    registry = DmxListenerRegistry(schedule=lambda fn, *args: queued.append((fn, args)))
    registry.set_frame_source(live.get)
    got: list[tuple[int, tuple[int, ...]]] = []
    registry.register([1, 2], lambda u, d: got.append((u, d)))
    assert got == []  # never called back from inside register()
    fn, args = queued.pop()
    fn(*args)
    assert got == [(1, (9, 8))]  # universe 2 has no live frame


def test_replay_skipped_after_unsubscribe_or_when_the_stream_is_gone() -> None:
    queued: list = []
    live = {1: [1]}
    registry = DmxListenerRegistry(schedule=lambda fn, *args: queued.append((fn, args)))
    registry.set_frame_source(live.get)
    got: list[int] = []
    unsub = registry.register([1], lambda u, d: got.append(u))
    unsub()
    registry.register([1], lambda u, d: got.append(u * 10))
    live.clear()  # stream lost before the replay ran
    for fn, args in queued:
        fn(*args)
    assert got == []


def test_no_replay_without_a_frame_source() -> None:
    queued: list = []
    registry = DmxListenerRegistry(schedule=lambda fn, *args: queued.append((fn, args)))
    registry.register([1], lambda u, d: None)
    assert queued == []  # no bridge running


def test_unsubscribed_during_dispatch_is_not_called() -> None:
    registry = DmxListenerRegistry()
    got: list[str] = []
    unsub_b = None

    def a(_u: int, _d: tuple[int, ...]) -> None:
        got.append("a")
        unsub_b()

    registry.register([1], a)
    unsub_b = registry.register([1], lambda u, d: got.append("b"))
    registry.dispatch(1, [0])
    assert got == ["a"]


sacn_lib = pytest.importorskip("sacn")


def _real_receiver(monkeypatch: pytest.MonkeyPatch):
    """The wrapper around the real sacn library, on a socket that never opens."""
    from sacn.receiving.receiver_socket_base import ReceiverSocketBase

    import sacn_control.receiver as receiver_module

    class StubSocket(ReceiverSocketBase):
        def start(self) -> None: ...
        def stop(self) -> None: ...
        def join_multicast(self, _addr: str) -> None: ...
        def leave_multicast(self, _addr: str) -> None: ...

    libs: list = []
    real_receiver = sacn_lib.sACNreceiver

    def factory():
        lib = real_receiver(socket=StubSocket(None))
        lib._handler.socket._listener = lib._handler
        libs.append(lib)
        return lib

    monkeypatch.setattr(receiver_module, "sacn", type("sacn", (), {"sACNreceiver": staticmethod(factory)}))
    events: list = []
    receiver = SacnReceiver(
        bind_ip="127.0.0.1",
        on_dmx=lambda universe, dmx, cid: events.append(("dmx", universe, dmx[0])),
        on_lost=lambda universe: events.append(("lost", universe)),
    )
    return receiver, libs, events


def _packet(seq: int, value: int, terminated: bool = False) -> bytes:
    from sacn.messages.data_packet import DataPacket

    return DataPacket(
        cid=tuple(range(16)), sourceName="test", universe=1, dmxData=(value,),
        priority=100, sequence=seq, streamTerminated=terminated,
    ).getBytes()


def test_real_library_stream_resuming_with_the_same_data_is_delivered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receiver, libs, events = _real_receiver(monkeypatch)
    receiver.sync({1})
    handler = libs[0]._handler
    handler.on_data(_packet(1, 10), 0.0)
    handler.on_periodic_callback(5.0)  # data loss timeout
    handler.on_data(_packet(2, 10), 6.0)  # same look again
    assert events == [("dmx", 1, 10), ("lost", 1), ("dmx", 1, 10)]
    events.clear()
    handler.on_data(_packet(3, 10, terminated=True), 7.0)
    handler.on_data(_packet(4, 10), 8.0)
    assert events == [("lost", 1), ("dmx", 1, 10)]  # termination carries no data


def test_real_library_resubscribe_does_not_leak_callbacks(monkeypatch: pytest.MonkeyPatch) -> None:
    receiver, libs, _ = _real_receiver(monkeypatch)
    receiver.sync({1})
    before = sum(len(v) for v in libs[0]._callbacks.values())
    for _ in range(5):
        receiver.sync({1, 2})
        receiver.sync({1})
    assert len(libs) == 1
    assert sum(len(v) for v in libs[0]._callbacks.values()) == before
