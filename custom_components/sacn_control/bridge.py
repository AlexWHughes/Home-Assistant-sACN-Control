"""Runtime bridge between sACN frames and Home Assistant lights."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
import time
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_RGB_COLOR,
    DOMAIN as LIGHT_DOMAIN,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, SERVICE_TURN_OFF, SERVICE_TURN_ON
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    BRIGHTNESS_HA_MODES,
    COLOR_TEMP_HA_MODES,
    CONF_BIND_IP,
    CONF_HA_UPDATE_HZ,
    CONF_INBOUND_MAPS,
    CONF_OUTBOUND_MAPS,
    CONF_PRIORITY,
    CONF_RECEIVE_ENABLED,
    CONF_SEND_ENABLED,
    CONF_SOURCE_NAME,
    CONF_TRANSITION,
    CONF_WHITE_BLEND,
    DEFAULT_HA_UPDATE_HZ,
    DEFAULT_NAME,
    DEFAULT_PRIORITY,
    DEFAULT_SOURCE_NAME,
    DEFAULT_TRANSITION,
    DEFAULT_WHITE_BLEND,
    RGB_CAPABLE_HA_MODES,
)
from .dmx import ColorCommand, decode, encode, values_changed
from .listeners import DmxListenerRegistry
from .models import (
    InboundMap,
    OutboundMap,
    parse_inbound_maps,
    parse_outbound_maps,
    persist_outbound_map_ids,
)
from .pixels import expand_cells
from .receiver import SacnReceiver
from .sender import SacnSender
from .universe import UniverseStore

_LOGGER = logging.getLogger(__name__)

_RECEIVE_STALE_S = 2.0


class SacnBridge:
    """Owns the sACN sockets and applies inbound/outbound mappings."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        listeners: DmxListenerRegistry,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.listeners = listeners
        self.store = UniverseStore()
        self.sender = SacnSender(
            bind_ip=_optional_ip(entry.data.get(CONF_BIND_IP)),
            source_name=str(entry.data.get(CONF_SOURCE_NAME) or DEFAULT_SOURCE_NAME),
            priority=int(entry.data.get(CONF_PRIORITY, DEFAULT_PRIORITY)),
        )
        self.receiver = SacnReceiver(
            bind_ip=_optional_ip(entry.data.get(CONF_BIND_IP)),
            on_dmx=self._on_dmx,
            ignore_cid=self.sender.cid,
            on_lost=self._on_lost,
        )
        self.inbound: list[InboundMap] = []
        self.outbound: list[OutboundMap] = []
        self._latest_dmx: dict[int, list[int]] = {}
        # Universes with a stream right now; written by the receiver thread.
        self._live: set[int] = set()
        self._last_applied: dict[str, list[int]] = {}
        self._inbound_dirty = False
        # Serialises receiver changes, which run in the executor, so they apply
        # in order and none can restart the receiver after async_stop.
        self._receiver_lock = asyncio.Lock()
        self._stopped = False
        self._unsub_tick = None
        self._last_stats_push = 0.0
        self.coordinator = DataUpdateCoordinator(
            hass,
            _LOGGER,
            name=DEFAULT_NAME,
            update_method=self._async_stats,
            update_interval=None,
        )
        self.reload_mappings()

    @property
    def receive_enabled(self) -> bool:
        """Whether inbound sACN should drive Home Assistant lights."""
        return bool(self.entry.data.get(CONF_RECEIVE_ENABLED, True))

    @property
    def send_enabled(self) -> bool:
        """Whether outbound fixtures should transmit sACN."""
        return bool(self.entry.data.get(CONF_SEND_ENABLED, True))

    @property
    def transition(self) -> float:
        """Seconds passed to light.turn_on / turn_off for inbound updates."""
        try:
            return max(0.0, min(5.0, float(self.entry.data.get(CONF_TRANSITION, DEFAULT_TRANSITION))))
        except (TypeError, ValueError):
            return DEFAULT_TRANSITION

    @property
    def white_blend(self) -> float:
        """RGBW white mix coefficient."""
        try:
            return max(0.0, min(1.0, float(self.entry.data.get(CONF_WHITE_BLEND, DEFAULT_WHITE_BLEND))))
        except (TypeError, ValueError):
            return DEFAULT_WHITE_BLEND

    @property
    def ha_update_hz(self) -> int:
        """Inbound apply rate."""
        try:
            return max(1, min(40, int(self.entry.data.get(CONF_HA_UPDATE_HZ, DEFAULT_HA_UPDATE_HZ))))
        except (TypeError, ValueError):
            return DEFAULT_HA_UPDATE_HZ

    def reload_mappings(self) -> None:
        """Reload patches from the config entry options."""
        raw_outbound = self.entry.options.get(CONF_OUTBOUND_MAPS)
        self.inbound = parse_inbound_maps(self.entry.options.get(CONF_INBOUND_MAPS))
        self.outbound = parse_outbound_maps(raw_outbound)
        migrated = persist_outbound_map_ids(raw_outbound, self.outbound)
        if migrated is not None:
            current = dict(self.entry.options)
            current[CONF_OUTBOUND_MAPS] = migrated
            self.hass.config_entries.async_update_entry(self.entry, options=current)

    def inbound_universes(self) -> set[int]:
        """Universes that inbound mappings listen on."""
        return {item.universe for item in self.inbound}

    def receive_universes(self) -> set[int]:
        """Universes the receiver joins: inbound mappings plus DMX listeners."""
        return self.inbound_universes() | self.listeners.universes

    def outbound_universes(self) -> set[int]:
        """Universes that outbound fixtures transmit on."""
        return {item.universe for item in self.outbound}

    async def async_start(self) -> None:
        """Open sockets and start the inbound apply tick."""
        # Before the receiver starts, so a listener registering meanwhile is seen.
        self.listeners.set_change_callback(self._on_listener_universes_changed)
        self.listeners.set_frame_source(self._current_frame)
        await self.hass.async_add_executor_job(self._start_sender)
        await self._async_sync_receiver()
        interval = 1.0 / self.ha_update_hz
        self._unsub_tick = async_track_time_interval(
            self.hass,
            self._async_tick,
            timedelta(seconds=interval),
        )
        await self.coordinator.async_config_entry_first_refresh()

    async def async_stop(self) -> None:
        """Close sockets and cancel the apply tick."""
        if self._unsub_tick is not None:
            self._unsub_tick()
            self._unsub_tick = None
        self.listeners.set_change_callback(None)
        self.listeners.set_frame_source(None)
        async with self._receiver_lock:
            self._stopped = True
            await self.hass.async_add_executor_job(self._stop_sockets)
        self._live.clear()
        self.listeners.lost_all()

    def _start_sender(self) -> None:
        if self.send_enabled and self.outbound:
            self.sender.start()
            self.sender.sync_universes(self.outbound_universes(), self.store)

    def _stop_sockets(self) -> None:
        self.receiver.stop()
        self.sender.stop()

    async def async_set_receive(self, enabled: bool) -> None:
        """Enable or disable inbound reception."""
        self.hass.config_entries.async_update_entry(
            self.entry,
            data={**self.entry.data, CONF_RECEIVE_ENABLED: enabled},
        )
        await self._async_sync_receiver()
        if not enabled:
            self._live.clear()
            self.listeners.lost_all()

    async def async_set_send(self, enabled: bool) -> None:
        """Enable or disable outbound transmission."""
        self.hass.config_entries.async_update_entry(
            self.entry,
            data={**self.entry.data, CONF_SEND_ENABLED: enabled},
        )
        await self.hass.async_add_executor_job(self._apply_send_state, enabled)

    async def _async_sync_receiver(self) -> None:
        """Start, resubscribe or stop the receiver to match what is wanted."""
        async with self._receiver_lock:
            if self._stopped:
                return
            # Read on the loop, under the lock, so the latest wanted set wins.
            universes = self.receive_universes() if self.receive_enabled else set()
            await self.hass.async_add_executor_job(self.receiver.sync, universes)

    @callback
    def _on_listener_universes_changed(self) -> None:
        self.entry.async_create_background_task(
            self.hass, self._async_sync_receiver(), "sacn_control receiver resubscribe"
        )

    def _apply_send_state(self, enabled: bool) -> None:
        if enabled and self.outbound:
            self.sender.start()
            self.sender.sync_universes(self.outbound_universes(), self.store)
            return
        self.sender.stop()

    def _on_dmx(
        self,
        universe: int,
        dmx: list[int],
        _cid: tuple[int, ...] | None,
    ) -> None:
        self._latest_dmx[universe] = dmx
        self._live.add(universe)
        self._inbound_dirty = True
        if self.listeners.has_universe(universe):
            # Receiver thread: hand each frame to the event loop as it arrives,
            # not at the inbound tick rate.
            self.hass.loop.call_soon_threadsafe(self._deliver_dmx, universe, tuple(dmx))

    @callback
    def _deliver_dmx(self, universe: int, dmx: tuple[int, ...]) -> None:
        # A frame queued just before the receiver stopped would otherwise reach
        # listeners after lost_all() told them the stream had ended.
        if self.receiver.running:
            self.listeners.dispatch(universe, dmx)

    def _current_frame(self, universe: int) -> list[int] | None:
        """Latest frame of a live universe, for replay to a new listener."""
        if not self.receiver.running or universe not in self._live:
            return None
        return self._latest_dmx.get(universe)

    def _on_lost(self, universe: int) -> None:
        # Receiver thread.
        self._live.discard(universe)
        if self.listeners.has_universe(universe):
            self.hass.loop.call_soon_threadsafe(self.listeners.lost, universe)

    async def _async_tick(self, _now: Any = None) -> None:
        if self.receive_enabled and self._inbound_dirty:
            self._inbound_dirty = False
            await self._async_apply_inbound()
        if self.send_enabled:
            dirty = self.store.take_dirty()
            if dirty:
                await self.hass.async_add_executor_job(self._push_dirty, dirty)
        now = time.time()
        if now - self._last_stats_push >= 2.0:
            self._last_stats_push = now
            await self.coordinator.async_request_refresh()

    def _push_dirty(self, universes: list[int]) -> None:
        for universe in universes:
            self.sender.update_universe(universe, self.store)

    async def _async_apply_inbound(self) -> None:
        for mapping in self.inbound:
            dmx = self._latest_dmx.get(mapping.universe)
            if dmx is None:
                continue
            start = mapping.start_channel - 1
            end = start + mapping.channel_count
            if start < 0 or end > len(dmx):
                continue
            values = dmx[start:end]
            last = self._last_applied.get(mapping.map_id)
            if last is not None and not values_changed(mapping.channel_mode, values, last):
                continue
            try:
                command = decode(
                    mapping.channel_mode,
                    values,
                    brightness=mapping.brightness,
                    white_blend=self.white_blend,
                )
            except ValueError:
                _LOGGER.debug("Skipping inbound map %s: short DMX frame", mapping.map_id)
                continue
            self._last_applied[mapping.map_id] = list(values)
            await self._async_push_ha_light(mapping, command)

    async def _async_push_ha_light(self, mapping: InboundMap, command: ColorCommand) -> None:
        if not self.hass.states.get(mapping.entity_id):
            return
        if command.is_black:
            await self.hass.services.async_call(
                LIGHT_DOMAIN,
                SERVICE_TURN_OFF,
                {ATTR_ENTITY_ID: mapping.entity_id, "transition": self.transition},
                blocking=False,
            )
            return
        await self.hass.services.async_call(
            LIGHT_DOMAIN,
            SERVICE_TURN_ON,
            _turn_on_payload(self.hass, mapping.entity_id, command, self.transition),
            blocking=False,
        )

    def write_outbound(self, mapping: OutboundMap, command: ColorCommand) -> None:
        """Encode a solid colour across every physical pixel."""
        self.write_outbound_cells(mapping, [command])

    def write_outbound_cells(self, mapping: OutboundMap, cells: list[ColorCommand]) -> None:
        """Encode per-pixel commands onto the outbound universe."""
        if mapping.pixel_count <= 0:
            return
        values: list[int] = []
        for cell in expand_cells(cells, mapping.pixel_count):
            values.extend(encode(mapping.channel_mode, cell))
        self.store.write(mapping.universe, mapping.start_channel, values)

    def outbound_for_id(self, map_id: str) -> OutboundMap | None:
        """Find an outbound mapping by id."""
        for mapping in self.outbound:
            if mapping.map_id == map_id:
                return mapping
        return None

    def stats(self) -> dict[str, Any]:
        """Snapshot for sensors and diagnostics."""
        last = self.receiver.last_packet_time
        receiving = bool(
            self.receive_enabled
            and last is not None
            and (time.time() - last) < _RECEIVE_STALE_S
        )
        return {
            "receive_enabled": self.receive_enabled,
            "send_enabled": self.send_enabled,
            "receiving": receiving,
            "packets_received": self.receiver.packets_received,
            "last_packet_time": last,
            "active_universes": sorted(self.receiver.active_universes),
            "packets_per_universe": dict(self.receiver.packets_per_universe),
            "inbound_count": len(self.inbound),
            "outbound_count": len(self.outbound),
            "listener_count": self.listeners.count,
            "listener_universes": sorted(self.listeners.universes),
            "bind_ip": self.entry.data.get(CONF_BIND_IP) or "",
            "source_name": self.entry.data.get(CONF_SOURCE_NAME) or DEFAULT_SOURCE_NAME,
            "priority": self.entry.data.get(CONF_PRIORITY, DEFAULT_PRIORITY),
        }

    async def _async_stats(self) -> dict[str, Any]:
        return self.stats()


def _optional_ip(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _turn_on_payload(
    hass: HomeAssistant,
    entity_id: str,
    command: ColorCommand,
    transition: float,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        ATTR_ENTITY_ID: entity_id,
        "transition": transition,
    }
    modes = _supported_modes(hass, entity_id)
    red, green, blue = command.rgb8
    brightness = command.ha_brightness
    if modes & RGB_CAPABLE_HA_MODES:
        payload[ATTR_RGB_COLOR] = [red, green, blue]
        payload[ATTR_BRIGHTNESS] = brightness
        return payload
    if modes & COLOR_TEMP_HA_MODES:
        payload[ATTR_BRIGHTNESS] = brightness
        payload[ATTR_COLOR_TEMP_KELVIN] = command.kelvin
        return payload
    if not modes or modes & BRIGHTNESS_HA_MODES:
        payload[ATTR_BRIGHTNESS] = brightness
        return payload
    return payload


def _supported_modes(hass: HomeAssistant, entity_id: str) -> set[str]:
    state = hass.states.get(entity_id)
    if state is None:
        return set()
    raw = state.attributes.get("supported_color_modes") or []
    return {str(mode).lower() for mode in raw if mode}
