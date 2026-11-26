# Homedial Backdrop: themeable dashboards for Home Assistant

Version 1.0.0. Directive Labs, LLC. Free under the Apache License 2.0 (see `LICENSE` and `NOTICE`).

Homedial Backdrop gives every dashboard page one shared look that you can change from a dropdown.
It also adds an Alert Mode that recolors every page during an alert. Alert Mode changes how
pages look only. It never changes your automations.

## What you need

- Home Assistant 2026.2 or newer (tested on 2026.2.3, 2026.9.4 and 2026.11) with HACS or Marketplace
- From HACS (Marketplace on Home Assistant 2026.11 or newer): **button-card** (required) and **card-mod** (optional, for ordinary cards)
- Recommended: the **Time & Date** integration with its **Date** sensor (Settings → Devices & services →
  Add integration → Time & Date). Seasons, Holidays, Travel and the quote then switch at midnight on
  every card. Without it, each card switches the next time it redraws (a page reload).
- Packages turned on in `configuration.yaml` (create the `config/packages/` folder if it doesn't exist):

      homeassistant:
        packages: !include_dir_named packages

## What's in the download

- `dist/packages/dlabs_core.yaml`: the helpers.
- `dist/dlabs_core_templates.json`: the card templates, with **every theme pack**: 72 themes plus
  Seasons, Holidays and Travel, and the Line of the day quotes. A fresh install shows **Directive Labs Navy**.
- `examples/dashboard_example.yaml`: a small example page.

## Install

1. Copy `dist/packages/dlabs_core.yaml` into `config/packages/`, then restart Home Assistant.
   This creates 4 helpers: theme, alert condition, alert reason, and "show manual alert to exempt people."
2. Open your dashboard → Edit (pencil) → three dots → **Raw configuration editor**.
   - The automatic Overview dashboard asks you to **Take control** first. Or make a new dashboard
     (Settings → Dashboards → Add dashboard → New dashboard from scratch).
   - A dashboard kept in a YAML file has no raw editor: add the line from step 3 to that file instead.
3. At the very top, type `button_card_templates: ` (with a space after the colon). Then, **on that
   same line**, paste the whole contents of `dist/dlabs_core_templates.json` and save. Don't press
   Enter before pasting: JSON pasted on the next line is refused as a YAML error.
   Do this in every dashboard that uses Backdrop cards.
4. Use the templates on your cards (see **Card templates** below), or start from
   `examples/dashboard_example.yaml`: paste it into a new dashboard's raw editor, then do step 3, then
   replace every entity ID that contains `your_`.
5. To update later, delete the old `button_card_templates:` section in the raw editor (that line and
   every indented line under it), then repeat step 3 with the new file.

## Card templates

Every card is `type: custom:button-card` with a `template:` and optional `variables:`.

| Template | What it is | Main settings |
| --- | --- | --- |
| `dl_header` | Page title bar with the date and the alert status | `title`, `sub` (`@DATE@` becomes today's date) |
| `dl_panel` | Titled panel; you write the body | `title`, `code` (small label), `hot` (true = alert color); `custom_fields.body` |
| `dl_group` | Panel that themes ordinary Home Assistant cards | `title`; `custom_fields.body.card` holds the card |
| `dl_bars` | Up to 6 bars | `rows`: list of `{n: label, e: entity, u: unit, d: decimals, min, max}` |
| `dl_pill` | Pill button | card `name` and `tap_action`; `on` (true = highlighted); `tone` (a theme color name such as `g1`, `g2`, `g3` or `amber`; default and fallback `g3`) |
| `dl_quote` | Line of the day | none |
| `dl_chip`, `dl_chip_toggle` | Tile replacement (toggle: tap toggles) | `entity`; `name`, `big` |
| `dl_status` | Grid of status chips | `chips` (see below), `min` (chip width in px) |
| `dl_dial` | Round thermostat gauge | `entity` (a climate entity); `title`, `min`, `max`, `reads` |
| `dl_thermostat` | The whole thermostat on one card | `entity` (a Homedial climate entity); `outside`, `outside_humidity`, `humidity` |

`examples/dashboard_example.yaml` shows each one in use. Cards that show other entities than their own
`entity` need those entities in `triggers_update` to redraw when they change (the example does this).

## One card for the whole thermostat

`dl_thermostat` puts the inside and outside readings, your target, the modes, the Reason and the fan on one
card. It can also set your first target, which Home Assistant's standard thermostat card can't. Add it with
Edit → Add card → Manual:

    type: custom:button-card
    template: dl_thermostat
    entity: climate.dlabs_thermostat

Outside comes from your first weather entity. To use another, add `variables:` with `outside:` set to a
weather or sensor entity. Auto and the fan show when the extras are installed, on your first Homedial only.

## Add the thermostat controls

`dl_dial` only shows the temperature. To change the target and mode, see the Reason and pick a theme, add these cards too (Edit → Add card → Manual). These IDs are for your first Homedial; a second one has longer IDs, shown in Settings → Devices & services → Entities.

    type: thermostat
    entity: climate.dlabs_thermostat

    type: markdown
    title: Reason
    content: "{{ states('sensor.dlabs_thermostat_reason') }}"

    type: entities
    entities:
      - input_select.dlabs_theme

## Switch themes

Change the **Homedial theme** helper. Every page using Homedial Backdrop switches right away.
The download includes all 72 themes (for example **Classic**, **Slate**, **Ember**, **Daylight**,
**High Contrast** and **Library**), plus the automatic **Seasons**, **Holidays** and **Travel postcards** choices.

**Directive Labs Navy, Light, Dark and Calm** follow the Directive Labs Design System: normal capitalization,
labels that wrap instead of being cut off, nothing you need to read under 15 px, no italics, and every
text color at 4.5:1 contrast or better. **Calm** is the lowest-stimulation look. **Navy** is deep navy with
teal, soft card shading and a still glow on the header and thermostat cards; nothing in it moves. A fresh
install starts on **Directive Labs Navy**. If you already picked a theme, it stays. (A theme saved by an early test version is not kept: pick it again once.) Every other theme keeps its own look (capitals, one-line labels), because Home
Assistant owners like to customize; switch any time.

## Alert Mode

Set **Homedial alert condition**:

| State | Meaning | Default message |
| --- | --- | --- |
| NORMAL | Everything is fine | theme's normal text |
| ALERT | Alert; stays on until you set NORMAL | theme's manual text |

With the Homedial extras package, ALERT also turns on by itself when a thermostat safety
guard trips (a room too cold while cooling, or too hot while heating), and back off when it clears.

INTRUSION and FAULT are built into the engine for add-ons that can detect them. The 1.0.0 download
doesn't offer them.

Any other value is treated as NORMAL. Put your own words in **Homedial alert reason** to override the message.

## Living themes

- **Seasons:** choose `seasons` in the theme dropdown and the look changes on the 1st of every
  month: 12 palettes, each with its own faint pattern (snowflakes, raindrops, flowers, leaves, pine trees).
  You can also pin any single month, such as `season_10`.
- **Line of the day:** the `dl_quote` card shows a different line from a classic book every day.
  It cycles through the whole library before repeating. The **Library** theme is the matching
  "Book of the Day" look.
- Patterns hide during an alert so nothing competes with it. Alert colors are the same in every theme.
- Every card switches to the new month, holiday or postcard, and the quote rolls over, right at
  midnight, using the Date sensor from the Time & Date integration (`sensor.date`, see What you need).
  Without that sensor, each card switches the next time it redraws (a page reload, or a change to
  something it shows), so an always-on screen can show two looks for a while.
- The header names the automatic choice, e.g. "Holidays · October · Peak Color", so you can tell
  Seasons, Holidays and Travel apart.

## Holidays and Travel postcards

- **Holidays:** choose `holidays` in the theme dropdown. Each holiday's look shows for a few days
  around it, and the monthly Seasons look the rest of the year. 18 looks for 19 days:
  - US: New Year, Valentine's Day, St. Patrick's Day, Easter, Mother's Day, Memorial Day, Father's Day,
    Fourth of July, Labor Day, Halloween, Veterans Day, Thanksgiving, Winter Holidays.
  - International: Lunar New Year, Holi, Eid al-Fitr, Diwali, Día de los Muertos, Hanukkah.
  - When two overlap: the holiday whose day it is wins, then the shorter one. If it is the day of
    both, the priority holiday wins: Christmas Day shows Winter Holidays even when Hanukkah starts
    that day (2027). Christmas Eve also shows Winter Holidays (for example during Hanukkah in 2027 and
    2030), unless it is another holiday's own day. Holidays run through 2040.
  - Dates that move (Easter, lunar and lunisolar calendars) are built in through 2035.
  - Every holiday look can also be picked on its own, any time.
- **Travel postcards:** choose `travel` for a new postcard every Monday, or pin one: Tropical Island,
  Mountain Lake, Desert Highway, Lighthouse Coast, City Nights, Northern Lights, Paris, New York Harbor,
  London, Mount Fuji, Grand Canyon, Waterfalls.
- All art is original and drawn for Directive Labs; no characters, logos or brand marks.

## Chips, status grids, tap-to-drill and the dial

- **`dl_chip`** replaces a tile: colored side bar, name, value, "5 min ago", and a level bar for
  brightness, fan speed, cover position or a number slider. Tap or hold opens the details.
  **`dl_chip_toggle`** is the same but a tap toggles (lights, fans, switches). Add a
  `tap_action.confirmation` to make a switch ask first.

      type: custom:button-card
      template: dl_chip_toggle
      entity: light.desk
      variables: {name: Desk lamp}

- **`dl_status`** is a panel full of status chips. Each chip shows an entity (or attribute) with a
  color by state, and can open another page when tapped (`go: rooms` opens the "rooms" view of the
  same dashboard; `go: /other-dashboard/view` opens any page). Taps work with a mouse and on phones.

      variables:
        title: System status
        chips:
          - {n: Front door, e: binary_sensor.front_door, map: {on: Open, off: Closed}, hot: ['on'], ok: ['off']}
          - {n: Rooms, v: '3 of 3', tone: ok, go: rooms}

- **`dl_dial`** draws a round thermostat gauge for any climate entity: the current reading,
  a marker for the target (two markers for a heat/cool range), an optional set of side readouts,
  and a status line. °F or °C follows your Home Assistant.
- Writing your own HTML in a `dl_panel` body? `variables.dl.go('rooms')` returns the attributes
  that make any element a tap-to-drill link.
- "Something is wrong" chips use each theme's alert red, darkened on light themes so it stays readable.

## Size

The download includes every theme pack, about 270 KB per card's settings, which can slow the first
load on an older wall tablet.

## Report a problem

Email support@directivelabs.app with your Home Assistant and button-card versions, the theme you were
using, a screenshot, and what you expected. Remove personal details first.

## Remove Homedial Backdrop

Set **Homedial alert condition** to NORMAL, remove the Backdrop cards and the whole `button_card_templates:`
section from each dashboard, delete `config/packages/dlabs_core.yaml`, and restart Home Assistant. If
you use the Homedial extras, its safety alert needs Backdrop; see "Removing Homedial cleanly" in
`INSTALL.md`.

## What's new in 1.0.0

- Four new starter themes from the Directive Labs Design System: **Directive Labs Navy**, **Light**,
  **Dark** and **Calm**. Fresh installs start on Navy. Under these four, labels use normal capitalization and wrap
  instead of being cut off, nothing you need to read is under 15 px, and quotes are not in italics.
- Every other theme looks exactly as before (checked screenshot by screenshot, desktop and phone).
- Plainer words in every theme: chips say "3 hr ago" and "2 days ago" (was "3 h ago", "2 d ago"), and the
  dial says "Target 72.5°" (was "Set 72.5").
- Chips switch from hours to "1 day ago" at 23½ hours, so they never say "24 hr ago".
