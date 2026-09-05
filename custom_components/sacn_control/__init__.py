"""sACN Control — bidirectional E1.31 bridge for Home Assistant."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType
import voluptuous as vol

from .bridge import SacnBridge
from .const import (
    CHANNEL_MAX,
    CHANNEL_MIN,
    CONF_BRIGHTNESS,
    CONF_CHANNEL_MODE,
    CONF_ENTITY_ID,
    CONF_INBOUND_MAPS,
    CONF_MAP_ID,
    CONF_MAP_NAME,
    CONF_OUTBOUND_MAPS,
    CONF_PIXEL_COUNT,
    CONF_PIXEL_LAYOUT,
    CONF_START_CHANNEL,
    CONF_UNIVERSE,
    DOMAIN,
    PLATFORMS,
    PIXEL_COUNT_MAX,
    PIXEL_COUNT_MIN,
    UNIVERSE_MAX,
    UNIVERSE_MIN,
    ChannelMode,
    PixelLayout,
)
from .models import (
    InboundMap,
    OutboundMap,
    parse_inbound_maps,
    parse_outbound_maps,
    remove_mapping_by_token,
)

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, _config: ConfigType) -> bool:
    """Set up the integration domain and register services."""
    hass.data.setdefault(DOMAIN, {})
    _register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up sACN Control from a config entry."""
    bridge = SacnBridge(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = bridge
    await bridge.async_start()
    await hass.config_entries.async_forward_entry_setups(
        entry, [Platform(platform) for platform in PLATFORMS]
    )
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(
        entry, [Platform(platform) for platform in PLATFORMS]
    )
    bridge: SacnBridge | None = hass.data[DOMAIN].pop(entry.entry_id, None)
    if bridge is not None:
        await bridge.async_stop()
    return unload_ok


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _bridge(hass: HomeAssistant) -> SacnBridge | None:
    entries = hass.data.get(DOMAIN) or {}
    if not entries:
        return None
    return next(iter(entries.values()))


def _register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, "add_inbound"):
        return

    async def handle_add_inbound(call: ServiceCall) -> None:
        bridge = _bridge(hass)
        if bridge is None:
            return
        mapping = InboundMap.from_dict(dict(call.data))
        inbound = parse_inbound_maps(bridge.entry.options.get(CONF_INBOUND_MAPS))
        inbound = [item for item in inbound if item.map_id != mapping.map_id]
        inbound.append(mapping)
        _update_options(hass, bridge, inbound=inbound)

    async def handle_add_outbound(call: ServiceCall) -> None:
        bridge = _bridge(hass)
        if bridge is None:
            return
        mapping = OutboundMap.from_dict(dict(call.data))
        outbound = parse_outbound_maps(bridge.entry.options.get(CONF_OUTBOUND_MAPS))
        outbound = [item for item in outbound if item.map_id != mapping.map_id]
        outbound.append(mapping)
        _update_options(hass, bridge, outbound=outbound)

    async def handle_remove_map(call: ServiceCall) -> None:
        bridge = _bridge(hass)
        if bridge is None:
            return
        token = str(call.data.get(CONF_MAP_ID) or "")
        inbound = parse_inbound_maps(bridge.entry.options.get(CONF_INBOUND_MAPS))
        outbound = parse_outbound_maps(bridge.entry.options.get(CONF_OUTBOUND_MAPS))
        removed = remove_mapping_by_token(token, inbound, outbound)
        if removed is None:
            return
        inbound, outbound = removed
        _update_options(hass, bridge, inbound=inbound, outbound=outbound)

    hass.services.async_register(
        DOMAIN,
        "add_inbound",
        handle_add_inbound,
        schema=vol.Schema(
            {
                vol.Required(CONF_ENTITY_ID): cv.entity_id,
                vol.Required(CONF_UNIVERSE): vol.All(
                    vol.Coerce(int), vol.Range(min=UNIVERSE_MIN, max=UNIVERSE_MAX)
                ),
                vol.Required(CONF_START_CHANNEL): vol.All(
                    vol.Coerce(int), vol.Range(min=CHANNEL_MIN, max=CHANNEL_MAX)
                ),
                vol.Optional(CONF_CHANNEL_MODE, default=ChannelMode.RGB_8): cv.string,
                vol.Optional(CONF_BRIGHTNESS, default=1.0): vol.All(
                    vol.Coerce(float), vol.Range(min=0.0, max=1.0)
                ),
                vol.Optional(CONF_MAP_NAME): cv.string,
                vol.Optional(CONF_MAP_ID): cv.string,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        "add_outbound",
        handle_add_outbound,
        schema=vol.Schema(
            {
                vol.Required(CONF_MAP_NAME): cv.string,
                vol.Required(CONF_UNIVERSE): vol.All(
                    vol.Coerce(int), vol.Range(min=UNIVERSE_MIN, max=UNIVERSE_MAX)
                ),
                vol.Required(CONF_START_CHANNEL): vol.All(
                    vol.Coerce(int), vol.Range(min=CHANNEL_MIN, max=CHANNEL_MAX)
                ),
                vol.Optional(CONF_CHANNEL_MODE, default=ChannelMode.RGB_8): cv.string,
                vol.Optional(CONF_PIXEL_COUNT, default=1): vol.All(
                    vol.Coerce(int), vol.Range(min=PIXEL_COUNT_MIN, max=PIXEL_COUNT_MAX)
                ),
                vol.Optional(CONF_PIXEL_LAYOUT, default=PixelLayout.WHOLE): cv.string,
                vol.Optional(CONF_MAP_ID): cv.string,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        "remove_map",
        handle_remove_map,
        schema=vol.Schema({vol.Required(CONF_MAP_ID): cv.string}),
    )


def _update_options(
    hass: HomeAssistant,
    bridge: SacnBridge,
    inbound: list[InboundMap] | None = None,
    outbound: list[OutboundMap] | None = None,
) -> None:
    current = dict(bridge.entry.options)
    if inbound is not None:
        current[CONF_INBOUND_MAPS] = [item.to_dict() for item in inbound]
    if outbound is not None:
        current[CONF_OUTBOUND_MAPS] = [item.to_dict() for item in outbound]
    hass.config_entries.async_update_entry(bridge.entry, options=current)


def get_bridge(hass: HomeAssistant, entry_id: str) -> SacnBridge:
    """Return the running bridge for a config entry."""
    return hass.data[DOMAIN][entry_id]


async def async_migrate_entry(_hass: HomeAssistant, _entry: ConfigEntry) -> bool:
    """Migrate old entry versions (none yet)."""
    return True
