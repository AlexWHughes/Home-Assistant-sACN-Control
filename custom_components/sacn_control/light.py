"""Outbound sACN fixtures exposed as Home Assistant lights."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Never

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_EFFECT,
    ATTR_HS_COLOR,
    ATTR_RGB_COLOR,
    ATTR_RGBW_COLOR,
    DOMAIN as LIGHT_DOMAIN,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval

from . import get_bridge
from .bridge import SacnBridge
from .const import (
    ATTR_CHANNEL_MODE,
    ATTR_PIXEL_COUNT,
    ATTR_PIXEL_LAYOUT,
    ATTR_START_CHANNEL,
    ATTR_UNIVERSE,
    CHANNEL_MODE_LABELS,
    CHANNEL_MODE_SPEC,
    DEFAULT_KELVIN,
    DOMAIN,
    EFFECT_INTERVAL_S,
    EFFECT_OFF,
    KELVIN_MAX,
    KELVIN_MIN,
    MANUFACTURER,
    PIXEL_LAYOUT_LABELS,
    ChannelKind,
    ChannelMode,
)
from .dmx import ColorCommand, command_from_ha
from .models import OutboundMap
from .pixels import EFFECT_LIST, render_effect


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up outbound fixture lights."""
    bridge = get_bridge(hass, entry.entry_id)
    keep_unique_ids = {f"{DOMAIN}_fixture_{mapping.map_id}" for mapping in bridge.outbound}
    entity_reg = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(entity_reg, entry.entry_id):
        if entity.domain == LIGHT_DOMAIN and entity.unique_id not in keep_unique_ids:
            entity_reg.async_remove(entity.entity_id)
    keep_devices = {(DOMAIN, entry.entry_id)} | {
        (DOMAIN, mapping.map_id) for mapping in bridge.outbound
    }
    device_reg = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(device_reg, entry.entry_id):
        if not (device.identifiers & keep_devices):
            device_reg.async_remove_device(device.id)
    async_add_entities(
        [SacnFixtureLight(bridge, mapping) for mapping in bridge.outbound],
        True,
    )


def _supported_modes(mode: ChannelMode) -> set[ColorMode]:
    kind, _bits, _fine = CHANNEL_MODE_SPEC[mode]
    if kind is ChannelKind.RGBW:
        return {ColorMode.RGBW}
    if kind in (ChannelKind.HSBK, ChannelKind.HSBK_INTENSITY):
        return {ColorMode.HS, ColorMode.COLOR_TEMP}
    if kind in (ChannelKind.RGB, ChannelKind.RGB_INTENSITY):
        return {ColorMode.RGB}
    unreachable: Never = kind
    raise ValueError(f"Unhandled channel kind: {unreachable}")


class SacnFixtureLight(LightEntity):
    """A software fixture that writes DMX onto an sACN universe."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_icon = "mdi:spotlight-beam"
    _attr_should_poll = False
    _attr_supported_features = LightEntityFeature.TRANSITION | LightEntityFeature.EFFECT
    _attr_effect_list = list(EFFECT_LIST)
    _attr_min_color_temp_kelvin = KELVIN_MIN
    _attr_max_color_temp_kelvin = KELVIN_MAX

    def __init__(self, bridge: SacnBridge, mapping: OutboundMap) -> None:
        self._bridge = bridge
        self._mapping = mapping
        self._command = ColorCommand(
            red=0.0,
            green=0.0,
            blue=0.0,
            white=0.0,
            hue=0.0,
            saturation=0.0,
            brightness=0.0,
            kelvin=DEFAULT_KELVIN,
            intensity=0.0,
        )
        self._color_mode = next(iter(_supported_modes(mapping.channel_mode)))
        self._effect = EFFECT_OFF
        self._effect_frame = 0
        self._unsub_effect = None
        self._attr_unique_id = f"{DOMAIN}_fixture_{mapping.map_id}"
        self._attr_supported_color_modes = _supported_modes(mapping.channel_mode)
        model = CHANNEL_MODE_LABELS[mapping.channel_mode]
        if mapping.pixel_count > 1:
            model = f"{model} · {mapping.pixel_count} px"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, mapping.map_id)},
            name=mapping.name,
            manufacturer=MANUFACTURER,
            model=model,
            via_device=(DOMAIN, bridge.entry.entry_id),
        )

    @property
    def is_on(self) -> bool:
        """Return true if the fixture is emitting."""
        return not self._command.is_black

    @property
    def brightness(self) -> int | None:
        """Return brightness 0..255."""
        if self._command.is_black:
            return None
        return max(1, int(round(self._command.brightness * 255)))

    @property
    def color_mode(self) -> ColorMode:
        """Return the active color mode."""
        return self._color_mode

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        """Return RGB chromaticity."""
        return (
            int(round(self._command.red * 255)),
            int(round(self._command.green * 255)),
            int(round(self._command.blue * 255)),
        )

    @property
    def rgbw_color(self) -> tuple[int, int, int, int] | None:
        """Return RGBW chromaticity."""
        return (
            int(round(self._command.red * 255)),
            int(round(self._command.green * 255)),
            int(round(self._command.blue * 255)),
            int(round(self._command.white * 255)),
        )

    @property
    def hs_color(self) -> tuple[float, float] | None:
        """Return HS chromaticity."""
        return (self._command.hue * 360.0, self._command.saturation * 100.0)

    @property
    def color_temp_kelvin(self) -> int | None:
        """Return colour temperature."""
        return self._command.kelvin

    @property
    def effect(self) -> str | None:
        """Return the current effect."""
        return self._effect

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the DMX patch on the entity."""
        return {
            ATTR_UNIVERSE: self._mapping.universe,
            ATTR_START_CHANNEL: self._mapping.start_channel,
            ATTR_CHANNEL_MODE: CHANNEL_MODE_LABELS[self._mapping.channel_mode],
            ATTR_PIXEL_COUNT: self._mapping.pixel_count,
            ATTR_PIXEL_LAYOUT: PIXEL_LAYOUT_LABELS[self._mapping.pixel_layout],
            "end_channel": self._mapping.end_channel,
            "map_id": self._mapping.map_id,
        }

    async def async_will_remove_from_hass(self) -> None:
        """Stop an effect timer when the entity is unloaded."""
        self._stop_effect()
        await super().async_will_remove_from_hass()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Write colour onto the outbound universe."""
        rgb = kwargs.get(ATTR_RGB_COLOR)
        rgbw = kwargs.get(ATTR_RGBW_COLOR)
        hs = kwargs.get(ATTR_HS_COLOR)
        brightness = kwargs.get(ATTR_BRIGHTNESS)
        kelvin = kwargs.get(ATTR_COLOR_TEMP_KELVIN)
        if ATTR_EFFECT in kwargs:
            requested = str(kwargs.get(ATTR_EFFECT) or EFFECT_OFF)
            self._effect = requested if requested in EFFECT_LIST else EFFECT_OFF
            self._effect_frame = 0
        if brightness is None and not self._command.is_black:
            brightness = max(1, int(round(self._command.brightness * 255)))
        if rgb is None and rgbw is None and hs is None and kelvin is None:
            if self._color_mode is ColorMode.RGBW:
                rgbw = self.rgbw_color
            elif self._color_mode is ColorMode.HS:
                hs = self.hs_color
            elif self._color_mode is ColorMode.COLOR_TEMP:
                kelvin = self._command.kelvin
            else:
                rgb = self.rgb_color
        if kelvin is not None:
            self._color_mode = (
                ColorMode.COLOR_TEMP
                if ColorMode.COLOR_TEMP in self._attr_supported_color_modes
                else self._color_mode
            )
        elif rgbw is not None:
            self._color_mode = ColorMode.RGBW
        elif hs is not None and ColorMode.HS in self._attr_supported_color_modes:
            self._color_mode = ColorMode.HS
        elif rgb is not None:
            self._color_mode = ColorMode.RGB
        self._command = command_from_ha(
            rgb=tuple(rgb) if rgb is not None else None,
            rgbw=tuple(rgbw) if rgbw is not None else None,
            hs=tuple(hs) if hs is not None else None,
            brightness=brightness if brightness is not None else 255,
            kelvin=int(kelvin) if kelvin is not None else self._command.kelvin,
            is_on=True,
        )
        if self._effect != EFFECT_OFF:
            self._start_effect()
            self._paint_effect()
        else:
            self._stop_effect()
            self._bridge.write_outbound(self._mapping, self._command)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Black out the fixture channels."""
        self._effect = EFFECT_OFF
        self._stop_effect()
        self._command = command_from_ha(is_on=False, kelvin=self._command.kelvin)
        self._bridge.write_outbound(self._mapping, self._command)
        self.async_write_ha_state()

    def _start_effect(self) -> None:
        if self._unsub_effect is not None:
            return
        self._unsub_effect = async_track_time_interval(
            self.hass,
            self._async_effect_tick,
            timedelta(seconds=EFFECT_INTERVAL_S),
        )

    def _stop_effect(self) -> None:
        if self._unsub_effect is not None:
            self._unsub_effect()
            self._unsub_effect = None

    async def _async_effect_tick(self, _now: Any = None) -> None:
        if self._effect == EFFECT_OFF or self._command.is_black:
            self._stop_effect()
            return
        self._effect_frame += 1
        self._paint_effect()

    def _paint_effect(self) -> None:
        cells = render_effect(
            self._effect,
            command=self._command,
            pixel_count=self._mapping.pixel_count,
            layout=self._mapping.pixel_layout,
            frame=self._effect_frame,
        )
        self._bridge.write_outbound_cells(self._mapping, cells)
