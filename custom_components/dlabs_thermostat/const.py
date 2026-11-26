# Homedial · Copyright (c) 2026 Directive Labs, LLC
"""Constants for Homedial (hardened 2026-09-30).

Every default below is an EXAMPLE with its reasoning, tuned on one real house. They are
safe starting points, not facts about your home; the setup screens let you change each one.
Temperature values are stored here in °F and converted for °C installs (see defaults_for).
"""
from __future__ import annotations

DOMAIN = "dlabs_thermostat"
MANUFACTURER = "Directive Labs"
SIGNAL_UPDATE = "dlabs_thermostat_update_{}"     # .format(entry_id); diagnostics listen to this

# --- names -----------------------------------------------------------------
# The product shows as Homedial (renamed 2026-10-31). Hidden names keep the old form: new setups
# pin their entity IDs to what the old name gave (climate.dlabs_thermostat, ..._reason), because
# dashboards, the extras and support notes use them.
PRODUCT = "Homedial"
OLD_PRODUCT = "DLabs Thermostat"         # the name before 2026-10-31
# Each diagnostic's entity ID ending, as the English name gave it before the rename.
ID_SUFFIX = {"control_temperature": "control_temperature", "reason": "reason",
             "latent_depression": "humidity_help", "guard_blocking": "safety_guard_blocking",
             "on_fallback": "using_fallback_sensor"}


def old_default_title(title: str) -> bool:
    """True for the titles setup used to give: "DLabs Thermostat" and "DLabs Thermostat (<thermostat>)"."""
    return title == OLD_PRODUCT or (title.startswith(OLD_PRODUCT + " (") and title.endswith(")"))


def id_base(title: str) -> str:
    """The object ID a new setup's entities start with: the old name's form for the default titles."""
    from homeassistant.util import slugify
    if title == PRODUCT or (title.startswith(PRODUCT + " (") and title.endswith(")")):
        title = OLD_PRODUCT + title[len(PRODUCT):]
    return slugify(title)

# --- sources ---------------------------------------------------------------
CONF_UNDERLYING = "underlying_climate"      # the real thermostat we command
CONF_ROOMS = "rooms"                        # temperature sensors blended into one control temperature
CONF_PROTECTED_ROOM = "protected_room"      # the room the protected floor keeps warm enough
# Comma-separated weights, positional against CONF_ROOMS. Blank = equal weights.
CONF_ROOM_WEIGHTS = "room_weights"
# Optional live weights, positional against CONF_ROOMS: read each room's weight from an entity
# (e.g. an input_number) so an automation can shift priority, for example when a room is empty.
CONF_ROOM_WEIGHT_ENTITIES = "room_weight_entities"
# Optional fallback sensors, positional against CONF_ROOMS. When a room's own sensor is dead,
# stale or frozen, read this one instead of dropping the room. Point a room at ITSELF to say
# "no fallback". If the fallback needs a calibration offset, put it in a template sensor.
CONF_ROOM_FALLBACK_ENTITIES = "room_fallback_entities"

# --- control ---------------------------------------------------------------
CONF_SETPOINT_CLAMP = "setpoint_clamp"      # most the setpoint may move in one write
CONF_MIN_WRITE_STEP = "min_write_step"      # never larger than the thermostat's resolution
CONF_SETPOINT_RESOLUTION = "setpoint_resolution"
# Minutes between writes that INCREASE demand. Writes that reduce demand (floor raises, guard
# backoffs) are never delayed. Without this, one clamped step re-triggers the next within
# milliseconds and the clamp stops being a ramp. 0 disables.
CONF_MIN_WRITE_INTERVAL = "min_write_interval"
# Seconds between ANY two writes, in either direction. Fixed, not a setting: it protects
# cloud thermostats whose services limit how often they can be written.
WRITE_FLOOR_SECONDS = 30
# When the thermostat rejects a change (cloud error, rate limit), the wait before the next try
# doubles from WRITE_FLOOR_SECONDS up to this many seconds. Fixed, not a setting.
WRITE_FAIL_BACKOFF_MAX = 600
# When armed in cool or heat, put the real thermostat in the same mode if it isn't already
# (including taking it out of an auto/heat-cool range mode). On by default so a new install
# works with any brand; turn off if another automation owns the thermostat's mode.
CONF_CONTROL_UNDERLYING_MODE = "control_underlying_mode"

# --- protected floor ------------------------------------------------------
CONF_PROTECTED_FLOOR = "protected_floor"
# Optional live floor (e.g. a sensor that picks a summer or winter value). The static number
# above is the fallback when this cannot be read.
CONF_PROTECTED_FLOOR_ENTITY = "protected_floor_entity"
# The floor is ON for a fresh install and can be turned off explicitly here.
CONF_PROTECTED_FLOOR_ENABLED = "protected_floor_enabled"
# Optional on/off entity (e.g. "room is occupied"). While it reads off, the floor does not apply.
# An UNREADABLE switch keeps the floor in force: a broken sensor never turns a safety limit off.
CONF_PROTECTED_FLOOR_ENABLE_ENTITY = "protected_floor_enable_entity"
CONF_OFFSET_CLAMP_LOW = "offset_clamp_low"
CONF_OFFSET_CLAMP_HIGH = "offset_clamp_high"

# --- scale translation (advanced, optional) ----------------------------------
# A thermostat regulates on ITS OWN reading, which is not the blended house temperature. Point
# this at an entity holding (thermostat reading - blend), SAMPLED ONCE PER CYCLE AND HELD, and
# the target is translated onto the thermostat's scale. It must be held, never live: a live
# difference closes a positive-feedback loop. Leave empty for no translation.
CONF_UNDERLYING_OFFSET_ENTITY = "underlying_offset_entity"
# Asymmetric on purpose: in cooling the negative side is the over-cooling side, so less rope.
CONF_UNDERLYING_OFFSET_CLAMP_LOW = "underlying_offset_clamp_low"
CONF_UNDERLYING_OFFSET_CLAMP_HIGH = "underlying_offset_clamp_high"

# --- latent (dew point) lever, COOL ONLY -----------------------------------------
# Lowers the cooling setpoint a little when the air is humid, so the AC runs longer and dries
# the house. Works on DEW POINT, not relative humidity (RH rises as a house cools, so an
# RH-driven cooler chases its own tail). Applied BEFORE the protected floor, so the floor can
# veto it. Never acts in heat: lowering a heating setpoint would only make the house colder.
CONF_LATENT_SOURCE = "latent_dew_point"
CONF_LATENT_CEILING = "latent_ceiling"       # depression starts above this dew point
CONF_LATENT_SPAN = "latent_span"             # degrees above the ceiling for full depression
CONF_LATENT_MAX_DEPRESSION = "latent_max_depression"

# --- safety ------------------------------------------------------------------
CONF_FREEZE_LIMIT = "freeze_limit"          # any room at/below this blocks cooling
CONF_OVERHEAT_LIMIT = "overheat_limit"      # any room at/above this blocks heating

# --- sensor trust ------------------------------------------------------------
CONF_STALE_SENSOR_MIN = "stale_sensor_minutes"   # not REPORTED for this long = untrusted
CONF_FROZEN_MIN = "frozen_minutes"               # value not CHANGED for this long = untrusted

# --- defaults (°F) ------------------------------------------------------------
DEFAULTS_F = {
    CONF_SETPOINT_CLAMP: 2.0,
    CONF_MIN_WRITE_STEP: 0.5,
    CONF_SETPOINT_RESOLUTION: 0.5,
    CONF_MIN_WRITE_INTERVAL: 10.0,      # example basis: a site that saw 38 writes in 24 h without it
    CONF_CONTROL_UNDERLYING_MODE: True,
    CONF_OFFSET_CLAMP_LOW: -3.0,
    CONF_OFFSET_CLAMP_HIGH: 6.0,
    CONF_LATENT_CEILING: 53.0,          # example: comfortable indoor dew point ceiling
    CONF_LATENT_SPAN: 4.0,
    CONF_LATENT_MAX_DEPRESSION: 2.0,    # same size as a typical thermostat "overcool" setting
    CONF_STALE_SENSOR_MIN: 45,          # about 3x a typical sensor's reporting interval
    CONF_FROZEN_MIN: 120,               # must stay longer than stale_sensor_minutes
    CONF_FREEZE_LIMIT: 62.0,
    CONF_OVERHEAT_LIMIT: 82.0,
    CONF_PROTECTED_FLOOR: 66.0,         # 4 degrees above the freeze limit
    CONF_PROTECTED_FLOOR_ENABLED: True,
    CONF_UNDERLYING_OFFSET_CLAMP_LOW: -1.25,
    CONF_UNDERLYING_OFFSET_CLAMP_HIGH: 1.75,
}

# Which settings are absolute temperatures vs temperature DIFFERENCES (they convert differently).
ABSOLUTE_TEMPS = {CONF_LATENT_CEILING, CONF_FREEZE_LIMIT, CONF_OVERHEAT_LIMIT, CONF_PROTECTED_FLOOR}
DELTA_TEMPS = {CONF_SETPOINT_CLAMP, CONF_OFFSET_CLAMP_LOW, CONF_OFFSET_CLAMP_HIGH, CONF_LATENT_SPAN,
               CONF_LATENT_MAX_DEPRESSION, CONF_UNDERLYING_OFFSET_CLAMP_LOW, CONF_UNDERLYING_OFFSET_CLAMP_HIGH}
# Resolution and write step are thermostat steps, not conversions: 0.5 is right in both units.


def _round_half(v: float) -> float:
    return round(v * 2) / 2


def defaults_for(celsius: bool) -> dict:
    """Defaults in the instance's unit. °C values are rounded to the nearest 0.5."""
    if not celsius:
        return dict(DEFAULTS_F)
    out = {}
    for k, v in DEFAULTS_F.items():
        if k in ABSOLUTE_TEMPS:
            out[k] = _round_half((v - 32.0) * 5.0 / 9.0)
        elif k in DELTA_TEMPS:
            out[k] = round(v * 5.0 / 9.0 * 4) / 4      # quarter-degree steps for small deltas
        else:
            out[k] = v
    return out

# --- rooms as their own items (product 0.3.0) ----------------------------------
# Each room is a config SUBENTRY of type "room", added with "+ Add room" on the integration page.
# Replaces the positional lists above (rooms / room_weights / room_weight_entities /
# room_fallback_entities / protected_room), which are migrated automatically (entry version 2).
SUBENTRY_ROOM = "room"
ROOM_NAME = "name"
ROOM_SENSOR = "sensor"
ROOM_PROTECTED = "protected"
ROOM_ADVANCED = "advanced"                 # collapsed section in the room form
ROOM_WEIGHT = "weight"                     # share of the blend; default 1 (equal)
ROOM_WEIGHT_ENTITY = "weight_entity"       # optional live weight (e.g. an input_number)
ROOM_BACKUP = "backup_sensor"              # optional sensor read when the room's own is dead
LEGACY_ROOM_KEYS = (CONF_ROOMS, CONF_PROTECTED_ROOM, CONF_ROOM_WEIGHTS,
                    CONF_ROOM_WEIGHT_ENTITIES, CONF_ROOM_FALLBACK_ENTITIES)


def rooms_from_legacy(cfg: dict) -> list[dict]:
    """Turn the old positional room lists into one dict per room. Lists of the wrong length
    are ignored (never attach a weight or backup to the wrong room), exactly as before."""
    rooms = list(cfg.get(CONF_ROOMS) or [])
    out = []
    weights = []
    raw = cfg.get(CONF_ROOM_WEIGHTS)
    if raw is not None and str(raw).strip():
        try:
            weights = [float(p) for p in str(raw).replace(" ", "").split(",") if p != ""]
        except ValueError:
            weights = []
    if len(weights) != len(rooms) or any(w <= 0 for w in weights):
        weights = [1.0] * len(rooms)
    went = list(cfg.get(CONF_ROOM_WEIGHT_ENTITIES) or [])
    if len(went) != len(rooms):
        went = [None] * len(rooms)
    fbs = list(cfg.get(CONF_ROOM_FALLBACK_ENTITIES) or [])
    if len(fbs) != len(rooms):
        fbs = [None] * len(rooms)
    for eid, w, we, fb in zip(rooms, weights, went, fbs):
        out.append({ROOM_SENSOR: eid, ROOM_PROTECTED: eid == cfg.get(CONF_PROTECTED_ROOM),
                    ROOM_WEIGHT: w, ROOM_WEIGHT_ENTITY: we,
                    ROOM_BACKUP: fb if fb and fb != eid else None})
    return out
