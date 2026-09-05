"""Enable/disable inbound reception and outbound transmission."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import get_bridge
from .bridge import SacnBridge
from .const import DEFAULT_NAME, DOMAIN, MANUFACTURER


async def _unset_transport(_bridge: SacnBridge, _enabled: bool) -> None:
    raise NotImplementedError


@dataclass(frozen=True, slots=True)
class SacnSwitchDescription(SwitchEntityDescription):
    """Switch that toggles a bridge transport."""

    is_on_fn: Callable[[SacnBridge], bool] = lambda _bridge: False
    set_fn: Callable[[SacnBridge, bool], Awaitable[None]] = _unset_transport


async def _set_receive(bridge: SacnBridge, enabled: bool) -> None:
    await bridge.async_set_receive(enabled)


async def _set_send(bridge: SacnBridge, enabled: bool) -> None:
    await bridge.async_set_send(enabled)


SWITCHES: tuple[SacnSwitchDescription, ...] = (
    SacnSwitchDescription(
        key="receive",
        translation_key="receive",
        is_on_fn=lambda bridge: bridge.receive_enabled,
        set_fn=_set_receive,
    ),
    SacnSwitchDescription(
        key="send",
        translation_key="send",
        is_on_fn=lambda bridge: bridge.send_enabled,
        set_fn=_set_send,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up receive/send switches."""
    bridge = get_bridge(hass, entry.entry_id)
    device = DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=DEFAULT_NAME,
        manufacturer=MANUFACTURER,
        model="E1.31 bridge",
    )
    async_add_entities(
        [
            SacnTransportSwitch(bridge, entry.entry_id, device, description)
            for description in SWITCHES
        ]
    )


class SacnTransportSwitch(CoordinatorEntity, SwitchEntity):
    """Switch that starts or stops one sACN transport."""

    _attr_has_entity_name = True
    entity_description: SacnSwitchDescription

    def __init__(
        self,
        bridge: SacnBridge,
        entry_id: str,
        device: DeviceInfo,
        description: SacnSwitchDescription,
    ) -> None:
        super().__init__(bridge.coordinator)
        self._bridge = bridge
        self.entity_description = description
        self._attr_unique_id = f"{DOMAIN}_{entry_id}_{description.key}"
        self._attr_device_info = device

    @property
    def is_on(self) -> bool:
        """Return whether this transport is enabled."""
        return self.entity_description.is_on_fn(self._bridge)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the transport."""
        await self.entity_description.set_fn(self._bridge, True)
        await self.coordinator.async_request_refresh()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the transport."""
        await self.entity_description.set_fn(self._bridge, False)
        await self.coordinator.async_request_refresh()
        self.async_write_ha_state()
