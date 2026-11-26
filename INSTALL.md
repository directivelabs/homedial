# Install, set up and remove Homedial

Homedial 1.0.0, extras 1.0.0, Homedial Backdrop 1.0.0. Read "Home safety" in the
[README](README.md) first.

## What you need

- Home Assistant 2026.2 or newer.
- A thermostat that already works in Home Assistant (Cool and/or Heat), and at least one room
  temperature sensor.
- HACS (built in as Marketplace on Home Assistant 2026.11 or newer). Or copy the files by hand (see
  "Install by hand").
- For the extras and Homedial Backdrop: access to your `config` folder (for example the File editor app).

File editor is an app you add: Settings → Apps → Install app → **File editor** → Install → Start. Apps need Home Assistant OS.

## 1. Install Homedial with HACS or Marketplace

On Home Assistant 2026.11 or newer, HACS is built in as Marketplace. Open Settings → **Marketplace**. The
first time, accept its community-content warning. Select **Add from link**, enter
`https://github.com/directivelabs/homedial` under **GitHub link**, and select **Add**. If it asks for a
type, pick Integration and select **Add** again. It may ask you to connect a GitHub account first. Open
**Homedial**, select **Install**, then **Install** again, and restart Home Assistant if it asks.

On older versions, use HACS:

1. Open HACS → three-dot menu → **Custom repositories**.
2. Paste `https://github.com/directivelabs/homedial`, pick type **Integration**, and add it.
3. Search HACS for **Homedial** → **Download**.
4. Restart Home Assistant.

### Install by hand

Download this repository (Code → Download ZIP) and unzip it. Copy its `custom_components/dlabs_thermostat`
folder, with everything in it, into your Home Assistant `config/custom_components/` folder (create
`custom_components` if it doesn't exist), then restart Home Assistant. Updates are not automatic this way.

The File editor app can't copy a whole folder. With it, create the folders
`custom_components/dlabs_thermostat`, `custom_components/dlabs_thermostat/translations` and
`custom_components/dlabs_thermostat/brand`, then upload each file into its matching folder (13 files in
all).

## 2. Add Homedial

1. Settings → Devices & services → **Add integration** → **Homedial** (if it isn't listed, use
   the Helpers tab → **Create helper**).
2. Pick your thermostat and your room temperature sensors, and a protected room if you want one.
3. Review every safety limit. They start at example values, not recommendations for your home.
4. Finish.

## 3. Set a target and a mode

Homedial starts **Off** with no target and changes nothing until both are set. Home Assistant's standard
thermostat card can't set the first target, so use one of these:

- **With Homedial Backdrop:** add the `dl_thermostat` card (see [core/README.md](core/README.md)), pick
  **Cool** or **Heat** (or **Auto**, if you installed the extras), choose a temperature with the arrows and
  press **Start**.
- **Without it:** Settings → Tools → Actions (called Developer tools on older Home Assistant versions),
  pick **Climate: Set target temperature**, choose your Homedial, enter the temperature and press
  **Perform action**. Then pick **Cool** or **Heat** on the standard thermostat card.

Watch it for the first hours. The **Reason** sensor says what Homedial is doing and why. Big changes are
made 2 °F (1 °C) at a time, with a 10-minute wait between changes that ask for more heating or
cooling. That is on purpose.

**Off means off.** With "Control the thermostat's mode" on (the default), turning Homedial Off also turns
your real thermostat off. With the system off, nothing heats or cools, so no guard can protect the
house: don't leave it off in freezing weather.

## 4. Rooms and settings

Everything is on Settings → Devices & services → **Homedial**.

- **Add a room:** press **+ Add room**, pick the sensor, and save.
- **Edit or remove a room:** use the three-dot menu on that room's line.
- **Configure:** Thermostat, Safety limits, Humidity help (Cool only) and Advanced (step size, waits,
  sensor timeouts).
- **One Homedial per thermostat.** Homedial refuses a thermostat that another Homedial already controls.

## 5. Extras: Auto heat/cool, fan timers and safety alert (optional)

1. Turn on packages. In `configuration.yaml` add (or merge into your `homeassistant:` section):

       homeassistant:
         packages: !include_dir_named packages

2. Download `homedial-extras-1.0.0.zip` from this repository's Releases page (or take
   `extras/dlabs_thermostat_extras.yaml` from the repository).
3. Create `config/packages/` if it doesn't exist, copy `dlabs_thermostat_extras.yaml` into it, and
   restart Home Assistant.
4. Check: Settings → Devices & services → Entities, search "Homedial auto". You should see **Homedial auto
   heat/cool**. If not, packages are not turned on (step 1).

What you get:

- **Auto** keeps Homedial in Cool or Heat around your one target. It switches only after the house has
  been 2 °F (adjustable) past the target for 10 minutes, and at most once every 2 hours (sooner if the
  house is a further 1° out). Picking Off, Cool or Heat yourself turns Auto off. Needs a thermostat that can both heat and cool.
- **Fan timers** run the thermostat's fan for a set time, then hand it back to normal.
- **Safety alert (needs Homedial Backdrop)** switches every Homedial page to Alert when a safety guard blocks for
  1 minute, and back to Normal 5 minutes after it clears. It is on screen only: it doesn't notify your
  phone or anyone else.

**To turn Auto on:** Settings → Devices & services → Entities, search "Homedial auto heat/cool", open the
switch and turn it on.

**To run a fan timer:** Settings → Tools → Actions (called Developer tools on older Home Assistant
versions), pick **Homedial run the fan**, enter the minutes (for example 15), and press **Perform action**.

With the `dl_thermostat` card, Auto and the fan timers are on the card.

With more than one Homedial, Auto and the fan timers use the first one in A–Z order.

## 6. Homedial Backdrop dashboards (optional)

Download `homedial-backdrop-1.0.0.zip` from the Releases page and follow [core/README.md](core/README.md).

## Report a problem

Email **support@directivelabs.app** with what you did, what you expected and what happened (with the
time), the Reason sensor's text at that time, your Home Assistant version, your thermostat's brand,
and °F or °C. Log lines help: Settings → System → Logs, search "dlabs". Remove names, addresses and
other personal details first.

## Removing Homedial cleanly

1. Set your thermostat the way you want it. Removing Homedial doesn't change your thermostat; whatever it
   was last told stays until you change it.
2. If Homedial Backdrop shows an alert, set **Homedial alert condition** to NORMAL.
3. Settings → Devices & services → Homedial → three-dot menu → **Delete**.
4. Remove the files:
   - Installed with Marketplace: open Homedial in Marketplace → three-dot menu → **Uninstall**.
   - Installed with HACS: HACS → Homedial → three-dot menu → **Remove**.
   - Installed by hand: delete `config/custom_components/dlabs_thermostat/`. File editor won't delete a folder that
     still has files in it, and it hides one folder inside: `__pycache__` (Home Assistant makes it). If the folder
     won't delete after you've deleted the files you can see, use the **Terminal & SSH** app and run
     `rm -r /config/custom_components/dlabs_thermostat`.
   - Delete `config/packages/dlabs_thermostat_extras.yaml` and, if you installed Backdrop,
     `config/packages/dlabs_core.yaml`.
5. In each dashboard that used Backdrop, remove the Backdrop cards, and in the raw configuration editor delete
   the whole `button_card_templates:` section.
6. Restart Home Assistant. Leave the `packages:` line in `configuration.yaml` if other packages use it.
7. **Check your real thermostat's mode and setpoint.** A safety guard may have moved the setpoint to
   its limit.

If any Homedial entities still show as unavailable, remove them in Settings → Devices & services →
Entities.
