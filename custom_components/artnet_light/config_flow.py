"""Config flow and options flow for Art-Net Light."""

from __future__ import annotations

import ipaddress
from typing import Any
import uuid

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .const import (
    CCT_MODE_CW,
    CCT_MODES,
    CONF_ADVANCED,
    CONF_BITS,
    CONF_CCT_MODE,
    CONF_CHANNEL_ORDER,
    CONF_DEFAULT_TRANSITION,
    CONF_DELETE,
    CONF_FIXTURE_TYPE,
    CONF_FIXTURES,
    CONF_FPS,
    CONF_KEEPALIVE,
    CONF_MAC,
    CONF_MAX_KELVIN,
    CONF_MAX_OUTPUT,
    CONF_MIN_KELVIN,
    CONF_MIN_OUTPUT,
    CONF_SEND_MODE,
    CONF_START_CHANNEL,
    CONF_UNIVERSE,
    CONF_UNIVERSES,
    DEFAULT_MAX_KELVIN,
    DEFAULT_MIN_KELVIN,
    DEFAULT_NAME,
    DEFAULT_OPTIONS,
    DEFAULT_PORT,
    DOMAIN,
    FIXTURE_TYPES,
    SEND_MODES,
    TYPE_RGB,
)
from .discovery import async_scan
from .fixture import Fixture, find_overlap, normalize_order

CONF_DEVICE = "device"
MANUAL = "manual"
CONF_FIXTURE = "fixture"


def _number(minimum: float, maximum: float, step: float = 1, unit: str | None = None) -> NumberSelector:
    config = NumberSelectorConfig(min=minimum, max=maximum, step=step, mode=NumberSelectorMode.BOX)
    if unit:  # the selector schema rejects unit_of_measurement=None
        config["unit_of_measurement"] = unit
    return NumberSelector(config)


def _select(options: list[str], translation_key: str) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=options, translation_key=translation_key, mode=SelectSelectorMode.DROPDOWN
        )
    )


def _valid_host(host: str) -> bool:
    try:
        ipaddress.IPv4Address(host)
    except ValueError:
        return False
    return True


class ArtNetConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add an Art-Net node."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovered: dict[str, dict[str, Any]] = {}
        self._node: dict[str, Any] | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> ArtNetOptionsFlow:
        return ArtNetOptionsFlow()

    # ------------------------------------------------------------ user / scan

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            choice = user_input[CONF_DEVICE]
            if choice == MANUAL or choice not in self._discovered:
                return await self.async_step_manual()
            node = self._discovered[choice]
            await self.async_set_unique_id(node["unique_id"])
            self._abort_if_unique_id_configured()
            return self._create_from_node(node)

        configured_ids = self._async_current_ids(include_ignore=False)
        configured_hosts = {e.data.get(CONF_HOST) for e in self._async_current_entries()}
        self._discovered = {
            node.ip: node.as_dict()
            for node in await async_scan(self.hass)
            if node.unique_id not in configured_ids and node.ip not in configured_hosts
        }
        if not self._discovered:
            return await self.async_step_manual()

        options = [
            SelectOptionDict(value=ip, label=f"{node['short_name'] or node['long_name'] or ip} ({ip})")
            for ip, node in self._discovered.items()
        ]
        options.append(SelectOptionDict(value=MANUAL, label=MANUAL))
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICE): SelectSelector(
                        SelectSelectorConfig(
                            options=options, translation_key="device", mode=SelectSelectorMode.LIST
                        )
                    )
                }
            ),
            description_placeholders={"count": str(len(self._discovered))},
        )

    async def async_step_manual(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = int(user_input[CONF_PORT])
            if not _valid_host(host):
                errors[CONF_HOST] = "invalid_host"
            else:
                self._async_abort_entries_match({CONF_HOST: host, CONF_PORT: port})
                await self.async_set_unique_id(f"{host}:{port}")
                self._abort_if_unique_id_configured()
                name = user_input.get(CONF_NAME) or DEFAULT_NAME
                return self.async_create_entry(
                    title=f"{name} ({host})",
                    data={CONF_HOST: host, CONF_PORT: port, CONF_NAME: name, CONF_UNIVERSES: []},
                    options=DEFAULT_OPTIONS,
                )

        user_input = user_input or {}
        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=user_input.get(CONF_HOST, "192.168.1.200")): TextSelector(),
                    vol.Required(CONF_PORT, default=user_input.get(CONF_PORT, DEFAULT_PORT)): _number(1, 65535),
                    vol.Optional(CONF_NAME, default=user_input.get(CONF_NAME, DEFAULT_NAME)): TextSelector(),
                }
            ),
            errors=errors,
        )

    # -------------------------------------------------------------- discovery

    async def async_step_integration_discovery(self, discovery_info: dict[str, Any]) -> ConfigFlowResult:
        """A node was found by the background ArtPoll scan."""
        host = discovery_info["ip"]
        unique_id = discovery_info["unique_id"]
        if discovery_info.get("mac"):
            unique_id = format_mac(discovery_info["mac"])
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})
        self._async_abort_entries_match({CONF_HOST: host})

        self._node = {**discovery_info, "unique_id": unique_id}
        self.context["title_placeholders"] = {"name": self._node_name(self._node), "host": host}
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        assert self._node is not None
        if user_input is not None:
            return self._create_from_node(self._node)
        self._set_confirm_only()
        return self.async_show_form(
            step_id="discovery_confirm",
            description_placeholders={
                "name": self._node_name(self._node),
                "host": self._node["ip"],
                "universes": ", ".join(map(str, self._node.get("universes") or [])) or "-",
            },
        )

    @staticmethod
    def _node_name(node: dict[str, Any]) -> str:
        return node.get("short_name") or node.get("long_name") or DEFAULT_NAME

    def _create_from_node(self, node: dict[str, Any]) -> ConfigFlowResult:
        name = self._node_name(node)
        return self.async_create_entry(
            title=f"{name} ({node['ip']})",
            data={
                CONF_HOST: node["ip"],
                CONF_PORT: node.get("port") or DEFAULT_PORT,
                CONF_NAME: name,
                CONF_MAC: node.get("mac"),
                CONF_UNIVERSES: node.get("universes") or [],
            },
            options=DEFAULT_OPTIONS,
        )


class ArtNetOptionsFlow(OptionsFlow):
    """Manage fixtures and output settings of a node."""

    def __init__(self) -> None:
        self._edit_id: str | None = None

    @property
    def _options(self) -> dict[str, Any]:
        return {**DEFAULT_OPTIONS, **self.config_entry.options}

    @property
    def _fixtures(self) -> list[Fixture]:
        return [Fixture.from_dict(f) for f in self._options[CONF_FIXTURES]]

    def _save(self, fixtures: list[Fixture] | None = None, **changes: Any) -> ConfigFlowResult:
        options = {**self._options, **changes}
        if fixtures is not None:
            options[CONF_FIXTURES] = [f.to_dict() for f in fixtures]
        return self.async_create_entry(data=options)

    # ------------------------------------------------------------------- menu

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        menu = ["add_fixture"]
        if self._fixtures:
            menu.append("select_fixture")
        menu.append("send_settings")
        return self.async_show_menu(
            step_id="init",
            menu_options=menu,
            description_placeholders={"count": str(len(self._fixtures))},
        )

    # ---------------------------------------------------------------- fixtures

    def _fixture_schema(self, defaults: dict[str, Any], with_delete: bool) -> vol.Schema:
        adv = defaults.get(CONF_ADVANCED, defaults)
        universes = self.config_entry.data.get(CONF_UNIVERSES) or [0]
        fields: dict[Any, Any] = {
            vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, "")): TextSelector(),
            vol.Required(CONF_FIXTURE_TYPE, default=defaults.get(CONF_FIXTURE_TYPE, TYPE_RGB)): _select(
                FIXTURE_TYPES, "fixture_type"
            ),
            vol.Required(CONF_UNIVERSE, default=defaults.get(CONF_UNIVERSE, universes[0])): _number(0, 32767),
            vol.Required(CONF_START_CHANNEL, default=defaults.get(CONF_START_CHANNEL, 1)): _number(1, 512),
            vol.Required(CONF_BITS, default=str(defaults.get(CONF_BITS, 8))): _select(["8", "16"], "bits"),
            vol.Required(CONF_ADVANCED): section(
                vol.Schema(
                    {
                        vol.Optional(
                            CONF_CHANNEL_ORDER,
                            description={"suggested_value": adv.get(CONF_CHANNEL_ORDER, "")},
                        ): TextSelector(),
                        vol.Required(CONF_CCT_MODE, default=adv.get(CONF_CCT_MODE, CCT_MODE_CW)): _select(
                            CCT_MODES, "cct_mode"
                        ),
                        vol.Required(
                            CONF_MIN_KELVIN, default=adv.get(CONF_MIN_KELVIN, DEFAULT_MIN_KELVIN)
                        ): _number(1000, 20000, 50, "K"),
                        vol.Required(
                            CONF_MAX_KELVIN, default=adv.get(CONF_MAX_KELVIN, DEFAULT_MAX_KELVIN)
                        ): _number(1000, 20000, 50, "K"),
                        vol.Required(CONF_MIN_OUTPUT, default=adv.get(CONF_MIN_OUTPUT, 0)): _number(0, 255),
                        vol.Required(CONF_MAX_OUTPUT, default=adv.get(CONF_MAX_OUTPUT, 255)): _number(0, 255),
                    }
                ),
                {"collapsed": True},
            ),
        }
        if with_delete:
            fields[vol.Optional(CONF_DELETE, default=False)] = BooleanSelector()
        return vol.Schema(fields)

    def _parse_fixture(
        self, user_input: dict[str, Any], fixture_id: str
    ) -> tuple[Fixture | None, dict[str, str], dict[str, str]]:
        """Validate the form. Returns (fixture, errors, placeholders)."""
        adv = user_input.get(CONF_ADVANCED) or {}
        name = (user_input.get(CONF_NAME) or "").strip()
        fixture_type = user_input[CONF_FIXTURE_TYPE]
        cct_mode = adv.get(CONF_CCT_MODE, CCT_MODE_CW)
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}

        if not name:
            errors[CONF_NAME] = "name_required"
        order = normalize_order(fixture_type, cct_mode, adv.get(CONF_CHANNEL_ORDER))
        if order is None:
            errors["base"] = "invalid_order"
        min_k, max_k = int(adv.get(CONF_MIN_KELVIN, DEFAULT_MIN_KELVIN)), int(
            adv.get(CONF_MAX_KELVIN, DEFAULT_MAX_KELVIN)
        )
        if min_k >= max_k:
            errors["base"] = "invalid_kelvin_range"
        min_o, max_o = int(adv.get(CONF_MIN_OUTPUT, 0)), int(adv.get(CONF_MAX_OUTPUT, 255))
        if min_o >= max_o:
            errors["base"] = "invalid_output_range"
        if errors:
            return None, errors, placeholders

        fixture = Fixture(
            id=fixture_id,
            name=name,
            type=fixture_type,
            universe=int(user_input[CONF_UNIVERSE]),
            start_channel=int(user_input[CONF_START_CHANNEL]),
            bits=int(user_input[CONF_BITS]),
            channel_order=order,
            cct_mode=cct_mode,
            min_kelvin=min_k,
            max_kelvin=max_k,
            min_output=min_o,
            max_output=max_o,
        )
        if fixture.end_channel > 512:
            errors[CONF_START_CHANNEL] = "channel_overflow"
            placeholders["end"] = str(fixture.end_channel)
        elif conflict := find_overlap(self._fixtures, fixture):
            errors[CONF_START_CHANNEL] = "channel_overlap"
            placeholders["conflict"] = (
                f"{conflict.name} (U{conflict.universe} {conflict.start_channel}-{conflict.end_channel})"
            )
        return (None if errors else fixture), errors, placeholders

    async def async_step_add_fixture(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}
        if user_input is not None:
            fixture, errors, placeholders = self._parse_fixture(user_input, uuid.uuid4().hex)
            if fixture:
                return self._save([*self._fixtures, fixture])

        return self.async_show_form(
            step_id="add_fixture",
            data_schema=self._fixture_schema(user_input or {}, with_delete=False),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_select_fixture(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._edit_id = user_input[CONF_FIXTURE]
            return await self.async_step_edit_fixture()

        options = [
            SelectOptionDict(
                value=f.id,
                label=f"{f.name} - {f.type.upper()} U{f.universe} CH{f.start_channel}-{f.end_channel}",
            )
            for f in sorted(self._fixtures, key=lambda f: (f.universe, f.start_channel))
        ]
        return self.async_show_form(
            step_id="select_fixture",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_FIXTURE): SelectSelector(
                        SelectSelectorConfig(options=options, mode=SelectSelectorMode.LIST)
                    )
                }
            ),
        )

    async def async_step_edit_fixture(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        current = next((f for f in self._fixtures if f.id == self._edit_id), None)
        if current is None:
            return self.async_abort(reason="fixture_not_found")

        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}
        if user_input is not None:
            if user_input.get(CONF_DELETE):
                return self._save([f for f in self._fixtures if f.id != current.id])
            fixture, errors, placeholders = self._parse_fixture(user_input, current.id)
            if fixture:
                return self._save([fixture if f.id == current.id else f for f in self._fixtures])
            defaults = user_input
        else:
            defaults = current.to_dict()
            defaults[CONF_FIXTURE_TYPE] = current.type

        return self.async_show_form(
            step_id="edit_fixture",
            data_schema=self._fixture_schema(defaults, with_delete=True),
            errors=errors,
            description_placeholders={"name": current.name, **placeholders},
        )

    # ------------------------------------------------------------ send settings

    async def async_step_send_settings(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self._save(
                **{
                    CONF_SEND_MODE: user_input[CONF_SEND_MODE],
                    CONF_KEEPALIVE: float(user_input[CONF_KEEPALIVE]),
                    CONF_FPS: int(user_input[CONF_FPS]),
                    CONF_DEFAULT_TRANSITION: float(user_input[CONF_DEFAULT_TRANSITION]),
                }
            )

        opts = self._options
        return self.async_show_form(
            step_id="send_settings",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SEND_MODE, default=opts[CONF_SEND_MODE]): _select(SEND_MODES, "send_mode"),
                    vol.Required(CONF_KEEPALIVE, default=opts[CONF_KEEPALIVE]): _number(0.1, 10, 0.1, "s"),
                    vol.Required(CONF_FPS, default=opts[CONF_FPS]): _number(1, 44, 1, "Hz"),
                    vol.Required(CONF_DEFAULT_TRANSITION, default=opts[CONF_DEFAULT_TRANSITION]): _number(
                        0, 60, 0.1, "s"
                    ),
                }
            ),
        )
