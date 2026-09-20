# Gouly for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories)
[![Validate](https://github.com/mikemaat/ha-gouly/actions/workflows/validate.yml/badge.svg)](https://github.com/mikemaat/ha-gouly/actions/workflows/validate.yml)
[![Tests](https://github.com/mikemaat/ha-gouly/actions/workflows/tests.yml/badge.svg)](https://github.com/mikemaat/ha-gouly/actions/workflows/tests.yml)

Local control of [Gouly](https://goulylight.com/) permanent outdoor / holiday lighting controllers
from Home Assistant. No cloud: Home Assistant talks to the controller directly on your network.

> Not affiliated with or endorsed by Gouly. Use at your own risk.

## Features

- On/off, brightness and RGBW colour
- 140 effects (Twinkle, Fireworks, Chase Rainbow, Breathing, ...) with an effect speed control
- The Gouly app's preset library (Christmas, Halloween, sports teams, ...), optional, see below
- Instant updates, including changes made from the Gouly app (local push)
- Finds the controller on your network automatically, and follows it if its IP address changes
- A companion [Gouly Card](https://github.com/mikemaat/ha-gouly-card) for browsing the presets,
  optional - everything here works with Home Assistant's own controls

## Supported hardware

Tested with a **Gouly Pro** controller (Wi-Fi + Bluetooth, 4 outputs, RGBW pixels) controlled by the
[Gouly Lighting](https://play.google.com/store/apps/details?id=com.goulyled.ledlight) app.
Other Gouly Wi-Fi controllers probably work too. Please open an issue to say whether yours does.

## How it works

Gouly controllers are Tuya devices underneath. Home Assistant needs two values to talk to yours
locally: its **device ID** and its **local key**. The key is stored in the Gouly app and never shown
to you, so this project includes a helper, **gouly-keys**, that reads it for you.

## 1. Get your device ID and local key

You need a Windows, macOS or Linux computer with [Python 3.10 or newer](https://www.python.org/downloads/)
and about 6 GB of free disk space. It doesn't have to be your Home Assistant machine.

Run **one** of these:

```sh
# with uv (https://docs.astral.sh/uv/)
uvx --from git+https://github.com/mikemaat/ha-gouly gouly-keys

# or with pipx (https://pipx.pypa.io/)
pipx run --spec git+https://github.com/mikemaat/ha-gouly gouly-keys
```

gouly-keys will:

1. Download a private Android emulator (one time, ~2.5 GB download). It doesn't touch any existing
   Android Studio install.
2. Download the Gouly Lighting app and install it in the emulator.
3. Open the emulator window and ask you to **log in to the Gouly app** with your normal account.
4. Read each controller's device ID and local key as the app loads your devices.
5. Look for the controllers on your network, and save everything to `gouly_devices.json`.

Your Gouly password is only typed into the Gouly app; gouly-keys never sees or stores it.
When you're done, `gouly-keys clean` deletes the emulator and downloads.

<details>
<summary>Troubleshooting</summary>

- **"can't use hardware acceleration"**
  - Windows: enable *Windows Hypervisor Platform* in *Turn Windows features on or off*, then reboot.
  - Linux: your user needs access to `/dev/kvm` (`sudo usermod -aG kvm $USER`, then log out and in).
- **The app download fails**: download the Gouly Lighting app yourself (`.apk`, `.xapk` or `.apks`,
  package `com.goulyled.ledlight`) and run `gouly-keys --apk path/to/file`.
- **The app crashes or closes**: run gouly-keys again. The emulator and downloads are reused.
- **A Gouly app update broke gouly-keys**: gouly-keys uses the latest Gouly app, and if that
  doesn't work it automatically retries with the last version it was tested with. You can also ask
  for that version directly with `gouly-keys --app-version known-good`, or pick a specific Play
  Store version code, e.g. `--app-version 109`. Please open an issue so the tool can be updated.
- **Controller not found on the network**: that's fine if the computer running gouly-keys isn't on
  the same network as your lights; Home Assistant will look for it during setup. To retry later,
  run `gouly-keys find` in the folder with `gouly_devices.json`.
- **Keys stopped working**: resetting or re-pairing a controller in the Gouly app changes its key.
  Run gouly-keys again.

</details>

<details>
<summary>Getting the key without gouly-keys</summary>

If you'd rather do it yourself, the approach is: run the Gouly Lighting app on a rooted Android
device or a *Google APIs* (not *Google Play*) emulator image, start
[frida-server](https://frida.re/docs/android/), and launch the app with
[`tools/gouly_keys/agent.js`](tools/gouly_keys/agent.js):

```sh
frida -U -f com.goulyled.ledlight -l tools/gouly_keys/agent.js
```

Log in, and the script prints each controller's `devId` and `localKey`.

</details>

Keep `gouly_devices.json` private: anyone on your network with it can control your lights.

## 2. Install the integration

**With HACS (recommended)**

1. In Home Assistant open **HACS**, click the ⋮ menu, then **Custom repositories**.
2. Add `https://github.com/mikemaat/ha-gouly` with type **Integration**.
3. Search HACS for **Gouly**, download it, and restart Home Assistant.

**Manually**: copy `custom_components/gouly` into your Home Assistant `config/custom_components`
folder and restart Home Assistant.

## 3. Add your lights

1. Go to **Settings > Devices & services > Add integration** and choose **Gouly**.
2. Choose **Paste gouly_devices.json**, and paste the whole file. (Or choose manual entry and type
   the device ID and local key.)
3. Home Assistant finds the controller on your network, which can take up to a minute.
4. Optionally upload `gouly_presets.json` (see below) on the last step, or skip it.

Your lights appear as a light entity with brightness, RGBW colour and 140 effects, plus an
**Effect speed** control.

## 4. Optional: the preset library

The Gouly app ships a library of ready-made patterns (Christmas, Halloween, sports teams and so
on). That library is Gouly's content, so it isn't included here. Extract it from the app on your
own machine instead (this doesn't need the emulator):

```sh
uvx --from git+https://github.com/mikemaat/ha-gouly gouly-keys presets
```

Then either upload `gouly_presets.json` on the last step when adding the integration, or add it
later from **Settings > Devices & services > Gouly > Configure > Preset library file**. (Copying
the file into your Home Assistant config folder by hand works too.) Three new controls appear on
the device: **Preset folder**, **Preset** and **Add preset to favourites**.

### The Gouly card

Everything above works with Home Assistant's own light dialog and the entities this integration
creates - no extra card needed. But picking from 2,600 presets through a dropdown is a poor way to
spend an evening, so there's a companion card:
**[Gouly Card](https://github.com/mikemaat/ha-gouly-card)**.

It keeps Home Assistant's own light dialog and adds the preset library to it: a folder menu, a
search box, favourites as one-tap buttons, and a star on every preset. Install it from HACS as a
**Dashboard** repository; it needs nothing configured beyond the light's entity id.

Use it or don't - the favourites, presets and services below behave the same either way, and
automations never depend on it.

### Favourites

> Favourite, with a "u" - since this plug-in was built in Canada, eh? The one place it'll trip you
> up is in the service names (`gouly.add_favourite`) and the `favourite_presets` attribute, so keep
> the "u" there and Home Assistant will find them. Or be a table-syrup-loving hoser.

Browsing 2,600 presets from a dropdown is fine occasionally, but for the ones you actually use:

1. Pick a **Preset folder**, then a **Preset** (the lights change as you pick).
2. Press **Add preset to favourites**.

(With the [Gouly Card](https://github.com/mikemaat/ha-gouly-card) it's the star beside each preset
instead; these three controls are how it's done without the card.)

Favourites are published as the light's `favourite_presets` attribute, which the
[Gouly Card](https://github.com/mikemaat/ha-gouly-card) shows as one-tap buttons in the light's
dialog. **Configure > Favourite presets** removes them, and they can be managed from scripts and
automations - which is what the card does.

Effects and presets are kept apart: the light's **effect list** holds the controller's 140 effects
and nothing else, and presets are applied with a service, so an automation never depends on what
the effect list contains.

| Service | What it does |
|---|---|
| `gouly.apply_preset` | Show `preset: "Folder / Preset"` on the lights |
| `gouly.add_favourite` | Add it to the favourites |
| `gouly.remove_favourite` | Remove it again |
| `gouly.set_favourites` | Replace the favourites with `presets: [...]`, in that order |

```yaml
# Christmas patterns from dusk, every December evening
triggers:
  - trigger: sun
    event: sunset
conditions:
  - condition: template
    value_template: "{{ now().month == 12 }}"
actions:
  - action: gouly.apply_preset
    target: { entity_id: light.christmas_lights_front }
    data: { preset: "Christmas 1 / Christmas-static" }
```

The light reports the colour a preset is showing: a single colour preset reports that colour, and a
multi colour one reports none, so a tile doesn't sit there showing the last solid colour you picked.

Presets are designed for an 800 LED string and are scaled to fit yours. The Gouly app instead maps
a preset's zones onto the controller's four outputs, which can leave most of the string dark; this
integration stretches them across the whole string so the pattern looks like its preview.

## Contributing

The protocol notes are in [docs/PROTOCOL.md](docs/PROTOCOL.md). Captures from other Gouly
controllers are especially useful. Issues and pull requests are welcome.

```sh
pip install pytest tinytuya
pytest
```

## License

[MIT](LICENSE)
