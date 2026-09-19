"""The Art-Net Light integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, device_registry as dr, entity_registry as er
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_FIXTURES,
    CONF_FPS,
    CONF_KEEPALIVE,
    CONF_MAC,
    CONF_SEND_MODE,
    DEFAULT_OPTIONS,
    DOMAIN,
)
from .controller import ArtNetController
from .fixture import Fixture
from .discovery import async_start_background_discovery

PLATFORMS = [Platform.LIGHT]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type ArtNetConfigEntry = ConfigEntry[ArtNetController]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> None | bool:
    """Start background discovery once the integration is loaded."""
    async_start_background_discovery(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ArtNetConfigEntry) -> bool:
    options = {**DEFAULT_OPTIONS, **entry.options}
    controller = ArtNetController(
        entry.data[CONF_HOST],
        entry.data[CONF_PORT],
        send_mode=options[CONF_SEND_MODE],
        keepalive=options[CONF_KEEPALIVE],
        fps=options[CONF_FPS],
    )
    await controller.async_start()
    entry.runtime_data = controller

    device_registry = dr.async_get(hass)
    node = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        connections={(dr.CONNECTION_NETWORK_MAC, mac)} if (mac := entry.data.get(CONF_MAC)) else set(),
        name=entry.data.get(CONF_NAME) or entry.title,
        manufacturer="Art-Net",
        model="Art-Net node",
        configuration_url=f"http://{entry.data[CONF_HOST]}",
    )
    # Fixture devices are created here (not via the entity's DeviceInfo) so they can be
    # linked with via_device_id; DeviceInfo(via_device=...) is deprecated since HA 2026.x.
    for fixture in _fixtures(entry):
        device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, fixture.id)},
            name=fixture.name,
            manufacturer="Art-Net",
            model=f"{fixture.type.upper()} {fixture.bits}-bit",
            via_device_id=node.id,
        )
    _async_remove_stale(hass, entry, {f.id for f in _fixtures(entry)})

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Entities have restored and written their levels; start transmitting.
    controller.async_start_sending(
        lambda coro, name: entry.async_create_background_task(hass, coro, name)
    )

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


def _fixtures(entry: ConfigEntry) -> list[Fixture]:
    return [Fixture.from_dict(data) for data in {**DEFAULT_OPTIONS, **entry.options}[CONF_FIXTURES]]


def _async_remove_stale(hass: HomeAssistant, entry: ConfigEntry, fixture_ids: set[str]) -> None:
    """Drop devices/entities of fixtures that were deleted in the options flow."""
    entity_registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
        if entity.unique_id not in fixture_ids:
            entity_registry.async_remove(entity.entity_id)

    device_registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(device_registry, entry.entry_id):
        ids = {ident for domain, ident in device.identifiers if domain == DOMAIN}
        if entry.entry_id in ids or ids & fixture_ids:
            continue
        device_registry.async_update_device(device.id, remove_config_entry_id=entry.entry_id)


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Options changed (fixture added/edited/removed): reload so entities follow."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ArtNetConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        controller = entry.runtime_data
        # Universes nobody transmits any more would hold their last frame on most
        # nodes: zero those (all of them when the entry is being disabled).
        keep = set() if entry.disabled_by else {f.universe for f in _fixtures(entry)}
        controller.blackout(controller.universes - keep)
        await controller.async_stop()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Entry deleted: turn its fixtures off (the controller is already stopped)."""
    if not (universes := {f.universe for f in _fixtures(entry)}):
        return
    controller = ArtNetController(
        entry.data[CONF_HOST], entry.data[CONF_PORT], send_mode=DEFAULT_OPTIONS[CONF_SEND_MODE]
    )
    try:
        await controller.async_start()
    except OSError:
        return
    controller.blackout(universes)
    await controller.async_stop()
