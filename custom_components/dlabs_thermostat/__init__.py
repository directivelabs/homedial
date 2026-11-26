# Homedial · Copyright (c) 2026 Directive Labs, LLC
"""Homedial: a multi-room, safety-guarded setpoint controller for any HA thermostat."""
from __future__ import annotations

import logging
from types import MappingProxyType

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import EVENT_CORE_CONFIG_UPDATE, Platform
from homeassistant.core import Event, HomeAssistant, callback

from .const import (
    DOMAIN, LEGACY_ROOM_KEYS, OLD_PRODUCT, PRODUCT, ROOM_BACKUP, ROOM_NAME, ROOM_PROTECTED, ROOM_SENSOR, ROOM_WEIGHT,
    ROOM_WEIGHT_ENTITY, SUBENTRY_ROOM, old_default_title, rooms_from_legacy,
)

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[Platform] = [Platform.CLIMATE, Platform.SENSOR, Platform.BINARY_SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    from .config_flow import _celsius, _unit, async_normalize_units, stored_unit
    # Renamed to Homedial (2026-10-31): the old default titles follow, so the device shows the new name.
    # A title the user picked stays. Entity IDs are kept by the registry either way.
    if old_default_title(entry.title):
        hass.config_entries.async_update_entry(entry, title=PRODUCT + entry.title[len(OLD_PRODUCT):])
    # Limits are compared with room readings in Home Assistant's unit: convert first.
    async_normalize_units(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {}
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    @callback
    def _units_changed(_event: Event) -> None:
        # °F/°C switched while running: reload, which converts the limits before the guards run
        if stored_unit(entry) != _unit(_celsius(hass)):
            hass.config_entries.async_schedule_reload(entry.entry_id)

    entry.async_on_unload(hass.bus.async_listen(EVENT_CORE_CONFIG_UPDATE, _units_changed))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Deliberately does NOT restore or rewrite the real thermostat's setpoint or mode.
    Removing a controller must not be a control action: whatever the equipment was last
    told stands until a person or another controller changes it."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Settings, rooms added, edited or removed: reload. The entity keeps its id, and its mode
    and target come back through restore, so nothing has to be set up again."""
    await hass.config_entries.async_reload(entry.entry_id)


def room_title(hass: HomeAssistant, room: dict) -> str:
    if room.get(ROOM_NAME):
        return str(room[ROOM_NAME])
    st = hass.states.get(room[ROOM_SENSOR])
    return (st.attributes.get("friendly_name") if st else None) or room[ROOM_SENSOR]


def room_subentry_data(room: dict) -> dict:
    return {k: room.get(k) for k in (ROOM_NAME, ROOM_SENSOR, ROOM_PROTECTED, ROOM_WEIGHT,
                                     ROOM_WEIGHT_ENTITY, ROOM_BACKUP) if room.get(k) is not None}


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Version 1 kept rooms as positional lists. Version 2 makes each room its own item
    ("+ Add room" on the integration page). Nothing about how the house is controlled changes."""
    if entry.version > 2:
        return False
    if entry.version == 1:
        merged = {**entry.data, **entry.options}
        rooms = rooms_from_legacy(merged)
        data = {k: v for k, v in entry.data.items() if k not in LEGACY_ROOM_KEYS}
        options = {k: v for k, v in entry.options.items() if k not in LEGACY_ROOM_KEYS}
        hass.config_entries.async_update_entry(entry, data=data, options=options, version=2)
        for room in rooms:
            hass.config_entries.async_add_subentry(entry, ConfigSubentry(
                data=MappingProxyType(room_subentry_data(room)), subentry_type=SUBENTRY_ROOM,
                title=room_title(hass, room), unique_id=room[ROOM_SENSOR]))
        _LOGGER.info("Homedial: moved %d rooms to their own items (entry version 2)", len(rooms))
    return True
