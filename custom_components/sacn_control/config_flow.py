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
    CONF_ENTITY_IDS,
    CONF_HA_UPDATE_HZ,
    CONF_INBOUND_MAPS,
    CONF_MAP_ID,
    CONF_MAP_NAME,
    CONF_NEXT_STEP,
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
    NoChannelCapacityError,
    OutboundMap,
    assign_inbound_maps,
    mapping_label,
    parse_inbound_maps,
    parse_outbound_maps,
)
from .receiver import local_ipv4_addresses

_MODE_OPTIONS = [
    selector.SelectOptionDict(value=mode.value, label=CHANNEL_MODE_LABELS[mode])
    for mode in ChannelMode
]

_NEXT_OPTIONS = [
    selector.SelectOptionDict(
        value="inbound",
        label="Select Home Assistant lights to control from sACN",
    ),
    selector.SelectOptionDict(
        value="outbound",
        label="Add an sACN fixture light (Home Assistant → sACN)",
    ),
    selector.SelectOptionDict(value="remove", label="Remove a mapping"),
    selector.SelectOptionDict(value="settings", label="Network and rate settings"),
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


def _inbound_schema(selected: list[str]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Optional(CONF_ENTITY_IDS, default=selected): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="light", multiple=True)
            ),
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
            ): selector.SelectSelector(selector.SelectSelectorConfig(options=_MODE_OPTIONS)),
            vol.Optional(CONF_BRIGHTNESS, default=1.0): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=1, step=0.05, mode=selector.NumberSelectorMode.SLIDER
                )
            ),
        }
    )


def _outbound_schema() -> vol.Schema:
    return vol.Schema(
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
            ): selector.SelectSelector(selector.SelectSelectorConfig(options=_MODE_OPTIONS)),
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


def _entity_ids(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if item]
    return []


def _save_inbound(
    user_input: dict[str, Any], existing: list[InboundMap]
) -> list[InboundMap]:
    return assign_inbound_maps(
        _entity_ids(user_input.get(CONF_ENTITY_IDS)),
        existing,
        universe=int(user_input.get(CONF_UNIVERSE, 1)),
        start_channel=int(user_input.get(CONF_START_CHANNEL, 1)),
        channel_mode=user_input.get(CONF_CHANNEL_MODE, ChannelMode.RGB_8),
        brightness=float(user_input.get(CONF_BRIGHTNESS, 1.0)),
    )


class SacnControlConfigFlow(ConfigFlow, domain=DOMAIN):
    """Initial setup: network settings, then pick lights and fixtures."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect network settings, then continue to light mapping."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            self._settings = _normalize_settings(user_input)
            self._inbound = []
            self._outbound = []
            return await self.async_step_inbound()
        return self.async_show_form(step_id="user", data_schema=_settings_schema({}))

    async def async_step_inbound(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select which existing Home Assistant lights sACN should drive."""
        if user_input is not None:
            try:
                self._inbound = _save_inbound(user_input, getattr(self, "_inbound", []))
            except NoChannelCapacityError:
                return self.async_show_form(
                    step_id="inbound",
                    data_schema=_inbound_schema(_entity_ids(user_input.get(CONF_ENTITY_IDS))),
                    errors={CONF_START_CHANNEL: "no_channel_capacity"},
                )
            return await self.async_step_outbound()
        return self.async_show_form(step_id="inbound", data_schema=_inbound_schema([]))

    async def async_step_outbound(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Optionally create a Home Assistant light that transmits sACN."""
        if user_input is not None:
            name = str(user_input.get(CONF_MAP_NAME) or "").strip()
            if name:
                self._outbound.append(OutboundMap.from_dict(user_input))
            return self.async_create_entry(
                title=DEFAULT_NAME,
                data=self._settings,
                options={
                    CONF_INBOUND_MAPS: [item.to_dict() for item in self._inbound],
                    CONF_OUTBOUND_MAPS: [item.to_dict() for item in self._outbound],
                },
            )
        return self.async_show_form(step_id="outbound", data_schema=_optional_outbound_schema())

    @staticmethod
    @callback
    def async_get_options_flow(
        _config_entry: ConfigEntry | None = None,
    ) -> SacnControlOptionsFlow:
        """Return the options flow. HA injects config_entry on the handler."""
        return SacnControlOptionsFlow()


def _optional_outbound_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Optional(CONF_MAP_NAME, default=""): selector.TextSelector(),
            vol.Optional(CONF_UNIVERSE, default=1): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=UNIVERSE_MIN, max=UNIVERSE_MAX, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Optional(CONF_START_CHANNEL, default=1): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=CHANNEL_MIN, max=CHANNEL_MAX, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Optional(
                CONF_CHANNEL_MODE, default=ChannelMode.RGB_8.value
            ): selector.SelectSelector(selector.SelectSelectorConfig(options=_MODE_OPTIONS)),
        }
    )


class SacnControlOptionsFlow(OptionsFlow):
    """Add, remove, and retune mappings after setup."""

    def _options(self) -> dict[str, Any]:
        return dict(self.config_entry.options)

    def _inbound(self) -> list[InboundMap]:
        return parse_inbound_maps(self._options().get(CONF_INBOUND_MAPS))

    def _outbound(self) -> list[OutboundMap]:
        return parse_outbound_maps(self._options().get(CONF_OUTBOUND_MAPS))

    def _write(
        self,
        inbound: list[InboundMap] | None = None,
        outbound: list[OutboundMap] | None = None,
    ) -> ConfigFlowResult:
        options = self._options()
        if inbound is not None:
            options[CONF_INBOUND_MAPS] = [item.to_dict() for item in inbound]
        if outbound is not None:
            options[CONF_OUTBOUND_MAPS] = [item.to_dict() for item in outbound]
        return self.async_create_entry(title="", data=options)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose what to configure. Form-based so it works without menu support."""
        if user_input is not None:
            next_step = user_input.get(CONF_NEXT_STEP, "inbound")
            if next_step == "outbound":
                return await self.async_step_outbound()
            if next_step == "remove":
                return await self.async_step_remove()
            if next_step == "settings":
                return await self.async_step_settings()
            return await self.async_step_inbound()
        inbound = self._inbound()
        outbound = self._outbound()
        description = (
            f"{len(inbound)} Home Assistant light(s) receive sACN. "
            f"{len(outbound)} sACN fixture(s) are exposed as lights."
        )
        schema = vol.Schema(
            {
                vol.Required(CONF_NEXT_STEP, default="inbound"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=_NEXT_OPTIONS)
                )
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            description_placeholders={"summary": description},
        )

    async def async_step_inbound(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select which existing Home Assistant lights sACN should drive."""
        selected = [item.entity_id for item in self._inbound()]
        if user_input is not None:
            try:
                inbound = _save_inbound(user_input, self._inbound())
            except NoChannelCapacityError:
                return self.async_show_form(
                    step_id="inbound",
                    data_schema=_inbound_schema(_entity_ids(user_input.get(CONF_ENTITY_IDS))),
                    errors={CONF_START_CHANNEL: "no_channel_capacity"},
                )
            return self._write(inbound=inbound)
        return self.async_show_form(step_id="inbound", data_schema=_inbound_schema(selected))

    async def async_step_outbound(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create a Home Assistant light that transmits sACN."""
        if user_input is not None:
            mapping = OutboundMap.from_dict(user_input)
            outbound = [item for item in self._outbound() if item.map_id != mapping.map_id]
            outbound.append(mapping)
            return self._write(outbound=outbound)
        return self.async_show_form(step_id="outbound", data_schema=_outbound_schema())

    async def async_step_remove(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Remove an inbound or outbound mapping."""
        inbound = self._inbound()
        outbound = self._outbound()
        choices = {item.map_id: f"sACN → HA · {mapping_label(item)}" for item in inbound}
        choices.update(
            {item.map_id: f"HA → sACN · {mapping_label(item)}" for item in outbound}
        )
        if not choices:
            return self.async_abort(reason="no_maps")
        if user_input is not None:
            map_id = user_input[CONF_MAP_ID]
            return self._write(
                inbound=[item for item in inbound if item.map_id != map_id],
                outbound=[item for item in outbound if item.map_id != map_id],
            )
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
        return self.async_show_form(step_id="remove", data_schema=schema)

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Update network and rate settings stored on the config entry."""
        if user_input is not None:
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=_normalize_settings(user_input)
            )
            return self.async_create_entry(title="", data=self._options())
        return self.async_show_form(
            step_id="settings", data_schema=_settings_schema(dict(self.config_entry.data))
        )
