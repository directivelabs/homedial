# Homedial · Copyright (c) 2026 Directive Labs, LLC
"""Setup screens for Homedial. Nothing is hardcoded: every source and limit is chosen
here. Ranges and defaults follow the instance's unit (°F or °C).

Hardened 2026-09-30: removed three fields nothing read (outdoor temperature, outdoor humidity,
weather entity); added "control the thermostat's mode"; every limit converts for °C.
0.3.0 (2026-10-04): every room is its own item ("+ Add room", edit, delete) with simple fields
up front and an "Advanced" section folded away; Configure opens a menu (thermostat, safety,
humidity, advanced); settings that are cleared really clear.
Private beta (2026-10-05): first-time setup makes the same room items as "+ Add room" (no more
one-per-room lists); the dew point picker takes temperature sensors only; Homedial can't pick itself
or a thermostat another Homedial controls; limits are saved with their unit and converted if Home
Assistant switches °F/°C; °C fields sit on whole steps."""
from __future__ import annotations

import logging
import math
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry, ConfigFlow, ConfigFlowResult, ConfigSubentryFlow, OptionsFlow, SubentryFlowResult,
)
from homeassistant.data_entry_flow import section
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er, selector

from .const import (
    CONF_CONTROL_UNDERLYING_MODE, CONF_FREEZE_LIMIT, CONF_FROZEN_MIN, CONF_LATENT_CEILING,
    CONF_LATENT_MAX_DEPRESSION, CONF_LATENT_SOURCE, CONF_LATENT_SPAN, CONF_MIN_WRITE_INTERVAL,
    CONF_MIN_WRITE_STEP, CONF_OFFSET_CLAMP_HIGH, CONF_OFFSET_CLAMP_LOW, CONF_OVERHEAT_LIMIT,
    CONF_PROTECTED_FLOOR, CONF_PROTECTED_FLOOR_ENABLE_ENTITY, CONF_PROTECTED_FLOOR_ENABLED,
    CONF_PROTECTED_FLOOR_ENTITY, CONF_PROTECTED_ROOM, CONF_ROOM_FALLBACK_ENTITIES,
    CONF_ROOM_WEIGHT_ENTITIES, CONF_ROOM_WEIGHTS, CONF_ROOMS, CONF_SETPOINT_CLAMP,
    CONF_SETPOINT_RESOLUTION, CONF_STALE_SENSOR_MIN, CONF_UNDERLYING,
    CONF_UNDERLYING_OFFSET_CLAMP_HIGH, CONF_UNDERLYING_OFFSET_CLAMP_LOW,
    CONF_UNDERLYING_OFFSET_ENTITY, DOMAIN, PRODUCT, ROOM_ADVANCED, ROOM_BACKUP, ROOM_NAME, ROOM_PROTECTED,
    ROOM_SENSOR, ROOM_WEIGHT, ROOM_WEIGHT_ENTITY, SUBENTRY_ROOM, defaults_for,
)

_LOGGER = logging.getLogger(__name__)

_ENTITY = selector.EntitySelector
_SENSOR_TEMP = selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
TEMP_UNITS = {u.value for u in UnitOfTemperature}

# The unit the saved temperature limits are in. Without it, a °F/°C switch after setup read
# 82 °F as 82 °C and the overheat guard never tripped.
CONF_TEMP_UNIT = "temperature_unit"

# Range of every temperature field, in °F. °C ranges are converted and rounded OUTWARD to the
# field's step, so the arrows land on whole steps (1.0, 1.25 ...) and any converted value fits.
ABS_RANGE_F = {CONF_FREEZE_LIMIT: (35.0, 70.0), CONF_OVERHEAT_LIMIT: (70.0, 110.0),
               CONF_PROTECTED_FLOOR: (40.0, 80.0), CONF_LATENT_CEILING: (30.0, 80.0)}
DELTA_RANGE_F = {CONF_SETPOINT_CLAMP: (0.5, 10.0), CONF_OFFSET_CLAMP_LOW: (-20.0, 0.0),
                 CONF_OFFSET_CLAMP_HIGH: (0.0, 20.0), CONF_LATENT_SPAN: (0.5, 20.0),
                 CONF_LATENT_MAX_DEPRESSION: (0.0, 6.0), CONF_UNDERLYING_OFFSET_CLAMP_LOW: (-5.0, 0.0),
                 CONF_UNDERLYING_OFFSET_CLAMP_HIGH: (0.0, 5.0)}
# When a limit is converted it is rounded toward the SAFE side: freeze limit and floor up,
# overheat limit down. Everything else goes to the nearest step.
_ROUND_UP = {CONF_FREEZE_LIMIT, CONF_PROTECTED_FLOOR}
_ROUND_DOWN = {CONF_OVERHEAT_LIMIT}


def _celsius(hass: HomeAssistant) -> bool:
    return hass.config.units.temperature_unit == UnitOfTemperature.CELSIUS


def _unit(c: bool) -> str:
    return UnitOfTemperature.CELSIUS.value if c else UnitOfTemperature.FAHRENHEIT.value


def _num(lo: float, hi: float, step: float, unit: str | None = None):
    """unit_of_measurement is OMITTED when there is none, never passed as None (an explicit
    None fails validation and takes the whole flow down)."""
    cfg: dict = {"min": lo, "max": hi, "step": step, "mode": selector.NumberSelectorMode.BOX}
    if unit is not None:
        cfg["unit_of_measurement"] = unit
    return selector.NumberSelector(selector.NumberSelectorConfig(**cfg))


def _step(key: str, c: bool) -> float:
    if key in ABS_RANGE_F:
        return 0.5
    return 0.25 if c or key in (CONF_UNDERLYING_OFFSET_CLAMP_LOW, CONF_UNDERLYING_OFFSET_CLAMP_HIGH) else 0.5


def _to(key: str, v: float, c: bool) -> float:
    """A °F value of this field in °C (unrounded)."""
    if not c:
        return v
    return (v - 32.0) * 5.0 / 9.0 if key in ABS_RANGE_F else v * 5.0 / 9.0


def temp_range(key: str, c: bool) -> tuple[float, float]:
    lo_f, hi_f = ABS_RANGE_F.get(key) or DELTA_RANGE_F[key]
    if not c:
        return lo_f, hi_f
    st = _step(key, True)
    return math.floor(round(_to(key, lo_f, True) / st, 6)) * st, math.ceil(round(_to(key, hi_f, True) / st, 6)) * st


def _temp_num(key: str, c: bool):
    return _num(*temp_range(key, c), _step(key, c), _unit(c))


def _convert(key: str, v, from_c: bool, to_c: bool):
    """One saved temperature setting from one unit to the other, rounded (toward safe for the
    limits) and kept inside the field's range so Configure can always be saved."""
    if from_c == to_c or v is None or (key not in ABS_RANGE_F and key not in DELTA_RANGE_F):
        return v
    v = float(v)
    if key in ABS_RANGE_F:
        x = (v - 32.0) * 5.0 / 9.0 if to_c else v * 9.0 / 5.0 + 32.0
    else:
        x = v * 5.0 / 9.0 if to_c else v * 9.0 / 5.0
    st = _step(key, to_c)
    n = round(x / st, 6)
    n = math.ceil(n) if key in _ROUND_UP else math.floor(n) if key in _ROUND_DOWN else round(n)
    lo, hi = temp_range(key, to_c)
    return min(max(n * st, lo), hi)


def _saved_celsius(values, fallback: bool | None) -> bool | None:
    """Which unit a block of saved settings is in: the stored unit, or (entries from before the
    unit was stored) read off the safety limits, whose °F and °C ranges never overlap."""
    u = values.get(CONF_TEMP_UNIT)
    if u in TEMP_UNITS:
        return u == UnitOfTemperature.CELSIUS
    for key, split in ((CONF_OVERHEAT_LIMIT, 56.0), (CONF_FREEZE_LIMIT, 28.0),
                       (CONF_PROTECTED_FLOOR, 33.0), (CONF_LATENT_CEILING, 28.5)):
        try:
            return float(values[key]) < split
        except (KeyError, TypeError, ValueError):
            continue
    return fallback


def _convert_block(values, from_c: bool, to_c: bool) -> dict:
    return {k: _convert(k, v, from_c, to_c) for k, v in values.items()}


def values_in_unit(data, options, celsius: bool) -> dict:
    """data + options (options win) with every temperature setting in the given unit."""
    data_c = _saved_celsius(data, celsius)
    opt_c = _saved_celsius(options, data_c)
    return {**_convert_block(data, data_c, celsius), **_convert_block(options, opt_c, celsius),
            CONF_TEMP_UNIT: _unit(celsius)}


def stored_unit(entry: ConfigEntry) -> str | None:
    return (entry.options.get(CONF_TEMP_UNIT) or entry.data.get(CONF_TEMP_UNIT))


@callback
def async_normalize_units(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Bring the saved limits into Home Assistant's current unit. Called before Homedial starts,
    so the guards always compare like with like. True if anything had to be converted."""
    c = _celsius(hass)
    data_c = _saved_celsius(entry.data, c)
    opt_c = _saved_celsius(entry.options, data_c)
    data = {**_convert_block(entry.data, data_c, c), CONF_TEMP_UNIT: _unit(c)}
    options = dict(entry.options)
    if options:
        options = {**_convert_block(options, opt_c, c), CONF_TEMP_UNIT: _unit(c)}
    if data == dict(entry.data) and options == dict(entry.options):
        return False
    converted = data_c != c or (bool(entry.options) and opt_c != c)
    if converted:
        now = {**data, **options}
        _LOGGER.warning("Homedial: Home Assistant now uses %s. Saved limits were converted "
                        "(freeze %s, overheat %s, floor %s). Check them under Configure > Safety limits.",
                        _unit(c), now.get(CONF_FREEZE_LIMIT), now.get(CONF_OVERHEAT_LIMIT), now.get(CONF_PROTECTED_FLOOR))
    hass.config_entries.async_update_entry(entry, data=data, options=options)
    return converted


# --- pickers that can't be filled in wrong ------------------------------------------------------
def _dlabs_climates(hass: HomeAssistant) -> list[str]:
    return sorted(e.entity_id for e in er.async_get(hass).entities.values()
                  if e.platform == DOMAIN and e.domain == "climate")


def _thermostat_picker(hass: HomeAssistant):
    cfg: dict = {"domain": "climate"}
    own = _dlabs_climates(hass)
    if own:
        cfg["exclude_entities"] = own        # Homedial is never its own thermostat
    return _ENTITY(selector.EntitySelectorConfig(**cfg))


def underlying_errors(hass: HomeAssistant, entity_id: str | None, entry_id: str | None = None) -> dict[str, str]:
    """The real thermostat: not a Homedial entity, and not one another Homedial already controls."""
    if not entity_id:
        return {}
    reg = er.async_get(hass).async_get(entity_id)
    if reg is not None and reg.platform == DOMAIN:
        return {CONF_UNDERLYING: "underlying_is_dlabs"}
    for other in hass.config_entries.async_entries(DOMAIN):
        if other.entry_id != entry_id and {**other.data, **other.options}.get(CONF_UNDERLYING) == entity_id:
            return {CONF_UNDERLYING: "underlying_in_use"}
    return {}


def dew_point_errors(hass: HomeAssistant, entity_id: str | None) -> dict[str, str]:
    """Humidity help needs a DEW POINT (a temperature). A humidity % sensor read as a dew point
    lowered the cooling setpoint all summer. A sensor with no state yet can't be checked."""
    if not entity_id:
        return {}
    st = hass.states.get(entity_id)
    if st is None:
        return {}
    if st.attributes.get("device_class") == "humidity" or st.attributes.get("unit_of_measurement") not in TEMP_UNITS:
        return {CONF_LATENT_SOURCE: "dew_point_not_temperature"}
    return {}


def _dew_point_like(hass: HomeAssistant) -> list[str]:
    """Sensors named like a dew point. They report °F/°C like a room sensor, so the room pickers
    offered them; blended in as a room, a dew point reads the house far too cold."""
    out = []
    for st in hass.states.async_all("sensor"):
        name = f"{st.entity_id} {st.attributes.get('friendly_name') or ''}".lower()
        if "dewpoint" in name.replace(" ", "").replace("_", "").replace("-", ""):
            out.append(st.entity_id)
    return sorted(out)


def _room_picker(hass: HomeAssistant, multiple: bool = False):
    cfg: dict = {"domain": "sensor", "device_class": "temperature"}
    if multiple:
        cfg["multiple"] = True
    dew = _dew_point_like(hass)
    if dew:
        cfg["exclude_entities"] = dew
    return _ENTITY(selector.EntitySelectorConfig(**cfg))


def room_sensors(entry: ConfigEntry) -> set[str]:
    """Every sensor Homedial reads as a room: room items (and their backups), or the old lists."""
    out = set()
    for se in entry.subentries.values():
        if se.subentry_type == SUBENTRY_ROOM:
            out |= {e for e in (se.data.get(ROOM_SENSOR), se.data.get(ROOM_BACKUP)) if e}
    if not out:
        out = set({**entry.data, **entry.options}.get(CONF_ROOMS) or [])
    return out


def sources_schema(hass: HomeAssistant) -> vol.Schema:
    """First screen: the thermostat and the rooms. Each room becomes a room item with weight 1,
    exactly like "+ Add room"; weights, live weights and backups are set on the room later."""
    return vol.Schema({
        vol.Required(CONF_UNDERLYING): _thermostat_picker(hass),
        vol.Required(CONF_ROOMS): _room_picker(hass, multiple=True),
        vol.Optional(CONF_PROTECTED_ROOM): _room_picker(hass),
    })


def control_fields(hass: HomeAssistant) -> dict:
    """Every limit and tuning field, flat. The first-run screen groups them into sections;
    Configure splits them across its menu."""
    c = _celsius(hass)
    u = _unit(c)
    dft = defaults_for(c)
    D = lambda k: {"default": dft[k]}            # noqa: E731
    T = lambda k: _temp_num(k, c)                # noqa: E731
    return {
        vol.Required(CONF_SETPOINT_RESOLUTION, **D(CONF_SETPOINT_RESOLUTION)): _num(0.1, 2.0, 0.1, u),
        vol.Required(CONF_MIN_WRITE_STEP, **D(CONF_MIN_WRITE_STEP)): _num(0.1, 2.0, 0.1, u),
        vol.Required(CONF_SETPOINT_CLAMP, **D(CONF_SETPOINT_CLAMP)): T(CONF_SETPOINT_CLAMP),
        vol.Required(CONF_MIN_WRITE_INTERVAL, **D(CONF_MIN_WRITE_INTERVAL)): _num(0.0, 60.0, 0.5, "min"),
        vol.Required(CONF_CONTROL_UNDERLYING_MODE, **D(CONF_CONTROL_UNDERLYING_MODE)): selector.BooleanSelector(),
        vol.Required(CONF_FREEZE_LIMIT, **D(CONF_FREEZE_LIMIT)): T(CONF_FREEZE_LIMIT),
        vol.Required(CONF_OVERHEAT_LIMIT, **D(CONF_OVERHEAT_LIMIT)): T(CONF_OVERHEAT_LIMIT),
        # the floor switch: the only way to say "no floor" (clearing the number falls back to the default)
        vol.Required(CONF_PROTECTED_FLOOR_ENABLED, **D(CONF_PROTECTED_FLOOR_ENABLED)): selector.BooleanSelector(),
        vol.Optional(CONF_PROTECTED_FLOOR, **D(CONF_PROTECTED_FLOOR)): T(CONF_PROTECTED_FLOOR),
        vol.Optional(CONF_PROTECTED_FLOOR_ENTITY): _ENTITY(selector.EntitySelectorConfig(domain="sensor")),
        vol.Optional(CONF_PROTECTED_FLOOR_ENABLE_ENTITY): _ENTITY(selector.EntitySelectorConfig(domain=["binary_sensor", "input_boolean"])),
        vol.Required(CONF_OFFSET_CLAMP_LOW, **D(CONF_OFFSET_CLAMP_LOW)): T(CONF_OFFSET_CLAMP_LOW),
        vol.Required(CONF_OFFSET_CLAMP_HIGH, **D(CONF_OFFSET_CLAMP_HIGH)): T(CONF_OFFSET_CLAMP_HIGH),
        vol.Optional(CONF_LATENT_SOURCE): _ENTITY(_SENSOR_TEMP),
        vol.Required(CONF_LATENT_CEILING, **D(CONF_LATENT_CEILING)): T(CONF_LATENT_CEILING),
        vol.Required(CONF_LATENT_SPAN, **D(CONF_LATENT_SPAN)): T(CONF_LATENT_SPAN),
        vol.Required(CONF_LATENT_MAX_DEPRESSION, **D(CONF_LATENT_MAX_DEPRESSION)): T(CONF_LATENT_MAX_DEPRESSION),
        vol.Optional(CONF_UNDERLYING_OFFSET_ENTITY): _ENTITY(selector.EntitySelectorConfig(domain=["sensor", "input_number", "number"])),
        vol.Required(CONF_UNDERLYING_OFFSET_CLAMP_LOW, **D(CONF_UNDERLYING_OFFSET_CLAMP_LOW)): T(CONF_UNDERLYING_OFFSET_CLAMP_LOW),
        vol.Required(CONF_UNDERLYING_OFFSET_CLAMP_HIGH, **D(CONF_UNDERLYING_OFFSET_CLAMP_HIGH)): T(CONF_UNDERLYING_OFFSET_CLAMP_HIGH),
    }


# First-run limits screen: safety up front, the rest folded into two collapsed sections.
CONTROL_TOP = (CONF_FREEZE_LIMIT, CONF_OVERHEAT_LIMIT, CONF_PROTECTED_FLOOR_ENABLED, CONF_PROTECTED_FLOOR,
               CONF_CONTROL_UNDERLYING_MODE)
CONTROL_SECTIONS = {
    "humidity": (CONF_LATENT_SOURCE, CONF_LATENT_CEILING, CONF_LATENT_SPAN, CONF_LATENT_MAX_DEPRESSION),
    "advanced": (CONF_SETPOINT_RESOLUTION, CONF_MIN_WRITE_STEP, CONF_SETPOINT_CLAMP, CONF_MIN_WRITE_INTERVAL,
                 CONF_PROTECTED_FLOOR_ENTITY, CONF_PROTECTED_FLOOR_ENABLE_ENTITY,
                 CONF_OFFSET_CLAMP_LOW, CONF_OFFSET_CLAMP_HIGH, CONF_UNDERLYING_OFFSET_ENTITY,
                 CONF_UNDERLYING_OFFSET_CLAMP_LOW, CONF_UNDERLYING_OFFSET_CLAMP_HIGH),
}


def control_schema(hass: HomeAssistant) -> vol.Schema:
    fields = {str(k): (k, v) for k, v in control_fields(hass).items()}
    out = {fields[k][0]: fields[k][1] for k in CONTROL_TOP}
    for name, keys in CONTROL_SECTIONS.items():
        # no default on the section itself: the form only fills a section's fields from their
        # own defaults when the section has none (with default={} they showed empty)
        out[vol.Required(name)] = section(
            vol.Schema({fields[k][0]: fields[k][1] for k in keys}), {"collapsed": True})
    return vol.Schema(out)


def _flatten_control(user_input: dict) -> dict:
    out = {k: v for k, v in user_input.items() if k not in CONTROL_SECTIONS}
    for name in CONTROL_SECTIONS:
        out.update(user_input.get(name) or {})
    return out


TRUST_SCHEMA = vol.Schema({
    vol.Required(CONF_STALE_SENSOR_MIN, default=defaults_for(False)[CONF_STALE_SENSOR_MIN]): _num(1, 720, 1, "min"),
    vol.Required(CONF_FROZEN_MIN, default=defaults_for(False)[CONF_FROZEN_MIN]): _num(1, 1440, 1, "min"),
})


def validate_sources(data: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    rooms = data.get(CONF_ROOMS) or []
    if not rooms:
        errors[CONF_ROOMS] = "no_rooms"
    protected = data.get(CONF_PROTECTED_ROOM)
    if protected and protected not in rooms:
        errors[CONF_PROTECTED_ROOM] = "protected_not_in_rooms"
    return errors


def validate_control(data: dict[str, Any]) -> dict[str, str]:
    """Reject configurations that are internally impossible. Each rule is a defect that shipped once."""
    errors: dict[str, str] = {}
    if data[CONF_MIN_WRITE_STEP] > data[CONF_SETPOINT_RESOLUTION]:
        errors[CONF_MIN_WRITE_STEP] = "min_step_above_resolution"
    if data[CONF_SETPOINT_CLAMP] < data[CONF_SETPOINT_RESOLUTION]:
        errors[CONF_SETPOINT_CLAMP] = "clamp_below_resolution"
    if data[CONF_OFFSET_CLAMP_LOW] >= data[CONF_OFFSET_CLAMP_HIGH]:
        errors[CONF_OFFSET_CLAMP_LOW] = "offset_clamp_inverted"
    if data[CONF_FREEZE_LIMIT] >= data[CONF_OVERHEAT_LIMIT]:
        errors[CONF_FREEZE_LIMIT] = "safety_limits_inverted"
    if data.get(CONF_LATENT_SOURCE) and data.get(CONF_LATENT_MAX_DEPRESSION, 0) > data[CONF_SETPOINT_CLAMP]:
        errors[CONF_LATENT_MAX_DEPRESSION] = "latent_exceeds_clamp"
    lo, hi = data.get(CONF_UNDERLYING_OFFSET_CLAMP_LOW), data.get(CONF_UNDERLYING_OFFSET_CLAMP_HIGH)
    if lo is not None and hi is not None and lo >= hi:
        errors[CONF_UNDERLYING_OFFSET_CLAMP_LOW] = "offset_clamp_inverted"
    floor = data.get(CONF_PROTECTED_FLOOR)
    if data.get(CONF_PROTECTED_FLOOR_ENABLED, True) and floor is not None and floor < data[CONF_FREEZE_LIMIT]:
        errors[CONF_PROTECTED_FLOOR] = "floor_below_freeze"
    return errors


def validate_trust(data: dict[str, Any]) -> dict[str, str]:
    """frozen_minutes must exceed stale_sensor_minutes, or a healthy sensor sitting at a steady
    temperature is dropped before a silent one is."""
    return {CONF_FROZEN_MIN: "frozen_below_stale"} if data[CONF_FROZEN_MIN] <= data[CONF_STALE_SENSOR_MIN] else {}


def _entry_title(hass: HomeAssistant, underlying: str) -> str:
    """One Homedial keeps the plain name; its entity IDs keep the old form (const.id_base). A second one, on
    another thermostat, is named after that thermostat so the two can be told apart."""
    if not hass.config_entries.async_entries(DOMAIN):
        return PRODUCT
    st = hass.states.get(underlying)
    name = (st.attributes.get("friendly_name") if st else None) or underlying
    return f"{PRODUCT} ({name})"


class DLabsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Three steps: what to control, limits, sensor trust. The rooms picked in step 1 become
    room items you can add to, edit or remove later without setting anything up again."""

    VERSION = 2

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    def _form(self, step_id, schema, user_input, errors):
        # keep what the user typed when a step fails validation, so the error sits next to it
        return self.async_show_form(step_id=step_id, errors=errors,
                                    data_schema=self.add_suggested_values_to_schema(schema, user_input or {}))

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = {**validate_sources(user_input), **underlying_errors(self.hass, user_input.get(CONF_UNDERLYING))}
            if not errors:
                self._data.update(user_input)
                return await self.async_step_control()
        return self._form("user", sources_schema(self.hass), user_input, errors)

    async def async_step_control(self, user_input=None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            flat = _flatten_control(user_input)
            errors = {**validate_control(flat), **dew_point_errors(self.hass, flat.get(CONF_LATENT_SOURCE))}
            if flat.get(CONF_LATENT_SOURCE) and flat[CONF_LATENT_SOURCE] in (self._data.get(CONF_ROOMS) or []):
                errors[CONF_LATENT_SOURCE] = "dew_point_is_a_room"
            # an error on a field inside a folded section is shown at the top, where it is seen
            errors = {(k if k in CONTROL_TOP else "base"): v for k, v in errors.items()}
            if not errors:
                self._data.update(flat)
                return await self.async_step_trust()
        return self._form("control", control_schema(self.hass), user_input, errors)

    async def async_step_trust(self, user_input=None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = validate_trust(user_input)
            if not errors:
                self._data.update(user_input)
                from . import room_subentry_data, room_title
                protected = self._data.get(CONF_PROTECTED_ROOM)
                # the same room item "+ Add room" makes with its defaults
                rooms = [{ROOM_SENSOR: eid, ROOM_PROTECTED: eid == protected, ROOM_WEIGHT: 1.0}
                         for eid in self._data.get(CONF_ROOMS) or []]
                data = {k: v for k, v in self._data.items() if k not in LEGACY_KEYS}
                data[CONF_TEMP_UNIT] = _unit(_celsius(self.hass))
                subentries = [{"subentry_type": SUBENTRY_ROOM, "data": room_subentry_data(r),
                               "title": room_title(self.hass, r), "unique_id": r[ROOM_SENSOR]} for r in rooms]
                return self.async_create_entry(title=_entry_title(self.hass, data[CONF_UNDERLYING]),
                                               data=data, subentries=subentries)
        return self._form("trust", TRUST_SCHEMA, user_input, errors)

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry: ConfigEntry) -> dict[str, type[ConfigSubentryFlow]]:
        return {SUBENTRY_ROOM: RoomFlow}

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return DLabsOptionsFlow()


LEGACY_KEYS = (CONF_ROOMS, CONF_PROTECTED_ROOM, CONF_ROOM_WEIGHTS, CONF_ROOM_WEIGHT_ENTITIES, CONF_ROOM_FALLBACK_ENTITIES)


# ---------------------------------------------------------------------------------------------
# Rooms: "+ Add room" on the integration page. Simple up front, advanced folded away.
# ---------------------------------------------------------------------------------------------
def room_schema(hass: HomeAssistant) -> vol.Schema:
    temp = _room_picker(hass)
    return vol.Schema({
        vol.Required(ROOM_SENSOR): temp,
        vol.Optional(ROOM_NAME): selector.TextSelector(),
        vol.Required(ROOM_PROTECTED, default=False): selector.BooleanSelector(),
        vol.Required(ROOM_ADVANCED): section(vol.Schema({
            vol.Optional(ROOM_WEIGHT, default=1.0): _num(0.1, 10.0, 0.1),
            vol.Optional(ROOM_WEIGHT_ENTITY): _ENTITY(selector.EntitySelectorConfig(domain=["sensor", "input_number", "number"])),
            vol.Optional(ROOM_BACKUP): temp,
        }), {"collapsed": True}),
    })


def _flatten_room(user_input: dict) -> dict:
    adv = user_input.get(ROOM_ADVANCED) or {}
    room = {ROOM_SENSOR: user_input[ROOM_SENSOR], ROOM_PROTECTED: bool(user_input.get(ROOM_PROTECTED)),
            ROOM_WEIGHT: float(adv.get(ROOM_WEIGHT) or 1.0)}
    if (user_input.get(ROOM_NAME) or "").strip():
        room[ROOM_NAME] = user_input[ROOM_NAME].strip()
    for k in (ROOM_WEIGHT_ENTITY, ROOM_BACKUP):
        if adv.get(k):
            room[k] = adv[k]
    return room


def _nest_room(room: dict) -> dict:
    return {ROOM_SENSOR: room.get(ROOM_SENSOR), ROOM_NAME: room.get(ROOM_NAME, ""),
            ROOM_PROTECTED: bool(room.get(ROOM_PROTECTED)),
            ROOM_ADVANCED: {k: room[k] for k in (ROOM_WEIGHT, ROOM_WEIGHT_ENTITY, ROOM_BACKUP) if room.get(k) is not None}}


class RoomFlow(ConfigSubentryFlow):
    """Add or edit one room. Changes apply at once: Homedial reloads, keeps its mode and target."""

    def _check(self, room: dict, editing_id: str | None) -> dict[str, str]:
        errors: dict[str, str] = {}
        entry = self._get_entry()
        for sid, se in entry.subentries.items():
            if se.subentry_type != SUBENTRY_ROOM or sid == editing_id:
                continue
            if se.data.get(ROOM_SENSOR) == room[ROOM_SENSOR]:
                errors[ROOM_SENSOR] = "room_sensor_in_use"
            if room[ROOM_PROTECTED] and se.data.get(ROOM_PROTECTED):
                errors[ROOM_PROTECTED] = "one_protected_room"
        if room.get(ROOM_BACKUP) == room[ROOM_SENSOR]:
            errors[ROOM_ADVANCED] = "backup_is_same_sensor"
        dew = {**entry.data, **entry.options}.get(CONF_LATENT_SOURCE)
        if dew and room[ROOM_SENSOR] == dew:
            errors[ROOM_SENSOR] = "dew_point_is_a_room"
        elif dew and room.get(ROOM_BACKUP) == dew:
            errors[ROOM_ADVANCED] = "dew_point_is_a_room"
        return errors

    def _title(self, room: dict) -> str:
        from . import room_title
        return room_title(self.hass, room)

    async def async_step_user(self, user_input=None) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            room = _flatten_room(user_input)
            errors = self._check(room, None)
            if not errors:
                return self.async_create_entry(title=self._title(room), data=room, unique_id=room[ROOM_SENSOR])
        return self.async_show_form(step_id="user", errors=errors,
                                    data_schema=self.add_suggested_values_to_schema(room_schema(self.hass), user_input or {}))

    async def async_step_reconfigure(self, user_input=None) -> SubentryFlowResult:
        sub = self._get_reconfigure_subentry()
        errors: dict[str, str] = {}
        if user_input is not None:
            room = _flatten_room(user_input)
            errors = self._check(room, sub.subentry_id)
            if not errors:
                return self.async_update_and_abort(self._get_entry(), sub, data=room,
                                                   title=self._title(room), unique_id=room[ROOM_SENSOR])
        shown = user_input or _nest_room(dict(sub.data))
        return self.async_show_form(step_id="reconfigure", errors=errors,
                                    data_schema=self.add_suggested_values_to_schema(room_schema(self.hass), shown))


# ---------------------------------------------------------------------------------------------
# Configure: a menu, so a first-time user sees four short screens, not one long one.
# ---------------------------------------------------------------------------------------------
STEP_KEYS = {
    "thermostat": (CONF_UNDERLYING, CONF_CONTROL_UNDERLYING_MODE),
    "safety": (CONF_FREEZE_LIMIT, CONF_OVERHEAT_LIMIT, CONF_PROTECTED_FLOOR_ENABLED, CONF_PROTECTED_FLOOR,
               CONF_PROTECTED_FLOOR_ENTITY, CONF_PROTECTED_FLOOR_ENABLE_ENTITY),
    "humidity": (CONF_LATENT_SOURCE, CONF_LATENT_CEILING, CONF_LATENT_SPAN, CONF_LATENT_MAX_DEPRESSION),
    "advanced": (CONF_SETPOINT_RESOLUTION, CONF_MIN_WRITE_STEP, CONF_SETPOINT_CLAMP, CONF_MIN_WRITE_INTERVAL,
                 CONF_OFFSET_CLAMP_LOW, CONF_OFFSET_CLAMP_HIGH, CONF_UNDERLYING_OFFSET_ENTITY,
                 CONF_UNDERLYING_OFFSET_CLAMP_LOW, CONF_UNDERLYING_OFFSET_CLAMP_HIGH,
                 CONF_STALE_SENSOR_MIN, CONF_FROZEN_MIN),
}


class DLabsOptionsFlow(OptionsFlow):
    def _merged(self) -> dict:
        """What is in force, in today's unit (Home Assistant may have switched °F/°C since the
        last save and Homedial not reloaded yet)."""
        c = _celsius(self.hass)
        return {**defaults_for(c), **values_in_unit(self.config_entry.data, self.config_entry.options, c)}

    def _saved_options(self, merged: dict) -> dict:
        """The options to build on, in today's unit. If the first-setup values are in the old
        unit, their converted copies go into options too, so nothing is read in the wrong unit."""
        c = _celsius(self.hass)
        data, options = self.config_entry.data, self.config_entry.options
        data_c = _saved_celsius(data, c)
        new = _convert_block(options, _saved_celsius(options, data_c), c)
        if data_c != c:
            for k in data:
                if k in ABS_RANGE_F or k in DELTA_RANGE_F:
                    new.setdefault(k, merged.get(k))
        new[CONF_TEMP_UNIT] = _unit(c)
        return new

    def _schema(self, step: str) -> vol.Schema:
        full = {**control_fields(self.hass), **TRUST_SCHEMA.schema,
                vol.Required(CONF_UNDERLYING): _thermostat_picker(self.hass)}
        keep = STEP_KEYS[step]
        return vol.Schema({k: v for k, v in full.items() if str(k) in keep})

    async def async_step_init(self, user_input=None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="init", menu_options=["thermostat", "safety", "humidity", "advanced"])

    async def _step(self, step: str, user_input):
        errors: dict[str, str] = {}
        merged = self._merged()
        if user_input is not None:
            new = self._saved_options(merged)
            for k in STEP_KEYS[step]:
                # a cleared optional field is saved as None, so it really clears (a missing key
                # would fall back to the value from the first setup)
                new[k] = user_input.get(k)
            test = {**merged, **new}
            errors = {**validate_control(test), **validate_trust(test),
                      **dew_point_errors(self.hass, test.get(CONF_LATENT_SOURCE) if step == "humidity" else None),
                      **({CONF_LATENT_SOURCE: "dew_point_is_a_room"} if step == "humidity" and test.get(CONF_LATENT_SOURCE)
                         and test[CONF_LATENT_SOURCE] in room_sensors(self.config_entry) else {}),
                      **underlying_errors(self.hass, test.get(CONF_UNDERLYING) if step == "thermostat" else None,
                                          self.config_entry.entry_id)}
            errors = {k: v for k, v in errors.items() if k in STEP_KEYS[step]} or (
                {"base": next(iter(errors.values()))} if errors else {})
            if not errors:
                return self.async_create_entry(data=new)
        shown = user_input or {k: v for k, v in merged.items() if v is not None}
        return self.async_show_form(step_id=step, errors=errors,
                                    data_schema=self.add_suggested_values_to_schema(self._schema(step), shown))

    async def async_step_thermostat(self, user_input=None) -> ConfigFlowResult:
        return await self._step("thermostat", user_input)

    async def async_step_safety(self, user_input=None) -> ConfigFlowResult:
        return await self._step("safety", user_input)

    async def async_step_humidity(self, user_input=None) -> ConfigFlowResult:
        return await self._step("humidity", user_input)

    async def async_step_advanced(self, user_input=None) -> ConfigFlowResult:
        return await self._step("advanced", user_input)
