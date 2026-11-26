# Homedial

Free, open-source add-ons for Home Assistant from Directive Labs, LLC. Version 1.0.0.

- **Homedial** puts a careful controller with built-in guards in front of the thermostat you
  already have. It blends several rooms into one temperature, can keep one room from getting too cold, and
  says what it is doing in plain words.
- **Extras (optional)** add Auto heat/cool, fan timers and an on-screen safety alert.
- **Homedial Backdrop (optional)** gives your dashboards one shared look you can change from a dropdown,
  including four calm Directive Labs themes: Navy (the default), Light, Dark and Calm.

## Home safety

**Homedial is not a safety device.** Read "Home safety" in the Directive Labs Terms before you turn on
thermostat control: https://directivelabs.app/terms#homedial

- Keep your thermostat's own limits, your heating and cooling equipment's safety controls, freeze
  protection, and smoke and carbon monoxide alarms in place. Homedial doesn't replace any of them.
- Every limit starts at an example value, not a recommendation for your home. Review and set each one
  yourself before you turn control on.
- After setup, and after any change or update, watch that your home stays at safe temperatures before
  you rely on Homedial.
- Alerts are on-screen only. They don't contact anyone, and nobody at Directive Labs watches your home.

## What it does

- **Blends rooms.** Several room sensors become one control temperature (weighted if you like). A
  sensor that stops reporting is left out, never counted as zero.
- **Protects one room.** In Cool, Homedial works to keep a protected room above a floor you set, while
  Home Assistant and your sensors are working, even when the thermostat can't see that room.
- **Safety guards.** If any room reaches the freeze limit while cooling, or the overheat limit while
  heating, Homedial backs the thermostat off until cooling or heating stops. A thermostat in Auto
  (heat/cool) is turned off instead, when "Control the thermostat's mode" is on, because that is the
  only way to stop it.
- **Gentle changes.** Small steps, a wait between changes that ask for more heating or cooling, and
  never outside the thermostat's own minimum and maximum. The waits survive restarts.
- **Explains itself.** The Reason sensor says what Homedial is doing and why, for example "Cooling toward
  72°. Next step in 7 min."

## What you need

- Home Assistant 2026.2 or newer. Tested on 2026.2.3, 2026.9.4 and 2026.11.
- A thermostat that already works in Home Assistant (Cool and/or Heat), and at least one room
  temperature sensor.
- HACS (built in as Marketplace on Home Assistant 2026.11 or newer), for the easiest install. Homedial
  Backdrop also needs **button-card** from it.

## Install

The short version: in HACS or Marketplace, add this repository as a custom repository (type Integration), download
Homedial, restart Home Assistant, then add the integration. Every step, plus the extras, Backdrop
and removal, is in [INSTALL.md](INSTALL.md).

## Guides

- [Install, set up and remove Homedial](INSTALL.md)
- [Tips for ADHD and autistic people](GUIDE_ADHD_AUTISM.md)
- [Homedial Backdrop dashboards](core/README.md)
- [What's changed](CHANGELOG.md)

## Report a problem

Email **support@directivelabs.app**. Please include:

- What you did, what you expected, and what happened (with the time).
- The text of the Reason sensor at that time.
- Your Home Assistant version, your thermostat's brand, and °F or °C.

Remove names, addresses and other personal details before you send logs or screenshots.

## Privacy

Homedial runs inside your Home Assistant. It has no network code, sends nothing to Directive Labs, and has
no accounts, ads, analytics or tracking. If your thermostat uses its maker's cloud, Home Assistant's own
connection for it sends Homedial's changes to the maker. Privacy policy: https://directivelabs.app/privacy

## License

Homedial is free under the Apache License 2.0. The Directive Labs and Homedial names and logos aren't
licensed. See [LICENSE](LICENSE) and [NOTICE](NOTICE). Home Assistant and HACS belong to their owners; Homedial isn't affiliated with or endorsed
by them.
