# Homedial · Copyright (c) 2026 Directive Labs, LLC
"""Diagnostic sensors: the blended control temperature, the plain-English reason (technical details
as an attribute), and the current latent (dew point) depression."""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .diagnostics_base import DLabsDiagnostic


class ControlTemperature(DLabsDiagnostic, SensorEntity):
    key = "control_temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    @property
    def native_unit_of_measurement(self) -> str:
        return self.hass.config.units.temperature_unit

    @property
    def native_value(self):
        s = self._status()
        return None if s is None else s["control_temperature"]


class Reason(DLabsDiagnostic, SensorEntity):
    key = "reason"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self):
        # One or two plain sentences for people (wording pass, 2026-10-26). The full technical
        # record is the `details` attribute here and the `reason` attribute on the climate entity.
        s = self._status()
        return None if s is None else s["summary"][:255]     # HA state limit

    @property
    def extra_state_attributes(self) -> dict:
        s = self._status()
        return {} if s is None else {"details": s["reason"]}


class LatentDepression(DLabsDiagnostic, SensorEntity):
    key = "latent_depression"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_unit_of_measurement(self) -> str:
        return self.hass.config.units.temperature_unit

    @property
    def native_value(self):
        s = self._status()
        return None if s is None else s["latent_depression"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([ControlTemperature(hass, entry), Reason(hass, entry), LatentDepression(hass, entry)])
