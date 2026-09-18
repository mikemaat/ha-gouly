# Gouly controller protocol

Notes from reverse engineering a Gouly Pro controller and the Gouly Lighting Android app (1.8.2).
Corrections and captures from other controller models are very welcome.

## Transport

Gouly controllers are Tuya Wi-Fi modules (MAC prefix `38:2C:E5`, Tuya Smart Inc.) and the
Gouly app is built on the Tuya/ThingClips app SDK.

- Local control: Tuya local protocol **3.5** on TCP **6668**, encrypted with the device's local key.
- The controller does **not** send the usual Tuya UDP discovery broadcasts (6666/6667/7000).
- The controller is slow to accept connections (~100-200 ms ping); aggressive port scans miss it.

### Data points

| DP  | Code            | Type        | Notes |
|-----|-----------------|-------------|-------|
| 20  | `switch_led`    | bool        | Reported on power changes and in `status()` |
| 21  | `work_mode`     | enum        | Declared in the schema, not used by the app |
| 22  | `bright_value`  | 10-1000     | Declared in the schema, not used by the app |
| 24  | `colour_data`   | string      | Declared in the schema, not used by the app |
| 101 | `transparent`   | raw         | **Everything the app does goes through this DP** |
| 102 | `percent_state` | 0-3, ro     | Unknown |
| 103 | `siri`          | string      | Unknown |

Over the local protocol, raw DP values are base64 strings. `status()` only returns DP 20; the
other DPs are only reported when they change.

## DP 101 frames

```
<header> <command> <payload ...> <crc>
```

- `header`: `0xAA` for commands. The controller echoes every command it accepts (whether sent by
  the app or by us), so echoes can be used to follow state changes made elsewhere.
  `0xBB` marks reports the controller generates itself (e.g. replies to queries).
- `crc`: **CRC-8/MAXIM** (polynomial 0x31 reflected, init 0x00, no final XOR) over every
  preceding byte, including the header.
- Frames are zero padded to a fixed length per command.

### Known commands

| Frame (hex, CRC omitted)                 | Len | Meaning |
|------------------------------------------|-----|---------|
| `AA F1 01` / `AA F1 00`                  | 11  | Power on / off (also reported as DP 20) |
| `AA F2 vv`                               | 11  | Brightness, `vv` = 0x01-0xFF (app sends 0x28-0xFF) |
| `AA F6 RR GG BB WW`                      | 19  | Solid RGBW colour |
| `AA F3 A1 ...`                           | 14  | Scene header: LED counts, see below |
| `AA F3 A2 ...`                           | 113 | Scene segment (zone), see below |
| `AA A0 00`                               | 11  | Save the scene in the controller |
| `AA C7 <on> <mode>`                      | 11  | Music mode (`C7 00 00` = off, sent before a colour or effect) |
| `AA B6`                                  | 9   | Query state, answered by `BB B6 ...` |
| `AA C2`, `AA C5`                         | 11  | Query schedules, answered by `BB C2 ...` / `BB C5 ...` |
| `AA EE yyyy MM dd HH mm ss ...`          | 18  | Clock sync sent by the controller on connect |

### Scene header (`F3 A1`)

```
AA F3 A1 <total:2> <ch1:2> <ch2:2> <ch3:2> <ch4:2>
```

LED counts: the whole string and each of the four outputs. Sent before the segments of a
scene. The controller reports its own counts in the `BB B6` state report, and those are
the values to use.

### Segment (`F3 A2`)

```
AA F3 A2 <togTag> <segmentId> <on> <start:2> <end:2> <effect> <speed> <width> <brightness>
         <direction> <colour1:5> <colour2:5> <colour3:5> <paletteId> <palette:16x5> <paletteLen>
```

* `start`/`end` are LED indexes, both sent as the value minus one (`end` is exclusive).
* `effect` is a mode id, see `custom_components/gouly/effects.py` (140 effects plus 23 music
  modes). Effect 0 is Static.
* `speed` 1-255, `direction` 0/1, `brightness` 0-255 (per segment).
* Colours are `R G B warmWhite coldWhite`, each scaled by their own brightness
  (`value * bright / 255`).
* `paletteId` is 0 for "no palette"; the 16 palette entries are always sent, padded by
  repeating the list, and `paletteLen` gives how many are real.

A scene is sent as: `C7 00 00` (music off), `F3 A1` (header), one `F3 A2` per zone about
100-250 ms apart, then `A0 00` (save). Zones starting past the end of the string are ignored
by the controller.

### Setting a solid colour

The app sends this sequence (about 150-250 ms apart):

```
AA C7                                              stop music (?)
AA F3 A1 01 90 00 64 00 64 00 64 00 64             static program parameters
AA F3 A2 00 00 01 00 00 06 3E 00 00 00 FF 00 RR GG BB WW   colour list with one colour
AA F6 RR GG BB WW                                  solid colour
AA A0                                              apply
```

### State report (`BB B6`)

```
BB B6 <on> <brightness> <total:2> <ch1:2> <ch2:2> <ch3:2> <ch4:2> <lineIndex> <icType>
      <hasPassword> ?? <firmware> ... <ch1Mirror> <ch2Mirror> <ch3Mirror> <ch4Mirror>
```

`on` is `01`/`00`, `brightness` is `00`-`FF`, then the same LED counts as the scene header.

### Presets

The Gouly app ships its pattern library as assets inside the APK: `assets/gouly_pro_db_06.db`
(scenes, segments and colour palettes for Wi-Fi "Pro" controllers) and
`assets/json/SLProEffect01.json` (the effect names and ids). The library is Gouly's content, so
this repository does not redistribute it; `gouly-keys` reads it from the app on your own machine.

Presets are designed for an 800 LED string. The app maps a preset's zones onto the controller's
four outputs, which leaves nothing lit when a preset has more zones than outputs; scaling the
zones proportionally to the controller's LED count reproduces the intended pattern instead.

### Not decoded yet

- Music mode data (`C7` with a mode, `AA C8` rhythm frames).
- Schedules (`BB C5` contains the schedule name, e.g. `Sunset`).
- Custom per-pixel mode (`E0`/`E5`), IC type and mirroring settings.

## Capturing more

`tools/gouly_keys/agent.js` shows how the app is hooked. To log what the app sends, hook
`com.thingclips.sdk.device.presenter.AbsThingDevice.publishDps` with Frida. Enumerating all
loaded classes makes the app freeze and get killed; use `Java.enumerateMethods` instead.
