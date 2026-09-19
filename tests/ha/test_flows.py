"""Config/options flow tests. Require pytest-homeassistant-custom-component (Linux, Python >= 3.12)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr, entity_registry as er

from custom_components.artnet_light.artnet import ArtNetNode
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


async def test_options_add_edit_delete_fixture(hass: HomeAssistant) -> None:
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

