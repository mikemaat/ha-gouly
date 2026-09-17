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
| `AA F3 A1 ...`                           | 14  | Program (effect) parameters, see below |
| `AA F3 A2 ...`                           | 113 | Program colour list, see below |
| `AA A0`                                  | 11  | Apply the program |
| `AA C7`                                  | 11  | Sent before changing colour; probably stops music mode |
| `AA B6`                                  | 9   | Query state, answered by `BB B6 ...` |
| `AA C2`, `AA C5`                         | 11  | Query schedules, answered by `BB C2 ...` / `BB C5 ...` |
| `AA EE yyyy MM dd HH mm ss ...`          | 18  | Clock sync sent by the controller on connect |

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
BB B6 <on> <brightness> <program parameters ...>
```

`on` is `01`/`00`, `brightness` is `00`-`FF`. The remaining bytes match the `F3 A1` parameters
of the saved program, not necessarily what is currently showing.

### Not decoded yet

- Effect programs: `F3 A1 06 3F 03 E7 00 C8 00 C8 00 C8` was sent for an effect. The first byte
  looks like the effect number and `03E7` (999) like a speed, but this needs more captures.
- `F3 A2` colour list header fields for effects (e.g. `06 3E 8F 80 00 FF`, `06 3E 00 80 B3 FF`).
- Music mode, schedules (`BB C5` contains the schedule name, e.g. `Sunset`), holiday presets.

## Capturing more

`tools/gouly_keys/agent.js` shows how the app is hooked. To log what the app sends, hook
`com.thingclips.sdk.device.presenter.AbsThingDevice.publishDps` with Frida. Enumerating all
loaded classes makes the app freeze and get killed; use `Java.enumerateMethods` instead.
