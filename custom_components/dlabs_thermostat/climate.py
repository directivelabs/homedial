# Homedial · Copyright (c) 2026 Directive Labs, LLC
"""The Homedial climate entity.

Commands a setpoint on an underlying ("real") thermostat. Runs NO control loop of its own:
the real thermostat already has a deadband, minimum run times and staging, and a second
regulator in series with it produces hunting and integral windup.

Hardened 2026-09-30 (product 0.2.0):
  - latent lever acts in COOL only (it used to lower HEAT setpoints)
  - °C installs get °C defaults; precision follows the configured resolution
  - offers only the modes the real thermostat supports; never commands outside its min/max
  - optionally puts the real thermostat in the matching mode (incl. out of heat/cool range mode)
  - at least 30 s between any two writes (protects cloud thermostats); waits are re-checked
    when they end instead of at the next 5-minute heartbeat
  - publishes its status to diagnostic sensors (guard blocking, fallback, reason, ...)
Product 0.2.1 (2026-10-04):
  - uses the real thermostat's own step size when it is coarser than ours (never asks a
    whole-degree thermostat for 72.5)
  - if the thermostat does not keep a setpoint after 2 writes, stops re-sending it for
    10 minutes and says why (protects cloud thermostats from endless rewrites)
Private beta (2026-10-05 launch audit):
  - a tripped guard backs the real thermostat off (cool: up, heat: down) instead of freezing
    the setpoint; it never adds demand and never changes the thermostat's mode while blocking
  - guards are reported, not blocking, while Homedial is Off
  - the protected floor acts in COOL only, and is HELD when the protected room is unreadable
  - a rejected service call is paced (30 s, then doubling) and explained, never an unhandled error
  - the last write time survives reloads and restarts, so pacing cannot be bypassed
  - a mode change sends a demand-reducing setpoint right away; a live weight of 0 excludes a room
"""
from __future__ import annotations

import asyncio
import logging
import math
from datetime import timedelta

from homeassistant.components.climate import (
    ATTR_CURRENT_TEMPERATURE, ATTR_HVAC_MODES, ATTR_MAX_TEMP, ATTR_MIN_TEMP, ATTR_TARGET_TEMP_STEP, ATTR_TEMPERATURE,
    ClimateEntity, ClimateEntityFeature, HVACAction, HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PRECISION_HALVES, PRECISION_TENTHS, PRECISION_WHOLE, UnitOfTemperature
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import (
    async_call_later, async_track_state_change_event, async_track_time_interval,
)
from homeassistant.helpers.restore_state import RestoredExtraData, RestoreEntity
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import TemperatureConverter

from .const import (
    CONF_CONTROL_UNDERLYING_MODE, CONF_FREEZE_LIMIT, CONF_FROZEN_MIN, CONF_LATENT_CEILING,
    CONF_LATENT_MAX_DEPRESSION, CONF_LATENT_SOURCE, CONF_LATENT_SPAN, CONF_MIN_WRITE_INTERVAL,
    CONF_MIN_WRITE_STEP, CONF_OFFSET_CLAMP_HIGH, CONF_OFFSET_CLAMP_LOW, CONF_OVERHEAT_LIMIT,
    CONF_PROTECTED_FLOOR, CONF_PROTECTED_FLOOR_ENABLE_ENTITY, CONF_PROTECTED_FLOOR_ENABLED,
    CONF_PROTECTED_FLOOR_ENTITY, CONF_SETPOINT_CLAMP, PRODUCT, id_base,
    CONF_SETPOINT_RESOLUTION, CONF_STALE_SENSOR_MIN, CONF_UNDERLYING,
    CONF_UNDERLYING_OFFSET_CLAMP_HIGH, CONF_UNDERLYING_OFFSET_CLAMP_LOW,
    CONF_UNDERLYING_OFFSET_ENTITY, DOMAIN, MANUFACTURER, ROOM_BACKUP, ROOM_PROTECTED, ROOM_SENSOR,
    ROOM_NAME, ROOM_WEIGHT, ROOM_WEIGHT_ENTITY, SIGNAL_UPDATE, SUBENTRY_ROOM, WRITE_FAIL_BACKOFF_MAX,
    WRITE_FLOOR_SECONDS, defaults_for, rooms_from_legacy,
)
from .controller import (
    Reading, blend, evaluate_guards, latent_depression, protected_floor_setpoint,
    SUMMARY_MAX, should_write, step_toward, summarize,
)

_LOGGER = logging.getLogger(__name__)

# A backstop so a missed state event cannot leave the controller idle, not the mechanism.
HEARTBEAT = timedelta(minutes=5)
READBACK_GRACE = 180.0          # seconds to wait for a thermostat to report a value we sent
NOT_STICKING_TRIES = 2          # re-sends of the same value that may fail to stick before pausing
NOT_STICKING_PAUSE = 600.0      # seconds to stop re-sending a value the thermostat will not keep
_MODE_WORD = {HVACMode.COOL: "cool", HVACMode.HEAT: "heat"}


def device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(identifiers={(DOMAIN, entry.entry_id)}, name=entry.title,
                      manufacturer=MANUFACTURER, model=PRODUCT)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([DLabsThermostat(hass, entry)])


class DLabsThermostat(ClimateEntity, RestoreEntity):
    """A setpoint commander, not a regulator."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_should_poll = False
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
    )

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self._entry = entry
        celsius = hass.config.units.temperature_unit == UnitOfTemperature.CELSIUS
        self._cfg = {**defaults_for(celsius), **entry.data, **entry.options}
        # One dict per room: from the room items (0.3.0), or the old positional lists.
        subs = [{**se.data, "_title": se.title} for se in entry.subentries.values() if se.subentry_type == SUBENTRY_ROOM]
        self._rooms = subs if subs else rooms_from_legacy(self._cfg)
        self._attr_unique_id = entry.entry_id
        self.entity_id = f"climate.{id_base(entry.title)}"   # only a suggestion: a registered ID is kept
        self._attr_device_info = device_info(entry)
        self._attr_hvac_mode = HVACMode.OFF   # ARMED IS OPT-IN. A fresh install never moves equipment.
        self._last_active_mode: HVACMode | None = None
        self._target: float | None = None
        self._control_temp: float | None = None
        self._reasons: list[str] = ["not armed"]
        self._summary: str = "Homedial is off. Your thermostat runs on its own."
        self._summary_warned = False     # log a failed summary once, not every cycle
        self._last_written: float | None = None
        # Time of the last ATTEMPTED write. Restored across reloads and restarts (extra restore
        # data), so a reload can never bypass the 30 s floor or the demand interval.
        self._last_write_ts = None
        self._fail_count = 0                 # consecutive rejected service calls
        self._retry_at = None                # no write before this time after a rejection
        self._last_error = ""
        self._guard_reasons: list[str] = []
        self._last_min_safe: float | None = None   # last floor minimum, held if the room goes dark
        self._blocked = False
        self._latent = 0.0
        self._on_fallback: list[str] = []
        self._recheck = None            # pending "re-evaluate when this wait ends" timer
        self._miss_count = 0                 # re-sends of the last written value that did not stick
        self._miss_counted_for = None        # which write a miss was already counted for
        self._miss_pause_until = None
        # One evaluation at a time, or simultaneous source changes can issue duplicate writes.
        self._lock = asyncio.Lock()

    # -- what we show -------------------------------------------------------
    @property
    def temperature_unit(self) -> str:
        return self.hass.config.units.temperature_unit

    def _resolution(self) -> float:
        """The step we command in: the configured resolution, or the real thermostat's own
        step when that is coarser. Asking a whole-degree thermostat for 72.5 gets it rounded
        to 72 or 73, the readback never matches, and the write repeats forever."""
        res = float(self._cfg[CONF_SETPOINT_RESOLUTION])
        under = self._under()
        try:
            theirs = float(under.attributes.get(ATTR_TARGET_TEMP_STEP)) if under else 0.0
        except (TypeError, ValueError):
            theirs = 0.0
        return max(res, theirs) if theirs > 0 else res

    @property
    def precision(self) -> float:
        """Published precision follows the step we command in. A controller that works in
        half degrees but displays whole degrees makes every button press look broken."""
        res = self._resolution()
        if res >= 1.0:
            return PRECISION_WHOLE
        return PRECISION_HALVES if res >= 0.5 else PRECISION_TENTHS

    @property
    def target_temperature_step(self) -> float:
        return self._resolution()

    def _under(self):
        return self.hass.states.get(self._cfg[CONF_UNDERLYING])

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """Off, plus whichever of cool/heat the real thermostat supports (both if it doesn't say)."""
        under = self._under()
        theirs = (under.attributes.get(ATTR_HVAC_MODES) if under else None) or ["cool", "heat"]
        return [HVACMode.OFF] + [m for m in (HVACMode.COOL, HVACMode.HEAT) if m.value in theirs]

    def _under_limit(self, attr: str, fallback: float) -> float:
        under = self._under()
        try:
            return float(under.attributes.get(attr)) if under and under.attributes.get(attr) is not None else fallback
        except (TypeError, ValueError):
            return fallback

    @property
    def min_temp(self) -> float:
        return self._under_limit(ATTR_MIN_TEMP, super().min_temp)

    @property
    def max_temp(self) -> float:
        return self._under_limit(ATTR_MAX_TEMP, super().max_temp)

    # -- lifecycle ---------------------------------------------------------
    async def async_added_to_hass(self) -> None:
        await self._restore()
        watched = [self._cfg[CONF_UNDERLYING]]
        for r in self._rooms:
            watched += [e for e in (r.get(ROOM_SENSOR), r.get(ROOM_WEIGHT_ENTITY), r.get(ROOM_BACKUP)) if e]
        for key in (CONF_PROTECTED_FLOOR_ENTITY, CONF_PROTECTED_FLOOR_ENABLE_ENTITY,
                    CONF_UNDERLYING_OFFSET_ENTITY, CONF_LATENT_SOURCE):
            if self._cfg.get(key):
                watched.append(self._cfg[key])
        self.async_on_remove(async_track_state_change_event(self.hass, watched, self._on_source_change))
        self.async_on_remove(async_track_time_interval(self.hass, self._on_heartbeat, HEARTBEAT))
        self.async_on_remove(self._cancel_recheck)
        self.hass.data[DOMAIN][self._entry.entry_id]["entity"] = self
        await self._evaluate()

    async def _restore(self) -> None:
        """Come back armed if we were armed before a restart (and OFF if we were OFF).
        A fresh install has no previous state, so it still starts OFF."""
        last = await self.async_get_last_state()
        if last is None:
            return
        extra = await self.async_get_last_extra_data()
        data = extra.as_dict() if extra is not None else {}
        # Home Assistant keeps a removed entity's last state for days and hands it to the next
        # entity with the same ID. State saved by another Homedial (a removed one) is ignored: adding
        # Homedial again must start OFF, not re-arm the old mode and target. State saved before 0.3.4
        # has no setup ID; it counts as another Homedial's when it is older than this entity.
        saved_by = data.get("entry_id")
        reg = self.registry_entry
        if (saved_by is not None and saved_by != self._entry.entry_id) or (
                saved_by is None and reg is not None and last.last_updated < reg.created_at):
            _LOGGER.info("Homedial: ignoring the saved state of a removed Homedial; starting OFF")
            return
        try:
            mode = HVACMode(last.state)
        except ValueError:
            mode = None
        if mode in (HVACMode.OFF, HVACMode.COOL, HVACMode.HEAT):
            self._attr_hvac_mode = mode
        if mode in (HVACMode.COOL, HVACMode.HEAT):
            self._last_active_mode = mode
        prev = last.attributes.get(ATTR_TEMPERATURE)
        if prev is not None:
            try:
                self._target = float(prev)
            except (TypeError, ValueError):
                self._target = None
        ts = dt_util.parse_datetime(data["last_write_ts"]) if data.get("last_write_ts") else None
        if ts is not None:
            self._last_write_ts = min(ts, dt_util.utcnow())     # a clock jump never means "never"
        if data.get("last_written") is not None:
            try:
                self._last_written = float(data["last_written"])
            except (TypeError, ValueError):
                self._last_written = None
        _LOGGER.info("Homedial restored: mode=%s target=%s", self._attr_hvac_mode, self._target)

    @property
    def extra_restore_state_data(self) -> RestoredExtraData:
        return RestoredExtraData({
            "last_write_ts": self._last_write_ts.isoformat() if self._last_write_ts else None,
            "last_written": self._last_written,
            "entry_id": self._entry.entry_id})

    @callback
    def _on_source_change(self, event: Event) -> None:
        self.hass.async_create_task(self._evaluate())

    @callback
    def _on_heartbeat(self, _now) -> None:
        self.hass.async_create_task(self._evaluate())

    @callback
    def _cancel_recheck(self) -> None:
        if self._recheck:
            self._recheck()
            self._recheck = None

    def _recheck_in(self, seconds: float) -> None:
        """Re-evaluate when a wait ends, instead of up to five minutes later at the heartbeat."""
        self._cancel_recheck()

        @callback
        def _fire(_now):
            self._recheck = None
            self.hass.async_create_task(self._evaluate())

        self._recheck = async_call_later(self.hass, max(1.0, seconds) + 0.5, _fire)

    # -- inputs ------------------------------------------------------------
    def _room_specs(self) -> list[tuple[str, float, bool]]:
        """(sensor, weight, protected) per room. A live weight entity wins while it reads >= 0;
        a live 0 leaves the room out of the blend (it is still watched by the guards). An
        unreadable or negative entity falls back to the room's own number (default 1). If every
        live weight reads 0, the configured numbers are used instead. Every path says which."""
        specs, notes, live = [], [], 0
        for r in self._rooms:
            static = float(r.get(ROOM_WEIGHT) or 1.0)
            w = static if static > 0 else 1.0
            ent = r.get(ROOM_WEIGHT_ENTITY)
            if ent:
                v = self._read_raw(ent)
                if v is not None and v >= 0:
                    w, live = v, live + 1
                elif v is not None:
                    notes.append(f"{ent} is negative ({v:g}), using {w:g}")
                else:
                    notes.append(f"{ent} unreadable, using {w:g}")
            specs.append((r[ROOM_SENSOR], w, bool(r.get(ROOM_PROTECTED))))
        if specs and all(w <= 0 for _, w, _ in specs):
            specs = [(eid, (float(r.get(ROOM_WEIGHT) or 1.0) if float(r.get(ROOM_WEIGHT) or 1.0) > 0 else 1.0), p)
                     for (eid, _, p), r in zip(specs, self._rooms)]
            notes.append("every live weight is 0, using the configured weights")
        src = "entities" if live and live == len(self._rooms) else (
            "mixed" if live else ("configured" if any(float(r.get(ROOM_WEIGHT) or 1.0) != 1.0 for r in self._rooms)
                                  else "equal"))
        self._weight_source = src + (f" ({'; '.join(notes)})" if notes else "")
        return specs

    def _protected_floor(self) -> float | None:
        """The floor in force now, or None. An unreadable floor VALUE falls back to the static
        number; an unreadable ENABLE switch keeps the floor on. A broken sensor never means off."""
        if not self._cfg.get(CONF_PROTECTED_FLOOR_ENABLED, True):
            self._floor_source = "disabled in config"
            return None
        gate = self._cfg.get(CONF_PROTECTED_FLOOR_ENABLE_ENTITY)
        gate_note = ""
        if gate:
            st = self.hass.states.get(gate)
            if st is None or st.state in ("unknown", "unavailable"):
                gate_note = f" (gate {gate} unreadable - floor kept)"
            elif str(st.state).lower() in ("off", "false", "no", "closed"):
                self._floor_source = f"disabled by {gate}"
                return None
        static = self._cfg.get(CONF_PROTECTED_FLOOR)
        ent = self._cfg.get(CONF_PROTECTED_FLOOR_ENTITY)
        if not ent:
            self._floor_source = "static" + gate_note
            return None if static is None else float(static)
        live = self._read_raw(ent)
        if live is not None:
            self._floor_source = f"live ({ent})" + gate_note
            return live
        self._floor_source = f"static - {ent} unreadable" + gate_note
        return None if static is None else float(static)

    def _underlying_offset(self) -> float:
        """Held (thermostat reading - blend) correction, clamped. Unreadable = 0.0: a correction
        that cannot be verified must not be invented."""
        ent = self._cfg.get(CONF_UNDERLYING_OFFSET_ENTITY)
        if not ent:
            self._offset_source = "not configured"
            return 0.0
        raw = self._read_raw(ent)
        if raw is None:
            self._offset_source = f"{ent} unreadable - no correction applied"
            return 0.0
        lo = float(self._cfg[CONF_UNDERLYING_OFFSET_CLAMP_LOW])
        hi = float(self._cfg[CONF_UNDERLYING_OFFSET_CLAMP_HIGH])
        held = min(max(raw, lo), hi)
        self._offset_source = (f"{raw:+.2f} from {ent} CLAMPED to {held:+.2f} [{lo:+.2f}, {hi:+.2f}]"
                               if abs(held - raw) > 1e-9 else f"{raw:+.2f} from {ent}")
        return held

    def _room_fallbacks(self) -> list[str | None]:
        fbs = [r.get(ROOM_BACKUP) or None for r in self._rooms]
        self._fallback_source = "configured" if any(fbs) else "none configured"
        return fbs

    def _read_room(self, entity_id: str, fallback: str | None) -> tuple[float | None, str | None]:
        value = self._read(entity_id)
        if value is not None:
            return value, None
        if fallback and fallback != entity_id:          # a room pointed at itself has no fallback
            sub = self._read(fallback)                   # a fallback is a measurement: same trust rules
            if sub is not None:
                return sub, fallback
        return None, None

    def _read_dew_point(self, entity_id: str) -> tuple[float | None, str | None]:
        """The dew point in Home Assistant's unit, or (None, why) when its unit is not °F or °C.
        Setup checks the unit once; a sensor can change unit later, and a reading in the wrong
        unit must never lower the cooling setpoint. °F and °C are converted, anything else skipped."""
        value = self._read(entity_id)
        if value is None:
            return None, None
        unit = self.hass.states.get(entity_id).attributes.get("unit_of_measurement")
        if unit not in (UnitOfTemperature.FAHRENHEIT, UnitOfTemperature.CELSIUS):
            return None, (f"latent: dew point sensor reports {unit or 'no unit'}, not °F or °C - "
                          "no depression applied")
        ours = self.hass.config.units.temperature_unit
        return (value if unit == ours else TemperatureConverter.convert(value, unit, ours)), None

    def _read_raw(self, entity_id: str) -> float | None:
        """A SETTING (weight, floor, held offset): no freshness check. A weight that has not
        changed in two hours is a weight that is working."""
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        try:
            return float(state.state)
        except (TypeError, ValueError):
            return None

    def _read(self, entity_id: str) -> float | None:
        """A MEASUREMENT: untrusted returns None, never 0.0. Stale = not reported recently;
        frozen = reported but not changed in a long time. Two different failures."""
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        now = dt_util.utcnow()
        limit = self._cfg.get(CONF_STALE_SENSOR_MIN)
        if limit and (now - state.last_reported).total_seconds() / 60.0 > float(limit):
            return None
        frozen = self._cfg.get(CONF_FROZEN_MIN)
        if frozen and (now - state.last_changed).total_seconds() / 60.0 > float(frozen):
            return None
        try:
            return float(state.state)
        except (TypeError, ValueError):
            return None

    # -- the decision ------------------------------------------------------
    async def _evaluate(self) -> None:
        async with self._lock:
            await self._evaluate_locked()

    def _publish(self, reasons: list[str]) -> None:
        if self._blocked:     # the guard always leads: the extras safety alert quotes the first part
            reasons = self._guard_reasons + [r for r in reasons if r not in self._guard_reasons]
        self._reasons = reasons
        try:      # words only: the summary must never stop the state below from being written
            self._summary = summarize(reasons, blocked=self._blocked, mode=_MODE_WORD.get(self._attr_hvac_mode),
                                      names=self._plain_names())
        except Exception:  # noqa: BLE001
            if not self._summary_warned:
                _LOGGER.warning("Homedial: could not build the plain summary; showing the technical reason instead",
                                exc_info=True)
                self._summary_warned = True
            first = str(reasons[0]) if reasons else "All clear"
            self._summary = ((first[:1].upper() + first[1:]).rstrip(".")[:SUMMARY_MAX - 1] + ".")
        self.async_write_ha_state()
        async_dispatcher_send(self.hass, SIGNAL_UPDATE.format(self._entry.entry_id))

    def _plain_names(self) -> dict[str, str]:
        """Names people know their sensors by, for the plain summary: the room's own name, else
        the sensor's friendly name. Covers rooms, backups and the dew point sensor."""
        names: dict[str, str] = {}
        ids = [r.get(ROOM_SENSOR) for r in self._rooms] + [r.get(ROOM_BACKUP) for r in self._rooms]
        ids.append(self._cfg.get(CONF_LATENT_SOURCE))
        for eid in [i for i in ids if i]:
            st = self.hass.states.get(eid)
            if st is not None and st.attributes.get("friendly_name"):
                names[eid] = str(st.attributes["friendly_name"])   # a YAML or template name may not be text
        for r in self._rooms:
            title = r.get("_title") or r.get(ROOM_NAME)
            if title and r.get(ROOM_SENSOR):
                names[r[ROOM_SENSOR]] = str(title)
        return names

    def _write_floor_wait(self, since: float | None) -> str | None:
        """None if a write may go now; else the reason, with a re-check scheduled. Covers the
        30 s floor between any two writes and the longer wait after a rejected write."""
        if self._retry_at is not None:
            left = (self._retry_at - dt_util.utcnow()).total_seconds()
            if left > 0:
                self._recheck_in(left)
                return (f"waiting {left:.0f} s before trying the thermostat again - it rejected the last "
                        f"change: {self._last_error}")
        if since is None or since >= WRITE_FLOOR_SECONDS:
            return None
        self._recheck_in(WRITE_FLOOR_SECONDS - since)
        return f"spacing writes - {WRITE_FLOOR_SECONDS - since:.0f} s until the next is allowed"

    def _seconds_since_write(self) -> float | None:
        return None if self._last_write_ts is None else (dt_util.utcnow() - self._last_write_ts).total_seconds()

    async def _send(self, service: str, data: dict) -> str | None:
        """Call the real thermostat. None on success; else the reason. A rejected call still
        counts as a write for pacing (30 s, then doubling up to WRITE_FAIL_BACKOFF_MAX), so a
        cloud error or rate limit is never answered with a retry on every sensor update."""
        self._last_write_ts = dt_util.utcnow()
        try:
            await self.hass.services.async_call(
                "climate", service, {"entity_id": self._cfg[CONF_UNDERLYING], **data}, blocking=True)
        except Exception as err:  # noqa: BLE001 - any failure must be paced and shown, never raised
            self._fail_count += 1
            wait = min(WRITE_FLOOR_SECONDS * 2 ** (self._fail_count - 1), WRITE_FAIL_BACKOFF_MAX)
            self._retry_at = self._last_write_ts + timedelta(seconds=wait)
            self._last_error = str(err) or type(err).__name__
            self._recheck_in(wait)
            _LOGGER.warning("Homedial: %s on %s failed: %s", service, self._cfg[CONF_UNDERLYING], err)
            return f"thermostat rejected the change: {self._last_error} - trying again in {wait:.0f} s"
        self._fail_count, self._retry_at = 0, None
        return None

    @staticmethod
    def _reduces_demand(mode: str | None, new: float, live: float) -> bool:
        return (mode == "cool" and new > live) or (mode == "heat" and new < live)

    async def _evaluate_locked(self) -> None:
        reasons: list[str] = []
        specs = self._room_specs()
        readings, on_fallback = [], []
        for (eid, weight, protected), fb in zip(specs, self._room_fallbacks()):
            value, used = self._read_room(eid, fb)
            if used is not None:
                on_fallback.append(f"{eid} on {used}")
            readings.append(Reading(eid, value, weight, protected))
        self._on_fallback = on_fallback
        if on_fallback:
            reasons.append("fallback: " + ", ".join(on_fallback))   # said every cycle, never hidden
        control, live_rooms, total_rooms = blend(readings)
        self._control_temp = control
        readable = [r.value for r in readings if r.value is not None]
        if control is None and not readable:
            self._blocked = False                                   # no readable room, nothing can trip
            return self._publish(["no control temperature - every room source is untrusted"])
        # A room left out of the blend (live weight 0) is still watched by the guards, so a
        # missing blend must not skip them: guards run below on every readable room.
        counted = sum(1 for r in readings if r.weight > 0)          # a live weight of 0 is left out
        if live_rooms < counted:
            reasons.append(f"{live_rooms} of {counted} rooms live")

        mode = _MODE_WORD.get(self._attr_hvac_mode)
        armed = mode is not None

        # GUARDS, before any write of any kind. While Homedial is Off it controls nothing, so a
        # tripped guard is REPORTED but is not "blocking" (no problem sensor, no Alert).
        verdict = evaluate_guards(readings, self._cfg.get(CONF_FREEZE_LIMIT), self._cfg.get(CONF_OVERHEAT_LIMIT), mode=mode)
        self._blocked = verdict.block and armed
        self._guard_reasons = verdict.reasons if self._blocked else []
        noted = (verdict.reasons + ["noted, not blocking - Homedial is off"]) if verdict.block and not armed else []
        if armed and not self._blocked and verdict.reasons:
            reasons.extend(verdict.reasons)                         # e.g. "overheat noted - a room is freezing"
        if control is None and not self._blocked:
            return self._publish(["no control temperature - every room in the blend is untrusted"] + noted)

        target = self._target
        floor_held = False
        self._latent = 0.0
        if not self._blocked:
            if target is None:
                return self._publish(["no target set"] + noted)

            # LATENT LEVER (cool only). Applied BEFORE the floor, so the floor can veto it.
            latent_src = self._cfg.get(CONF_LATENT_SOURCE)
            if latent_src:
                dew, bad_unit = self._read_dew_point(latent_src)
                if bad_unit:
                    if mode == "cool":                          # the lever only acts in cool
                        reasons.append(bad_unit)
                else:
                    drop, why = latent_depression(
                        dew, float(self._cfg[CONF_LATENT_CEILING]),
                        float(self._cfg[CONF_LATENT_SPAN]), float(self._cfg[CONF_LATENT_MAX_DEPRESSION]), mode)
                    if drop > 0:
                        target -= drop
                        self._latent = drop
                    if why:
                        reasons.append(why)

            # PROTECTED FLOOR (cool only: it exists to stop over-cooling one room).
            floor = self._protected_floor() if mode == "cool" else None
            has_protected = any(r.protected for r in readings)
            protected = next((r for r in readings if r.protected and r.value is not None), None)
            if floor is not None and protected is not None:
                offset, min_safe = protected_floor_setpoint(
                    control, protected.value, float(floor),
                    float(self._cfg[CONF_OFFSET_CLAMP_LOW]), float(self._cfg[CONF_OFFSET_CLAMP_HIGH]))
                self._last_min_safe = min_safe
                if min_safe > target:
                    if self._latent > 0:
                        reasons.append(f"latent depression overruled by the floor - {protected.name} "
                                       f"would have gone below {floor:.2f}")
                    reasons.append(f"raised to {min_safe:.2f} - {protected.name} floor {floor:.2f} with offset {offset:+.2f}")
                    target = min_safe
            elif floor is not None and has_protected:
                # The protected room cannot be read: HOLD the floor. Keep the last safe minimum
                # and never lower the cooling setpoint (checked below). A dead sensor must never
                # cause more cooling of the room it protects.
                floor_held = True
                if self._last_min_safe is not None and self._last_min_safe > target:
                    target = self._last_min_safe
                reasons.append("floor held - protected room unreadable, not lowering the cooling setpoint")

            # SCALE TRANSLATION, applied last so everything above works on the blend's scale.
            xlat = self._underlying_offset()
            if xlat != 0.0:
                target = round(target + xlat, 2)
                reasons.append(f"translated {xlat:+.2f} onto the thermostat's own scale")

            if not armed:
                return self._publish(["not armed"] + noted + reasons)

        under = self._under()
        if under is None:
            return self._publish([f"cannot find the thermostat {self._cfg[CONF_UNDERLYING]}"] + reasons)
        if under.state in ("unavailable", "unknown"):
            return self._publish(["thermostat unavailable - waiting"] + reasons)

        since = self._seconds_since_write()

        # MODE: the real thermostat must be in the mode we are armed in.
        if under.state != mode:
            if self._blocked:
                # Switching the thermostat INTO cool (or heat) while that guard is tripped could
                # only add the demand the guard is there to stop. But a thermostat left in a mode
                # that can still do that work (auto/heat_cool, or dry for cooling) must be stopped:
                # turning it off is the only demand-reducing move there, and when the guard clears
                # the normal path below puts it back in Homedial's mode.
                risky = {"cool": ("heat_cool", "auto", "dry"), "heat": ("heat_cool", "auto")}[mode]
                theirs = under.attributes.get(ATTR_HVAC_MODES) or []
                if (under.state in risky and self._cfg.get(CONF_CONTROL_UNDERLYING_MODE, True)
                        and (not theirs or "off" in theirs)):
                    if (wait := self._write_floor_wait(since)) is not None:
                        return self._publish([wait] + reasons)
                    if (err := await self._send("set_hvac_mode", {"hvac_mode": "off"})) is not None:
                        return self._publish([err] + reasons)
                    self._recheck_in(WRITE_FLOOR_SECONDS)
                    work = "cooling" if mode == "cool" else "heating"
                    return self._publish([f"turned the thermostat off (it was in {under.state} and could keep {work})"]
                                         + reasons)
                return self._publish([f"not changing the thermostat's mode while a guard is blocking "
                                      f"(it is in {under.state})"] + reasons)
            theirs = under.attributes.get(ATTR_HVAC_MODES) or []
            if self._cfg.get(CONF_CONTROL_UNDERLYING_MODE, True) and (not theirs or mode in theirs):
                if (wait := self._write_floor_wait(since)) is not None:
                    return self._publish([wait] + reasons)
                if (err := await self._send("set_hvac_mode", {"hvac_mode": mode})) is not None:
                    return self._publish([err] + reasons)
                done = f"set the thermostat to {mode} (it was {under.state})"
                # The old setpoint now means the wrong thing (cool 78 becomes heat 78). If the
                # target REDUCES demand from there, send it at once instead of after 30 s of
                # running the wrong way. Only once the thermostat shows the new mode: sent any
                # earlier it would land on the old mode's setpoint.
                after = self._under()
                after_sp = after.attributes.get(ATTR_TEMPERATURE) if after is not None else None
                if after is not None and after.state == mode and after_sp is not None:
                    res = self._resolution()
                    sp = min(max(round(round(target / res) * res, 2), self.min_temp), self.max_temp)
                    if (self._reduces_demand(mode, sp, float(after_sp))
                            and should_write(sp, float(after_sp), float(self._cfg[CONF_MIN_WRITE_STEP]))):
                        if (err := await self._send("set_temperature", {"temperature": sp})) is not None:
                            return self._publish([done, err] + reasons)
                        self._last_written = sp
                        self._clear_miss()
                        done += f" and its setpoint to {sp:.2f} in the same step"
                self._recheck_in(WRITE_FLOOR_SECONDS)
                return self._publish([done] + reasons)
            return self._publish([f"waiting - the thermostat is in {under.state}, armed for {mode}; "
                                  "set it to match or turn on mode control"] + reasons)

        live = under.attributes.get(ATTR_TEMPERATURE)
        if live is None:
            return self._publish(["cannot read the thermostat's setpoint"] + reasons)
        live = float(live)

        res = self._resolution()
        if res > float(self._cfg[CONF_SETPOINT_RESOLUTION]):
            reasons.append(f"using the thermostat's {res:g}-degree steps")
        lo, hi = self.min_temp, self.max_temp
        if self._blocked:
            # BACK OFF: walk the real thermostat's setpoint away from demand, one clamped step
            # per allowed write, until it is clearly past the house temperature (so the equipment
            # stops) - never further, so a naturally cool room can't park the system at its max.
            margin = 1.0 if self.hass.config.units.temperature_unit == UnitOfTemperature.CELSIUS else 2.0
            # Clear the warmest (cool) / coldest (heat) temperature we know of by the margin, so the
            # equipment stops whichever sensor the thermostat goes by. Room values are moved onto
            # the thermostat's own scale first. Without a usable reading from the thermostat itself
            # we can't know where it stops, so fall back to its own limit (the old, conservative walk).
            try:
                cur = float(under.attributes.get(ATTR_CURRENT_TEMPERATURE))
                cur = cur if math.isfinite(cur) else None
            except (TypeError, ValueError):
                cur = None
            if cur is None:
                target = hi if mode == "cool" else lo
            else:
                xlat = self._underlying_offset()
                seen = [cur] + [float(v) + xlat for v in ([control] if control is not None else []) + readable]
                if mode == "cool":
                    target = min(hi, math.ceil((max(seen) + margin) / res - 1e-9) * res)
                else:
                    target = max(lo, math.floor((min(seen) - margin) / res + 1e-9) * res)
        commanded = step_toward(target, live, float(self._cfg[CONF_SETPOINT_CLAMP]), res)
        if commanded < lo or commanded > hi:
            if not self._blocked:
                reasons.append(f"kept within the thermostat's range {lo:.1f}-{hi:.1f}")
            commanded = min(max(commanded, lo), hi)
        if self._blocked:
            if not self._reduces_demand(mode, commanded, live):
                past = "above" if mode == "cool" else "below"
                return self._publish([f"backed off - holding at {live:.2f}, {past} the house temperature "
                                      "or at the thermostat's limit"] + reasons)
        elif abs(commanded - target) > 1e-9:
            reasons.append(f"stepping {commanded:.2f} on the way to {target:.2f}")

        if floor_held and commanded < live:
            return self._publish([f"holding at {live:.2f}"] + reasons)

        if not should_write(commanded, live, float(self._cfg[CONF_MIN_WRITE_STEP])):
            self._clear_miss()
            return self._publish([f"holding at {live:.2f}"] + reasons)

        # NOT STICKING. The same value was already sent and the thermostat still shows something
        # else. Cloud thermostats can take minutes to report back, so first wait READBACK_GRACE;
        # after that each re-send counts as a miss, and after NOT_STICKING_TRIES misses we stop
        # re-sending that value for NOT_STICKING_PAUSE and say why.
        if (not self._blocked and self._last_written is not None and abs(commanded - self._last_written) < 1e-9
                and since is not None):
            if since < READBACK_GRACE:
                self._recheck_in(READBACK_GRACE - since)
                return self._publish([f"waiting for the thermostat to show {commanded:.2f} "
                                      f"(sent {since:.0f} s ago, it shows {live:.2f})"] + reasons)
            if self._miss_counted_for != self._last_write_ts:
                self._miss_counted_for = self._last_write_ts
                self._miss_count += 1
            if self._miss_count >= NOT_STICKING_TRIES:
                now = dt_util.utcnow()
                if self._miss_pause_until is None:
                    self._miss_pause_until = now + timedelta(seconds=NOT_STICKING_PAUSE)
                if now < self._miss_pause_until:
                    left = (self._miss_pause_until - now).total_seconds()
                    self._recheck_in(left)
                    return self._publish([
                        f"not sticking - the thermostat still shows {live:.2f} after {self._miss_count + 1} "
                        f"sends of {commanded:.2f}; pausing {left / 60.0:.0f} min. Check its step size, limits or "
                        "schedule"] + reasons)
                self._miss_count, self._miss_pause_until = NOT_STICKING_TRIES - 1, None   # pause over: one more try
        elif self._last_written is not None:
            self._clear_miss()

        # MINIMUM WRITE INTERVAL: only the demand-INCREASING direction waits. A write that
        # reduces demand (cool: up, heat: down) - every cool floor raise and guard backoff -
        # never does. The 30 s floor below still applies to every write.
        interval = float(self._cfg.get(CONF_MIN_WRITE_INTERVAL) or 0.0)
        if interval > 0 and since is not None:
            waited = since / 60.0
            if not self._reduces_demand(mode, commanded, live) and waited < interval:
                self._recheck_in((interval - waited) * 60.0)
                return self._publish([f"holding {live:.2f} - {interval - waited:.1f} min left of the "
                                      f"{interval:.1f} min write interval (wanted {commanded:.2f})"] + reasons)

        if (wait := self._write_floor_wait(since)) is not None:
            return self._publish([wait] + reasons)
        if (err := await self._send("set_temperature", {"temperature": commanded})) is not None:
            return self._publish([err] + reasons)
        self._last_written = commanded
        if not self._blocked and abs(commanded - target) > 1e-9:
            self._recheck_in(WRITE_FLOOR_SECONDS)       # keep stepping toward the target
        elif self._blocked:
            self._recheck_in(WRITE_FLOOR_SECONDS)       # keep backing off until the guard clears
        else:
            self._recheck_in(READBACK_GRACE)            # come back and check the thermostat kept it
        _LOGGER.debug("Homedial wrote %.2f to %s", commanded, self._cfg[CONF_UNDERLYING])
        if self._blocked:
            what = "raised the cooling setpoint" if mode == "cool" else "lowered the heating setpoint"
            stop = "cooling" if mode == "cool" else "heating"
            return self._publish([f"backing off - {what} to {commanded:.2f} to stop {stop}"] + reasons)
        self._publish([f"wrote {commanded:.2f}"] + reasons)

    # -- climate interface -------------------------------------------------
    @property
    def current_temperature(self) -> float | None:
        return self._control_temp

    @property
    def target_temperature(self) -> float | None:
        return self._target

    @property
    def hvac_action(self) -> HVACAction | None:
        under = self._under()
        raw = under.attributes.get("hvac_action") if under else None
        try:
            return HVACAction(raw) if raw is not None else None
        except ValueError:
            return None

    @property
    def status(self) -> dict:
        """What the diagnostic sensors show."""
        return {"reason": " | ".join(self._reasons) if self._reasons else "all clear",
                "summary": self._summary,
                "blocked": self._blocked, "on_fallback": bool(self._on_fallback),
                "control_temperature": self._control_temp, "latent_depression": self._latent,
                "last_written": self._last_written,
                "not_sticking": self._miss_count >= NOT_STICKING_TRIES}

    @property
    def extra_state_attributes(self) -> dict:
        specs = self._room_specs()
        total = sum(w for _, w, _ in specs) or 1.0
        since = self._seconds_since_write()
        return {
            "reason": " | ".join(self._reasons) if self._reasons else "all clear",
            "summary": self._summary,
            "control_temperature": self._control_temp,
            "last_written": self._last_written,
            "min_write_interval": self._cfg.get(CONF_MIN_WRITE_INTERVAL),
            "minutes_since_write": None if since is None else round(since / 60.0, 1),
            "underlying": self._cfg[CONF_UNDERLYING],
            "control_underlying_mode": self._cfg.get(CONF_CONTROL_UNDERLYING_MODE, True),
            "blocked_by_guard": self._blocked,
            "rooms": [eid for eid, _, _ in specs],
            "room_weights": {eid: round(w / total, 4) for eid, w, _ in specs},
            "weight_source": getattr(self, "_weight_source", "unknown"),
            "room_fallbacks": [r.get(ROOM_BACKUP) for r in self._rooms],
            "room_names": {r[ROOM_SENSOR]: r.get("_title") or r.get(ROOM_NAME) for r in self._rooms
                           if r.get("_title") or r.get(ROOM_NAME)},
            "fallback_source": getattr(self, "_fallback_source", "unknown"),
            "on_fallback": self._on_fallback,
            "latent_depression": self._latent,
            "latent_source": self._cfg.get(CONF_LATENT_SOURCE),
            "protected_room": next((r[ROOM_SENSOR] for r in self._rooms if r.get(ROOM_PROTECTED)), None),
            "protected_floor": self._protected_floor(),
            "protected_floor_static": self._cfg.get(CONF_PROTECTED_FLOOR),
            "protected_floor_entity": self._cfg.get(CONF_PROTECTED_FLOOR_ENTITY),
            "protected_floor_source": getattr(self, "_floor_source", "unknown"),
            "protected_floor_enabled": self._cfg.get(CONF_PROTECTED_FLOOR_ENABLED, True),
            "protected_floor_enable_entity": self._cfg.get(CONF_PROTECTED_FLOOR_ENABLE_ENTITY),
            "underlying_offset": self._underlying_offset(),
            "underlying_offset_entity": self._cfg.get(CONF_UNDERLYING_OFFSET_ENTITY),
            "underlying_offset_source": getattr(self, "_offset_source", "unknown"),
            "setpoint_step": self._resolution(),
            # COOL or HEAT, whichever Homedial was last armed in (kept while it is OFF). Auto in the
            # extras resumes it when Homedial's OFF has also turned the real thermostat off.
            "last_active_mode": self._last_active_mode.value if self._last_active_mode else None,
            "not_sticking": self._miss_count >= NOT_STICKING_TRIES,
        }

    def _clear_miss(self) -> None:
        self._miss_count, self._miss_counted_for, self._miss_pause_until = 0, None, None

    async def async_set_temperature(self, **kwargs) -> None:
        if (temp := kwargs.get(ATTR_TEMPERATURE)) is not None:
            self._target = float(temp)
            self._clear_miss()              # a new target from a person is always worth a try
            await self._evaluate()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        self._attr_hvac_mode = hvac_mode
        if hvac_mode in (HVACMode.COOL, HVACMode.HEAT):
            self._last_active_mode = hvac_mode
        if hvac_mode == HVACMode.OFF:
            async with self._lock:              # never interleaved with a write from _evaluate
                await self._turn_underlying_off()
        await self._evaluate()

    async def _turn_underlying_off(self) -> None:
        """OFF means off, wherever it is picked (Homedial card, voice, automation, the extras mode
        picker): Homedial is already disarmed, so it can't switch the system back on; then the real
        thermostat goes off, only when Homedial controls its mode and it offers OFF. Setup, restore
        and removal never come through here, so they never change the real thermostat."""
        if not self._cfg.get(CONF_CONTROL_UNDERLYING_MODE, True):
            return
        under = self._under()
        if under is None or under.state in ("off", "unavailable", "unknown"):
            return
        if "off" not in (under.attributes.get(ATTR_HVAC_MODES) or []):
            return
        await self._send("set_hvac_mode", {"hvac_mode": "off"})

    async def async_turn_on(self) -> None:
        """Arm the mode we were last armed in; else the real thermostat's current cool/heat
        mode; else cool. Never Home Assistant's default, which can arm HEAT in August."""
        if self._last_active_mode:
            return await self.async_set_hvac_mode(self._last_active_mode)
        under = self._under()
        if under is not None and under.state in ("cool", "heat") and HVACMode(under.state) in self.hvac_modes:
            return await self.async_set_hvac_mode(HVACMode(under.state))
        await self.async_set_hvac_mode(HVACMode.COOL if HVACMode.COOL in self.hvac_modes else self.hvac_modes[-1])
