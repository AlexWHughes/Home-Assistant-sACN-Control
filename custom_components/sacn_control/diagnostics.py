"""Diagnostics dump for sACN Control."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from . import get_bridge


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    bridge = get_bridge(hass, entry.entry_id)
    return {
        "data": dict(entry.data),
        "options": dict(entry.options),
        "stats": bridge.stats(),
    }
