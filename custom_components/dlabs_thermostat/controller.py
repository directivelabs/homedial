# Homedial · Copyright (c) 2026 Directive Labs, LLC
"""Pure decision logic for Homedial.

Nothing here touches Home Assistant. Every function is a pure function of its arguments,
so the whole control policy is unit-tested without an instance.

Hardened 2026-09-30 (product 0.2.0): unused functions removed (demand index, forecast
projection, equipment fault, trust/decision records); the latent lever now takes the mode
and never acts outside COOL; the guard verdict no longer carries always-empty fields.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


def clamp(value: float, low: float, high: float) -> float:
    return max(min(value, high), low)


def ramp(value: float, null_point: float, full_point: float) -> float:
    """Normalise `value` onto 0..1 between null_point and full_point. Inverted or equal
    endpoints give 0.0 rather than an error: a mis-set tuning value must degrade, not explode."""
    if full_point <= null_point:
        return 0.0
    return clamp((value - null_point) / (full_point - null_point), 0.0, 1.0)


@dataclass(frozen=True)
class Reading:
    """One room's contribution. `value` is None when the source is untrusted."""

    name: str
    value: float | None
    weight: float
    protected: bool = False


def blend(readings: list[Reading]) -> tuple[float | None, int, int]:
    """Weighted mean over LIVE rooms only, renormalized.

    An untrusted room is dropped and the remaining weights rescaled. It does NOT count as
    zero and it cannot veto the blend: one dead sensor must never stop the system.
    """
    num = den = 0.0
    live = 0
    for r in readings:
        if r.value is None or r.weight <= 0:
            continue
        num += r.value * r.weight
        den += r.weight
        live += 1
    if den <= 0:
        return None, 0, len(readings)
    return num / den, live, len(readings)


def protected_floor_setpoint(
    control_temperature: float, protected_value: float, floor: float,
    offset_low: float, offset_high: float,
) -> tuple[float, float]:
    """Offset-aware floor. Returns (offset, minimum safe setpoint).

    A floor on a ROOM and a setpoint for the HOUSE are different numbers. When the protected
    room runs colder than the blend, clamping the setpoint to the floor does nothing, so we
    raise it by how far the room sits below the blend. The offset is clamped: an unbounded
    correction term is how a guard becomes the fault.
    """
    offset = clamp(control_temperature - protected_value, offset_low, offset_high)
    return offset, floor + offset


def latent_depression(
    dew_point: float | None, ceiling: float, span: float, max_depression: float, mode: str | None,
) -> tuple[float, str | None]:
    """Degrees to lower the COOLING setpoint to buy runtime for drying. (degrees, reason).

    A continuous ramp, not a switch: nothing at or below `ceiling`, the full `max_depression`
    at `ceiling + span`, linear between, re-evaluated every cycle, so it releases on its own.

    COOL ONLY. In heat, lowering the setpoint does not dry anything; it only makes the house
    colder. (Found in the 2026-09-10 audit, proven by test 2026-09-30, fixed here.)

    FAILS TO ZERO. A dead dew point sensor must never CAUSE cooling.
    """
    if mode != "cool":
        return 0.0, None
    if dew_point is None:
        return 0.0, "latent: no dew point reading, no depression applied"
    if span <= 0 or max_depression <= 0:
        return 0.0, None
    fraction = ramp(dew_point, ceiling, ceiling + span)
    if fraction <= 0:
        return 0.0, None
    degrees = round(max_depression * fraction, 2)
    return degrees, (
        f"latent: dew point {dew_point:.2f} over ceiling {ceiling:.2f}, lowering setpoint {degrees:.2f}"
    )


def step_toward(target: float, live: float, clamp_per_write: float, resolution: float) -> float:
    """Move toward target, rate-limited, quantized to the thermostat's resolution.
    A clamped value is WRITTEN, not refused; it steps again next cycle.
    The per-write limit is never smaller than one resolution step: a 0.5 clamp on a
    whole-degree thermostat would otherwise round back to `live` and stall forever."""
    limit = max(clamp_per_write, resolution)
    delta = clamp(target - live, -limit, limit)
    return round(round((live + delta) / resolution) * resolution, 2)


def should_write(commanded: float, live: float, min_step: float) -> bool:
    """Gate on a threshold never finer than the thermostat can express; otherwise the readback
    never matches and the loop holds forever believing it has more to do."""
    return abs(commanded - live) >= min_step


# ---------------------------------------------------------------------------
# Safety guards: computed from the room readings, so a fresh install has freeze and
# overheat protection with no extra setup. Every guard says WHY in plain language.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GuardVerdict:
    block: bool
    reasons: list[str]


def freeze_guard(readings: list[Reading], limit: float | None) -> tuple[bool, list[str]]:
    """Any LIVE room at or below `limit`. An untrusted sensor can neither trigger nor mask it."""
    if limit is None:
        return False, []
    hits = [r for r in readings if r.value is not None and r.value <= limit]
    return bool(hits), [f"FREEZE - {r.name} at {r.value:.2f} is at or below {limit:.2f}" for r in hits]


def overheat_guard(readings: list[Reading], limit: float | None) -> tuple[bool, list[str]]:
    """Any LIVE room at or above `limit`."""
    if limit is None:
        return False, []
    hits = [r for r in readings if r.value is not None and r.value >= limit]
    return bool(hits), [f"OVERHEAT - {r.name} at {r.value:.2f} is at or above {limit:.2f}" for r in hits]


def evaluate_guards(
    readings: list[Reading], freeze_limit: float | None, overheat_limit: float | None, mode: str | None = None,
) -> GuardVerdict:
    """Combine the thermal guards into one verdict.

    `mode` ("cool", "heat" or None) decides which guard may BLOCK. The freeze guard stops
    COOLING a room that is already too cold; in heat it would block the very heat that fixes
    it. The overheat guard is the mirror image. mode=None is the conservative case: either
    guard blocks. Both conditions are always REPORTED, even when not blocking.
    """
    reasons: list[str] = []
    froze, r = freeze_guard(readings, freeze_limit)
    reasons += r
    hot, r = overheat_guard(readings, overheat_limit)
    reasons += r
    freeze_blocks = froze and mode in (None, "cool")
    # A freezing room outranks an overheating one: in Heat, cutting the heat would make the
    # freezing room colder, so the overheat guard does not block while any room is freezing.
    overheat_blocks = hot and mode in (None, "heat") and not froze
    if froze and not freeze_blocks:
        reasons.append("freeze condition noted but not blocking - not cooling")
    if hot and not overheat_blocks:
        reasons.append("overheat condition noted but not blocking - " + ("a room is freezing" if froze and mode == "heat" else "not heating"))
    return GuardVerdict(block=bool(freeze_blocks or overheat_blocks), reasons=reasons)


# ---------------------------------------------------------------------------
# Plain-language summary (wording pass, 2026-10-26). The reason list above stays the
# technical record (support, tests and the extras safety alert read it); `summarize` turns it
# into one or two short sentences for people: room names instead of sensor IDs, whole or
# one-decimal degrees, no capitals or jargon. It only READS the reasons, so it can never change
# what Homedial does.
# ---------------------------------------------------------------------------

_NUM = r"(-?\d+(?:\.\d+)?)"
SUMMARY_MAX = 255


def _deg(text: str) -> str:
    """'66.00' -> '66', '91.50' -> '91.5', '-0.04' -> '0' (never '-0')."""
    v = round(float(text), 1) + 0.0     # + 0.0 turns -0.0 into 0.0
    return f"{v:.0f}" if v == int(v) else f"{v:.1f}"


def _named(eid: str, names: dict[str, str]) -> str:
    """A room's own name; never the sensor ID people would have to decode."""
    n = names.get(eid)
    if isinstance(n, str) and n and not re.fullmatch(r"[a-z_]+\.[a-z0-9_]+", n):   # a name that is just the ID is no name
        return n
    tail = eid.split(".", 1)[-1].replace("_", " ").strip()
    return tail[:1].upper() + tail[1:] if tail else eid


def _guard_sentence(text: str, names: dict[str, str]) -> str | None:
    m = re.match(rf"^(FREEZE|OVERHEAT) - (\S+) at {_NUM} is at or (?:below|above) {_NUM}$", text)
    if not m:
        return None
    word = "very cold" if m.group(1) == "FREEZE" else "very warm"
    return f"{_named(m.group(2), names)} is {word} ({_deg(m.group(3))}°, limit {_deg(m.group(4))}°)."


def _lead_sentence(text: str, mode: str | None, names: dict[str, str], target: str | None) -> str:
    doing = {"cool": "Cooling", "heat": "Heating"}.get(mode or "", "Working")
    toward = f" toward {_deg(target)}°" if target is not None else ""
    stop = "cooling" if mode == "cool" else "heating"
    rules: list[tuple[str, object]] = [
        (r"^not armed$", "Homedial is off. Your thermostat runs on its own."),
        (r"^no target set$", "No target yet. Pick Cool or Heat and a temperature."),
        (r"^no control temperature", "No room reading to trust right now, so Homedial is not changing anything."),
        (rf"^holding {_NUM} - {_NUM} min left of the {_NUM} min write interval \(wanted {_NUM}\)$",
         lambda m: f"{doing}{toward}. Next step in {max(1, round(float(m.group(2))))} min "
                   "(Homedial changes the thermostat slowly)."),
        (rf"^holding at {_NUM}$", lambda m: f"Holding the thermostat at {_deg(m.group(1))}°."),
        (rf"^wrote {_NUM}$", lambda m: f"Set the thermostat to {_deg(m.group(1))}°"
                                       + (f", on the way to {_deg(target)}°." if target is not None else ".")),
        (r"^thermostat unavailable", "Can't reach your thermostat. Waiting for it to come back."),
        (r"^cannot find the thermostat", "Can't find your thermostat in Home Assistant. Check Homedial's settings."),
        (r"^cannot read the thermostat's setpoint", "Can't read your thermostat's temperature setting. Waiting."),
        (rf"^thermostat rejected the change: .* - trying again in {_NUM} s$",
         lambda m: f"Your thermostat refused the change. Trying again in {_deg(m.group(1))} sec."),
        (rf"^waiting {_NUM} s before trying the thermostat again",
         lambda m: f"Your thermostat refused the last change. Trying again in {_deg(m.group(1))} sec."),
        (rf"^spacing writes - {_NUM} s",
         lambda m: f"Waiting {_deg(m.group(1))} sec between changes to the thermostat."),
        (rf"^waiting for the thermostat to show {_NUM}",
         lambda m: f"Waiting for your thermostat to show {_deg(m.group(1))}°."),
        (rf"^not sticking - the thermostat still shows {_NUM} after (\d+) sends of {_NUM}; pausing (\d+) min",
         lambda m: f"Your thermostat keeps {_deg(m.group(1))}° even after {m.group(2)} tries. "
                   f"Pausing {m.group(4)} min. Check its step size and limits."),
        (r"^waiting - the thermostat is in (\w+), armed for (\w+)",
         lambda m: f"Waiting: your thermostat is set to {m.group(1).replace('_', ' ')}, Homedial to {m.group(2)}. "
                   "Set them to match, or turn on mode control."),
        (r"^set the thermostat to (\w+) \(it was ([\w ]+)\)",
         lambda m: f"Switched your thermostat to {m.group(1)} (it was {m.group(2).replace('_', ' ')})."),
        (r"^turned the thermostat off",
         "Turned your thermostat off so it can't keep running against the safety guard."),
        (r"^not changing the thermostat's mode while a guard is blocking",
         "Not changing your thermostat's mode while the safety guard is on."),
        (rf"^backed off - holding at {_NUM}",
         lambda m: f"Holding the thermostat at {_deg(m.group(1))}°."),
        (rf"^backing off - (?:raised|lowered) the (?:cooling|heating) setpoint to {_NUM}",
         lambda m: f"Moved the thermostat to {_deg(m.group(1))}° to stop {stop}."),
    ]
    for pat, out in rules:
        m = re.match(pat, text)
        if m:
            return out(m) if callable(out) else str(out)
    # Text without a rule: still never a sensor ID or a two-decimal number.
    plain = re.sub(r"\b(?:sensor|climate|input_number|number)\.[a-z0-9_]+\b", lambda m: _named(m.group(0), names), text)
    plain = re.sub(r"\b(\d+)\.(\d)\d\b", r"\1.\2", plain)
    return (plain[:1].upper() + plain[1:]).rstrip(".") + "."


def _note_sentence(text: str, names: dict[str, str]) -> tuple[int, str] | None:
    """(priority, sentence) for a secondary reason worth telling people; lower is more important."""
    if (g := _guard_sentence(text, names)) is not None:
        return 0, g
    m = re.match(rf"^latent depression overruled by the floor - (\S+) would have gone below {_NUM}$", text)
    if m:
        return 2, f"Not cooling lower: {_named(m.group(1), names)} must stay at {_deg(m.group(2))}° or above."
    if text.startswith("floor held - protected room unreadable"):
        return 3, "Not cooling lower: the protected room has no reading."
    m = re.match(r"^fallback: (.+)$", text)
    if m:
        rooms = [_named(part.split(" on ", 1)[0].strip(), names) for part in m.group(1).split(", ")]
        return 4, "Using the backup sensor for " + ", ".join(rooms) + "."
    m = re.match(r"^(\d+) of (\d+) rooms live$", text)
    if m:
        return 5, f"{m.group(1)} of {m.group(2)} rooms reporting."
    m = re.match(rf"^latent: dew point {_NUM} over ceiling {_NUM}, lowering setpoint {_NUM}$", text)
    if m:
        return 6, f"Humid air (dew point {_deg(m.group(1))}°): cooling up to {_deg(m.group(3))}° lower to dry it."
    if text.startswith("latent: dew point sensor reports"):
        return 6, "Humidity help skipped: the dew point sensor's unit is not °F or °C."
    return None


def summarize(reasons: list[str], *, blocked: bool, mode: str | None, names: dict[str, str]) -> str:
    """One or two plain sentences for people (the Reason sensor). Pure: it reads the reasons and
    never decides anything."""
    if not reasons:
        return "All clear."
    target = None
    for r in reasons:
        m = re.match(rf"^stepping {_NUM} on the way to {_NUM}$", r)
        if m:
            target = m.group(2)
    if target is None:
        m = re.match(rf"^holding {_NUM} - .* \(wanted {_NUM}\)$", reasons[0])
        if m:
            target = m.group(2)
    if blocked and (g := _guard_sentence(reasons[0], names)) is not None:
        what = "cooling" if reasons[0].startswith("FREEZE") else "heating"
        lead = f"Safety guard: {g[:-1]}. Homedial is not {what}."
        follow = next((_lead_sentence(r, mode, names, None) for r in reasons[1:]
                       if r.startswith(("backing off", "backed off", "turned the thermostat off"))), "")
        out = (lead + " " + follow).strip()
        return out if len(out) <= SUMMARY_MAX else lead[:SUMMARY_MAX]
    nb = next((r for r in reasons if "noted but not blocking" in r), "")
    why = ("Cooling is the right fix, so nothing is blocked." if nb.endswith("not heating") else
           "Heating is the right fix, so nothing is blocked." if nb.endswith("not cooling") else
           "The freezing room comes first, so nothing is blocked." if nb.endswith("a room is freezing") else "")
    guard_lead = _guard_sentence(reasons[0], names)
    if guard_lead is not None:              # a guard noted (not blocking) leads the list
        lead, rest = (guard_lead + " " + why).strip(), reasons[1:]
        notes = [n for n in (_note_sentence(r, names) for r in rest) if n is not None]
        notes = [n for n in notes if n[0] != 0] or notes   # one more room, or the next useful note
    else:
        lead = _lead_sentence(reasons[0], mode, names, target)
        notes = [n for n in (_note_sentence(r, names) for r in reasons[1:]) if n is not None]
    if not notes:
        return lead[:SUMMARY_MAX]
    pri, note = min(notes, key=lambda n: n[0])
    if pri == 0 and guard_lead is None and why:
        note = note + " " + why
    out = lead + " " + note
    return out if len(out) <= SUMMARY_MAX else lead[:SUMMARY_MAX]
