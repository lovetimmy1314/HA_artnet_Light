"""Config/options flow tests. Require pytest-homeassistant-custom-component (Linux, Python >= 3.12)."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, State
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr, entity_registry as er

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    mock_restore_cache,
    mock_restore_cache_with_extra_data,
)

from custom_components.artnet_light.artnet import ArtNetNode
from custom_components.artnet_light.controller import ArtNetController
from custom_components.artnet_light.const import DOMAIN

NODE = ArtNetNode(ip="192.168.1.50", short_name="Node-A", mac="02:00:00:00:00:01", universes=[0, 1])


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture(autouse=True)
def no_network():
    """No real sockets: skip background discovery and the UDP socket."""
    with (
        patch("custom_components.artnet_light.async_start_background_discovery"),
        patch("custom_components.artnet_light.controller.ArtNetController.async_start"),
    ):
        yield


@pytest.fixture(autouse=True)
async def unload_entries(hass: HomeAssistant):
    """Unload every entry so the sender tasks don't linger past the test."""
    yield
    for entry in hass.config_entries.async_entries(DOMAIN):
        await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


def scan_returns(nodes):
    return patch("custom_components.artnet_light.config_flow.async_scan", return_value=nodes)


async def test_user_manual_when_nothing_found(hass: HomeAssistant) -> None:
    with scan_returns([]):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "manual"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "not-an-ip", "port": 6454, "name": "X"}
    )
    assert result["errors"] == {"host": "invalid_host"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "192.168.1.200", "port": 6454, "name": "Gateway"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["host"] == "192.168.1.200"
    assert result["options"]["fixtures"] == []


async def test_user_pick_discovered(hass: HomeAssistant) -> None:
    with scan_returns([NODE]):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"device": NODE.ip})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == NODE.mac
    assert result["data"]["universes"] == [0, 1]


async def test_integration_discovery_and_dedup(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_INTEGRATION_DISCOVERY}, data=NODE.as_dict()
    )
    assert result["step_id"] == "discovery_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    moved = {**NODE.as_dict(), "ip": "192.168.1.99"}
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_INTEGRATION_DISCOVERY}, data=moved
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert hass.config_entries.async_entries(DOMAIN)[0].data["host"] == "192.168.1.99"


async def _setup_entry(hass: HomeAssistant):
    with scan_returns([]):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": "192.168.1.200", "port": 6454, "name": "Gateway"}
        )
    await hass.async_block_till_done()
    return result["result"]


FIXTURE_INPUT = {
    "name": "客厅灯带",
    "type": "rgb",
    "universe": 0,
    "start_channel": 1,
    "bits": "8",
    "advanced": {"cct_mode": "cold_warm", "min_kelvin": 2700, "max_kelvin": 6500, "min_output": 0, "max_output": 255},
}


async def test_options_add_edit_delete_fixture(hass: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    entry = await _setup_entry(hass)

    # add
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "add_fixture"})
    result = await hass.config_entries.options.async_configure(result["flow_id"], FIXTURE_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    state = hass.states.get("light.ke_ting_deng_dai")
    assert state is not None
    assert state.attributes["dmx_end_channel"] == 3

    # fixture device hangs off the node device
    devices = dr.async_get(hass)
    node = next(
        d
        for d in dr.async_entries_for_config_entry(devices, entry.entry_id)
        if (DOMAIN, entry.entry_id) in d.identifiers
    )
    fixture_dev = devices.async_get(er.async_get(hass).async_get("light.ke_ting_deng_dai").device_id)
    assert fixture_dev.name == "客厅灯带"
    assert fixture_dev.via_device_id == node.id

    # overlapping fixture is rejected
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "add_fixture"})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**FIXTURE_INPUT, "name": "Other", "start_channel": 3}
    )
    assert result["errors"] == {"start_channel": "channel_overlap"}

    # turning on writes DMX
    await hass.services.async_call(
        "light", "turn_on", {"entity_id": "light.ke_ting_deng_dai", "rgb_color": [255, 0, 0]}, blocking=True
    )
    assert entry.runtime_data.universe_data(0)[:3] == bytes([255, 0, 0])

    # delete
    fixture_id = entry.options["fixtures"][0]["id"]
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "select_fixture"})
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"fixture": fixture_id})
    assert result["step_id"] == "edit_fixture"
    result = await hass.config_entries.options.async_configure(result["flow_id"], {**FIXTURE_INPUT, "delete": True})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    assert hass.states.get("light.ke_ting_deng_dai") is None
    assert er.async_get(hass).async_get("light.ke_ting_deng_dai") is None
    assert devices.async_get(fixture_dev.id) is None
    assert "Detected that custom integration" not in caplog.text  # no deprecated HA API use

def _entry_with_fixtures(hass: HomeAssistant, *fixtures: dict) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Gateway",
        data={"host": "192.168.1.200", "port": 6454, "name": "Gateway", "universes": [0]},
        options={"fixtures": list(fixtures)},
    )
    entry.add_to_hass(hass)
    return entry


RGB_FIXTURE = {"id": "fx-rgb", "name": "Strip", "type": "rgb", "universe": 0, "start_channel": 1}
CCT_FIXTURE = {"id": "fx-cct", "name": "Panel", "type": "cct", "universe": 0, "start_channel": 10}


async def test_restore_off_keeps_last_values(hass: HomeAssistant) -> None:
    """Restarting while off keeps brightness/colour for the next turn_on (extra stored data)."""
    mock_restore_cache_with_extra_data(
        hass,
        [
            (
                State("light.strip", "off"),
                {"brightness": 128, "rgb_color": [0, 0, 255], "rgbw_color": None,
                 "rgbww_color": None, "color_temp_kelvin": None},
            ),
            (
                State("light.panel", "off"),
                {"brightness": 64, "rgb_color": None, "rgbw_color": None,
                 "rgbww_color": None, "color_temp_kelvin": 3000},
            ),
        ],
    )
    entry = _entry_with_fixtures(hass, RGB_FIXTURE, CCT_FIXTURE)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("light.strip").state == "off"
    assert entry.runtime_data.universe_data(0)[:3] == bytes(3)

    await hass.services.async_call("light", "turn_on", {"entity_id": "light.strip"}, blocking=True)
    state = hass.states.get("light.strip")
    assert state.attributes["brightness"] == 128
    assert tuple(state.attributes["rgb_color"]) == (0, 0, 255)

    await hass.services.async_call("light", "turn_on", {"entity_id": "light.panel"}, blocking=True)
    state = hass.states.get("light.panel")
    assert state.attributes["brightness"] == 64
    assert state.attributes["color_temp_kelvin"] == 3000


async def test_restore_legacy_state_attributes(hass: HomeAssistant) -> None:
    """States saved by <= 0.1.2 have no extra data: fall back to the attributes."""
    mock_restore_cache(hass, [State("light.strip", "on", {"brightness": 255, "rgb_color": [255, 0, 0]})])
    entry = _entry_with_fixtures(hass, RGB_FIXTURE)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("light.strip").state == "on"
    assert entry.runtime_data.universe_data(0)[:3] == bytes([255, 0, 0])


async def _open_edit(hass: HomeAssistant, entry, fixture_id: str):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "select_fixture"})
    return await hass.config_entries.options.async_configure(result["flow_id"], {"fixture": fixture_id})


def _suggested(result, key: str):
    for field, value in result["data_schema"].schema.items():
        if field == "advanced":
            for inner in value.schema.schema:
                if inner == key:
                    return (inner.description or {}).get("suggested_value")
    raise KeyError(key)


async def test_edit_fixture_change_type_with_default_order(hass: HomeAssistant) -> None:
    """A default channel order is not pre-filled, so changing the type just works."""
    entry = _entry_with_fixtures(hass, RGB_FIXTURE)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await _open_edit(hass, entry, "fx-rgb")
    assert result["step_id"] == "edit_fixture"
    assert not _suggested(result, "channel_order")

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**FIXTURE_INPUT, "name": "Strip", "type": "rgbw", "bits": "16"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    fixture = entry.options["fixtures"][0]
    assert (fixture["id"], fixture["type"], fixture["channel_order"], fixture["bits"]) == ("fx-rgb", "rgbw", "RGBW", 16)
    state = hass.states.get("light.strip")
    assert state.attributes["dmx_end_channel"] == 8
    assert state.attributes["supported_color_modes"] == ["rgbw"]

    # a custom order is still offered for editing
    result = await _open_edit(hass, entry, "fx-rgb")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**FIXTURE_INPUT, "name": "Strip", "type": "rgbw", "advanced": {**FIXTURE_INPUT["advanced"], "channel_order": "wrgb"}}
    )
    await hass.async_block_till_done()
    result = await _open_edit(hass, entry, "fx-rgb")
    assert _suggested(result, "channel_order") == "WRGB"


async def test_send_settings(hass: HomeAssistant) -> None:
    entry = _entry_with_fixtures(hass, RGB_FIXTURE)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "send_settings"})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"send_mode": "continuous", "keepalive": 2, "fps": 25, "default_transition": 1.5}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    assert entry.options["fixtures"] == [RGB_FIXTURE]
    controller = entry.runtime_data
    assert (controller.send_mode, controller.fps, controller.keepalive) == ("continuous", 25, 2)


async def test_removed_universe_is_blacked_out(hass: HomeAssistant) -> None:
    """Universes that lose their last fixture get a zero frame instead of holding the last look."""
    other = {**CCT_FIXTURE, "universe": 1}
    entry = _entry_with_fixtures(hass, RGB_FIXTURE, other)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    with patch.object(ArtNetController, "blackout", autospec=True) as blackout:
        # delete the only fixture on universe 1 -> reload blacks out universe 1 only
        result = await _open_edit(hass, entry, "fx-cct")
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {**FIXTURE_INPUT, "type": "cct", "delete": True}
        )
        await hass.async_block_till_done()
        assert blackout.call_args_list[-1].args[1] == {1}

        # disabling the entry turns everything off
        await hass.config_entries.async_set_disabled_by(
            entry.entry_id, config_entries.ConfigEntryDisabler.USER
        )
        await hass.async_block_till_done()
        assert blackout.call_args_list[-1].args[1] == {0}

        await hass.config_entries.async_set_disabled_by(entry.entry_id, None)
        await hass.async_block_till_done()

        # removing the entry turns everything off, too
        blackout.reset_mock()
        await hass.config_entries.async_remove(entry.entry_id)
        await hass.async_block_till_done()
        assert [c.args[1] for c in blackout.call_args_list] == [set(), {0}]


async def test_manual_duplicate_node_aborts(hass: HomeAssistant) -> None:
    await _setup_entry(hass)
    with scan_returns([]):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": "192.168.1.200", "port": 6454, "name": "Again"}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"

    # same host as a discovered (MAC-keyed) node is caught too
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_INTEGRATION_DISCOVERY}, data=NODE.as_dict()
    )
    await hass.config_entries.flow.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()
    with scan_returns([]):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": NODE.ip, "port": 6454, "name": "Again"}
        )
    assert result["type"] is FlowResultType.ABORT
    assert len(hass.config_entries.async_entries(DOMAIN)) == 2


async def test_fixture_form_reports_every_error(hass: HomeAssistant) -> None:
    entry = _entry_with_fixtures(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "add_fixture"})
    bad = {
        **FIXTURE_INPUT,
        "name": " ",
        "advanced": {**FIXTURE_INPUT["advanced"], "channel_order": "RGGB", "min_kelvin": 6500, "max_output": 0},
    }
    result = await hass.config_entries.options.async_configure(result["flow_id"], bad)
    assert result["errors"] == {
        "name": "name_required",
        "base": "invalid_order",
        "advanced": "invalid_kelvin_and_output_range",
    }

    bad = {**FIXTURE_INPUT, "advanced": {**FIXTURE_INPUT["advanced"], "min_output": 200, "max_output": 100}}
    result = await hass.config_entries.options.async_configure(result["flow_id"], bad)
    assert result["errors"] == {"advanced": "invalid_output_range"}


async def _turn_on(hass: HomeAssistant, entity_id: str, **data) -> None:
    await hass.services.async_call("light", "turn_on", {"entity_id": entity_id, **data}, blocking=True)


async def test_entity_output_per_fixture_type(hass: HomeAssistant) -> None:
    """CCT (both modes), RGBWW and 16-bit fixtures write the right DMX bytes."""
    entry = _entry_with_fixtures(
        hass,
        {"id": "cw", "name": "CW", "type": "cct", "start_channel": 1,
         "min_kelvin": 2700, "max_kelvin": 6500},
        {"id": "it", "name": "IT", "type": "cct", "cct_mode": "intensity_temp", "start_channel": 3,
         "min_kelvin": 2700, "max_kelvin": 6500},
        {"id": "ww", "name": "WW", "type": "rgbww", "start_channel": 5, "channel_order": "WCRGB"},
        {"id": "d16", "name": "D16", "type": "dimmer", "start_channel": 10, "bits": 16},
        {"id": "rgb16", "name": "RGB16", "type": "rgb", "start_channel": 20, "bits": 16, "max_output": 128},
    )
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    data = lambda: entry.runtime_data.universe_data(0)  # noqa: E731

    await _turn_on(hass, "light.cw", color_temp_kelvin=6500, brightness=255)
    assert data()[0:2] == bytes([255, 0])  # C W
    await _turn_on(hass, "light.cw", color_temp_kelvin=2700)
    assert data()[0:2] == bytes([0, 255])

    await _turn_on(hass, "light.it", color_temp_kelvin=4600, brightness=128)
    assert data()[2:4] == bytes([128, 128])  # I T (T = 50 % between min and max)
    state = hass.states.get("light.it")
    assert (state.attributes["min_color_temp_kelvin"], state.attributes["max_color_temp_kelvin"]) == (2700, 6500)

    await _turn_on(hass, "light.ww", rgbww_color=[10, 20, 30, 40, 50])
    assert data()[4:9] == bytes([50, 40, 10, 20, 30])  # W C R G B

    await _turn_on(hass, "light.d16", brightness=128)
    value = round(128 / 255 * 0xFFFF)
    assert data()[9:11] == bytes([value >> 8, value & 0xFF])

    await _turn_on(hass, "light.rgb16", rgb_color=[255, 0, 0])
    red = round(128 / 255 * 0xFFFF)  # max_output caps full red at 128/255
    assert data()[19:25] == bytes([red >> 8, red & 0xFF, 0, 0, 0, 0])
    assert hass.states.get("light.rgb16").attributes["dmx_end_channel"] == 25


async def test_transition_fades(hass: HomeAssistant) -> None:
    entry = _entry_with_fixtures(hass, RGB_FIXTURE)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    data = lambda: entry.runtime_data.universe_data(0)[:3]  # noqa: E731

    await _turn_on(hass, "light.strip", rgb_color=[255, 0, 0])
    assert data() == bytes([255, 0, 0])

    await _turn_on(hass, "light.strip", rgb_color=[0, 0, 255], transition=0.4)
    await asyncio.sleep(0.15)
    mid = data()
    assert 0 < mid[0] < 255 and 0 < mid[2] < 255
    await asyncio.sleep(0.4)
    assert data() == bytes([0, 0, 255])

    # a new command cancels the running fade and wins
    await _turn_on(hass, "light.strip", rgb_color=[0, 255, 0], transition=10)
    await hass.services.async_call("light", "turn_off", {"entity_id": "light.strip"}, blocking=True)
    await asyncio.sleep(0.1)
    assert data() == bytes(3)
