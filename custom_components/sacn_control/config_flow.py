"""Config and options flows for sACN Control."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector
import voluptuous as vol

from .const import (
    CHANNEL_MAX,
    CHANNEL_MIN,
    CHANNEL_MODE_LABELS,
    CONF_BIND_IP,
    CONF_BRIGHTNESS,
    CONF_CHANNEL_MODE,
    CONF_ENTITY_ID,
    CONF_HA_UPDATE_HZ,
    CONF_INBOUND_MAPS,
    CONF_MAP_ID,
    CONF_MAP_NAME,
    CONF_OUTBOUND_MAPS,
    CONF_PRIORITY,
    CONF_RECEIVE_ENABLED,
    CONF_SEND_ENABLED,
    CONF_SOURCE_NAME,
    CONF_START_CHANNEL,
    CONF_TRANSITION,
    CONF_UNIVERSE,
    CONF_WHITE_BLEND,
    DEFAULT_HA_UPDATE_HZ,
    DEFAULT_NAME,
    DEFAULT_PRIORITY,
    DEFAULT_SOURCE_NAME,
    DEFAULT_TRANSITION,
    DEFAULT_WHITE_BLEND,
    DOMAIN,
    PRIORITY_MAX,
    PRIORITY_MIN,
    SOURCE_NAME_MAX,
    UNIVERSE_MAX,
    UNIVERSE_MIN,
    ChannelMode,
)
from .models import (
    InboundMap,
    OutboundMap,
    mapping_label,
    parse_inbound_maps,
    parse_outbound_maps,
)
from .receiver import local_ipv4_addresses

_MODE_OPTIONS = [
    selector.SelectOptionDict(value=mode.value, label=CHANNEL_MODE_LABELS[mode])
    for mode in ChannelMode
]


def _bind_options() -> list[selector.SelectOptionDict]:
    options = [selector.SelectOptionDict(value="", label="All interfaces")]
    for ip in local_ipv4_addresses():
        options.append(selector.SelectOptionDict(value=ip, label=ip))
    return options


def _settings_schema(data: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Optional(
                CONF_SOURCE_NAME,
                default=data.get(CONF_SOURCE_NAME, DEFAULT_SOURCE_NAME),
            ): selector.TextSelector(),
            vol.Optional(
                CONF_PRIORITY,
                default=data.get(CONF_PRIORITY, DEFAULT_PRIORITY),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=PRIORITY_MIN, max=PRIORITY_MAX, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Optional(
                CONF_BIND_IP,
                default=data.get(CONF_BIND_IP, ""),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_bind_options(),
                    custom_value=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(
                CONF_RECEIVE_ENABLED,
                default=data.get(CONF_RECEIVE_ENABLED, True),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_SEND_ENABLED,
                default=data.get(CONF_SEND_ENABLED, True),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_HA_UPDATE_HZ,
                default=data.get(CONF_HA_UPDATE_HZ, DEFAULT_HA_UPDATE_HZ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=40, mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional(
                CONF_TRANSITION,
                default=data.get(CONF_TRANSITION, DEFAULT_TRANSITION),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=5, step=0.01, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Optional(
                CONF_WHITE_BLEND,
                default=data.get(CONF_WHITE_BLEND, DEFAULT_WHITE_BLEND),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=1, step=0.05, mode=selector.NumberSelectorMode.BOX
                )
            ),
        }
    )


def _normalize_settings(user_input: dict[str, Any]) -> dict[str, Any]:
    source = str(user_input.get(CONF_SOURCE_NAME) or DEFAULT_SOURCE_NAME).strip()
    return {
        CONF_SOURCE_NAME: source[:SOURCE_NAME_MAX] or DEFAULT_SOURCE_NAME,
        CONF_PRIORITY: int(user_input.get(CONF_PRIORITY, DEFAULT_PRIORITY)),
        CONF_BIND_IP: str(user_input.get(CONF_BIND_IP) or "").strip(),
        CONF_RECEIVE_ENABLED: bool(user_input.get(CONF_RECEIVE_ENABLED, True)),
        CONF_SEND_ENABLED: bool(user_input.get(CONF_SEND_ENABLED, True)),
        CONF_HA_UPDATE_HZ: int(user_input.get(CONF_HA_UPDATE_HZ, DEFAULT_HA_UPDATE_HZ)),
        CONF_TRANSITION: float(user_input.get(CONF_TRANSITION, DEFAULT_TRANSITION)),
        CONF_WHITE_BLEND: float(user_input.get(CONF_WHITE_BLEND, DEFAULT_WHITE_BLEND)),
    }


class SacnControlConfigFlow(ConfigFlow, domain=DOMAIN):
    """Initial setup flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect network settings and create the single config entry."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            return self.async_create_entry(title=DEFAULT_NAME, data=_normalize_settings(user_input))
        return self.async_show_form(step_id="user", data_schema=_settings_schema({}))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> SacnControlOptionsFlow:
        """Return the options flow."""
        return SacnControlOptionsFlow(config_entry)


class SacnControlOptionsFlow(OptionsFlow):
    """Add, remove, and retune mappings after setup."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry

    def _options(self) -> dict[str, Any]:
        return dict(self._config_entry.options)

    def _inbound(self) -> list[InboundMap]:
        return parse_inbound_maps(self._options().get(CONF_INBOUND_MAPS))

    def _outbound(self) -> list[OutboundMap]:
        return parse_outbound_maps(self._options().get(CONF_OUTBOUND_MAPS))

    async def async_step_init(
        self, _user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the options menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["add_inbound", "add_outbound", "remove_map", "settings"],
        )

    async def async_step_add_inbound(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Patch an existing Home Assistant light to an sACN address."""
        if user_input is not None:
            mapping = InboundMap.from_dict(user_input)
            inbound = [item for item in self._inbound() if item.map_id != mapping.map_id]
            inbound.append(mapping)
            options = self._options()
            options[CONF_INBOUND_MAPS] = [item.to_dict() for item in inbound]
            return self.async_create_entry(title="", data=options)
        schema = vol.Schema(
            {
                vol.Required(CONF_ENTITY_ID): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="light")
                ),
                vol.Optional(CONF_MAP_NAME): selector.TextSelector(),
                vol.Required(CONF_UNIVERSE, default=1): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=UNIVERSE_MIN, max=UNIVERSE_MAX, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Required(CONF_START_CHANNEL, default=1): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=CHANNEL_MIN, max=CHANNEL_MAX, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Required(
                    CONF_CHANNEL_MODE, default=ChannelMode.RGB_8.value
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=_MODE_OPTIONS)
                ),
                vol.Optional(CONF_BRIGHTNESS, default=1.0): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=1, step=0.05, mode=selector.NumberSelectorMode.SLIDER
                    )
                ),
            }
        )
        return self.async_show_form(step_id="add_inbound", data_schema=schema)

    async def async_step_add_outbound(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create a Home Assistant light that transmits sACN."""
        if user_input is not None:
            mapping = OutboundMap.from_dict(user_input)
            outbound = [item for item in self._outbound() if item.map_id != mapping.map_id]
            outbound.append(mapping)
            options = self._options()
            options[CONF_OUTBOUND_MAPS] = [item.to_dict() for item in outbound]
            return self.async_create_entry(title="", data=options)
        schema = vol.Schema(
            {
                vol.Required(CONF_MAP_NAME): selector.TextSelector(),
                vol.Required(CONF_UNIVERSE, default=1): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=UNIVERSE_MIN, max=UNIVERSE_MAX, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Required(CONF_START_CHANNEL, default=1): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=CHANNEL_MIN, max=CHANNEL_MAX, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Required(
                    CONF_CHANNEL_MODE, default=ChannelMode.RGB_8.value
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=_MODE_OPTIONS)
                ),
            }
        )
        return self.async_show_form(step_id="add_outbound", data_schema=schema)

    async def async_step_remove_map(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Remove an inbound or outbound mapping."""
        inbound = self._inbound()
        outbound = self._outbound()
        choices = {
            item.map_id: f"Inbound · {mapping_label(item)}" for item in inbound
        }
        choices.update(
            {item.map_id: f"Outbound · {mapping_label(item)}" for item in outbound}
        )
        if not choices:
            return self.async_abort(reason="no_maps")
        if user_input is not None:
            map_id = user_input[CONF_MAP_ID]
            options = self._options()
            options[CONF_INBOUND_MAPS] = [
                item.to_dict() for item in inbound if item.map_id != map_id
            ]
            options[CONF_OUTBOUND_MAPS] = [
                item.to_dict() for item in outbound if item.map_id != map_id
            ]
            return self.async_create_entry(title="", data=options)
        schema = vol.Schema(
            {
                vol.Required(CONF_MAP_ID): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value=key, label=label)
                            for key, label in choices.items()
                        ]
                    )
                )
            }
        )
        return self.async_show_form(step_id="remove_map", data_schema=schema)

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Update network and rate settings stored on the config entry."""
        if user_input is not None:
            self.hass.config_entries.async_update_entry(
                self._config_entry, data=_normalize_settings(user_input)
            )
            return self.async_create_entry(title="", data=self._options())
        return self.async_show_form(
            step_id="settings", data_schema=_settings_schema(dict(self._config_entry.data))
        )
