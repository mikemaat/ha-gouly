# Gouly for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories)
[![Validate](https://github.com/mikemaat/ha-gouly/actions/workflows/validate.yml/badge.svg)](https://github.com/mikemaat/ha-gouly/actions/workflows/validate.yml)
[![Tests](https://github.com/mikemaat/ha-gouly/actions/workflows/tests.yml/badge.svg)](https://github.com/mikemaat/ha-gouly/actions/workflows/tests.yml)

Local control of [Gouly](https://goulylight.com/) permanent outdoor / holiday lighting controllers
from Home Assistant. No cloud: Home Assistant talks to the controller directly on your network.

> Not affiliated with or endorsed by Gouly. Use at your own risk.

## Features

- On/off, brightness and RGBW colour
- Instant updates, including changes made from the Gouly app (local push)
- Finds the controller on your network automatically, and follows it if its IP address changes

Planned: effects (Chase, Breathing, Fireworks, ...), holiday presets, music mode.

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

Your lights appear as a light entity with brightness and RGBW colour.

## Contributing

The protocol notes are in [docs/PROTOCOL.md](docs/PROTOCOL.md). Effects, presets and music mode
still need decoding, and captures from other Gouly controllers are especially useful. Issues and
pull requests are welcome.

```sh
pip install pytest tinytuya
pytest
```

## License

[MIT](LICENSE)
