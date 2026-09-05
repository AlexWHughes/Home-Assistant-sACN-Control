"""Status sensors for the sACN Control bridge."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import get_bridge
from .const import DEFAULT_NAME, DOMAIN, MANUFACTURER


@dataclass(frozen=True, slots=True)
class SacnSensorDescription(SensorEntityDescription):
    """Sensor that reads a value from bridge stats."""

    value_fn: Callable[[dict[str, Any]], Any] = lambda _stats: None
    attrs_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None


SENSORS: tuple[SacnSensorDescription, ...] = (
    SacnSensorDescription(
        key="packets_received",
        translation_key="packets_received",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda stats: stats.get("packets_received", 0),
        attrs_fn=lambda stats: {"packets_per_universe": stats.get("packets_per_universe", {})},
    ),
    SacnSensorDescription(
        key="active_universes",
        translation_key="active_universes",
        value_fn=lambda stats: ",".join(str(item) for item in stats.get("active_universes", [])),
        attrs_fn=lambda stats: {
            "universes": stats.get("active_universes", []),
            "inbound_count": stats.get("inbound_count", 0),
            "outbound_count": stats.get("outbound_count", 0),
        },
    ),
    SacnSensorDescription(
        key="receiving",
        translation_key="receiving",
        value_fn=lambda stats: "receiving" if stats.get("receiving") else "idle",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up bridge sensors."""
    bridge = get_bridge(hass, entry.entry_id)
    device = DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=DEFAULT_NAME,
        manufacturer=MANUFACTURER,
        model="E1.31 bridge",
    )
    async_add_entities(
        [
            SacnStatusSensor(bridge.coordinator, entry.entry_id, device, description)
            for description in SENSORS
        ]
    )


class SacnStatusSensor(CoordinatorEntity, SensorEntity):
    """A diagnostic sensor backed by the bridge coordinator."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: Any,
        entry_id: str,
        device: DeviceInfo,
        description: SacnSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{DOMAIN}_{entry_id}_{description.key}"
        self._attr_device_info = device

    @property
    def native_value(self) -> Any:
        """Return the sensor value."""
        return self.entity_description.value_fn(self.coordinator.data or {})

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes when defined."""
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.coordinator.data or {})
