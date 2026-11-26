# Homedial · Copyright (c) 2026 Directive Labs, LLC
"""Shared base for the diagnostic entities: they read the controller's status and refresh
whenever it publishes, so guard trips and fallbacks can trigger normal HA automations."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .climate import device_info
from .const import DOMAIN, ID_SUFFIX, SIGNAL_UPDATE, id_base


class DLabsDiagnostic(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    key = ""
    id_domain = "sensor"          # binary sensors override it; used for the pinned entity ID

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{self.key}"
        self._attr_translation_key = self.key
        self.entity_id = f"{self.id_domain}.{id_base(entry.title)}_{ID_SUFFIX[self.key]}"
        self._attr_device_info = device_info(entry)

    def _status(self) -> dict | None:
        ent = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {}).get("entity")
        return ent.status if ent else None

    @property
    def available(self) -> bool:
        return self._status() is not None

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(
            self.hass, SIGNAL_UPDATE.format(self._entry.entry_id), self._refresh))

    @callback
    def _refresh(self) -> None:
        self.async_write_ha_state()
