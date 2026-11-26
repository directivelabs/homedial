# Homedial · Copyright (c) 2026 Directive Labs, LLC
"""Problem sensors: turn on when a safety guard is blocking writes, or a room is on its fallback."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .diagnostics_base import DLabsDiagnostic


class GuardBlocking(DLabsDiagnostic, BinarySensorEntity):
    key = "guard_blocking"
    id_domain = "binary_sensor"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    @property
    def is_on(self) -> bool | None:
        s = self._status()
        return None if s is None else s["blocked"]


class OnFallback(DLabsDiagnostic, BinarySensorEntity):
    key = "on_fallback"
    id_domain = "binary_sensor"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def is_on(self) -> bool | None:
        s = self._status()
        return None if s is None else s["on_fallback"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([GuardBlocking(hass, entry), OnFallback(hass, entry)])
