# G815 lighting probe (Phase 1 spike)

Throwaway experiment proving we can drive the Logitech G815 (`046d:c33f`)
lighting from Python over hidraw, with no OpenRGB. Design:
`docs/superpowers/specs/2026-07-14-g815-static-controller-experiment-design.md`.
Not imported by `logitech_lighting`.

## Setup (one-time)

```bash
g560ctl/.venv/bin/pip install hidapi==0.15.0
sudo cp experiments/99-logitech-g815.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

The rule opens up only interface 1 (`ID_USB_INTERFACE_NUM=01`, the HID++
node). Interface 0, where keystrokes arrive, stays root-only. After
installing, check that `ls -l /dev/hidraw*` shows group `logitech-lighting` on
the G815's interface-1 node only.

Uses `import hidraw` (never `hid`, which is hidapi's libusb backend and would
detach the keyboard driver).

## Rungs

| Rung | Command | Proves |
| --- | --- | --- |
| A | `g560ctl/.venv/bin/python experiments/g815_probe.py enumerate` | Opens the HID++ vendor collection without disturbing typing; lists features |
| B | `g560ctl/.venv/bin/python experiments/g815_probe.py solid ff0000` | Whole keyboard one color + frameEnd commit |
| — | `g560ctl/.venv/bin/python experiments/g815_probe.py restore` | Hands lighting back to the onboard profile |
| C | `g560ctl/.venv/bin/python experiments/g815_probe.py key a 00ff00` | Per-key addressing by name (or raw zone `0xNN`) |
| D | `g560ctl/.venv/bin/python experiments/g815_probe.py latency [KEY] [--seconds N]` | Sustained acknowledged frames/sec |

## Findings log

### Rung A — enumerate

- Interface: `/dev/hidraw2`, interface 1, usage page `0xff43` usage `0x0602`
  (HID++ long reports, ID `0x11`). The same node also carries the NKRO
  keyboard (`0x0001/0x0006`), mouse (`0x0001/0x0002`), consumer (`0x000c`) and
  very-long HID++ (`0xff43/0x0604`) collections. `/dev/hidraw1` (interface 0)
  is the boot keyboard and is never opened.
- Feature indexes: `0x8081` per_key_lighting_v2 → `0x10`, `0x8071`
  rgb_effects → `0x0f`, `0x8100` onboard_profiles → `0x11` (same values
  g810-led hardcodes).
- Typing during the run: unaffected. The keyboard kept working; the run is
  sub-second and hidraw never detaches the input driver.

### Rung B — solid

- Packet: `11 ff 10 6c RR GG BB z×13` (0x8081 fn 6 setRgbZonesSingleValue),
  commit `11 ff 10 7c` (fn 7 frameEnd); host mode via `11 ff 11 1c 02`
  (0x8100 fn 1 setOnboardMode).
- Result: visible change, red then blue. Chunks accepted 8/20: zones
  `0x01-0x68` accepted; every chunk from `0x69` up rejected with
  `INVALID_ARGUMENT`. A chunk is all-or-nothing, so one invalid zone sinks
  the valid zones beside it.
- Not painted: Windows, Shift, Alt, and Ctrl on the red run (on the blue run
  Ctrl wasn't mentioned). Everything else (letters, numbers, F-row, arrows,
  etc.) changed. *Superseded by rung C:* the modifiers are zones `0x68-0x6f`,
  not `usage - 3`. Only `0x68` (left Ctrl) fell inside an accepted chunk,
  which explains the Ctrl ambiguity; `0x69-0x6f` sat in rejected chunks.
- `restore` returns the keyboard to its onboard effect.

### Rung C — key

- Zone rule `usage - 3` confirmed for: `a` (0x01), `esc` (0x26), `space`
  (0x29), `f12` (0x42). Each lit alone, as expected.
- Mismatches: the modifiers are **not** `usage - 3` (zones `0xdd-0xe4` are
  rejected). A one-zone-at-a-time scan of `0x69-0xfe` found exactly 18 valid
  zones, and each group was confirmed visually:
  - `0x68-0x6f`: the 8 modifiers (Ctrl/Shift/Alt/Win/…), i.e. `usage - 0x78`
  - `0x99, 0x9b-0x9e`: media keys
  - `0xb4-0xb8`: G1-G5
  - `0xd2`: G logo
- The full valid set is therefore `0x01-0x6f`, `0x99`, `0x9b-0x9e`,
  `0xb4-0xb8`, `0xd2`. This explains rung B: `0x68` (first modifier) was in
  an accepted chunk and the other modifiers were in rejected ones.

### Rung D — latency

- Runs (one frame = 1 setRgbZonesSingleValue + 1 frameEnd, each waited for):
  - `834 frames (0 busy) in 5.00s on space: 166.7 accepted frames/s, 333.3 reports/s`, repeated
    across 4 runs
  - `1667 frames in 10.00s` on esc ×3 and space ×2: 166.6-166.7 frames/s, 0 busy
  - `5000 frames (0 busy) in 30.00s on esc: 166.6 accepted frames/s, 333.3 reports/s`
  - Two diagnostic runs of 40 s and one of 30 s: 6664 / 6665 / 4999 frames, 0 busy
- Throughput is rock-steady at **~333 acknowledged reports/s (one round
  trip ≈ 3 ms)**.
- **Intermittent `BUSY` bursts.** Two runs out of ~15 got HID++ `BUSY`
  (code 8): one 30 s run aborted on its first BUSY (before BUSY was
  tolerated), and another 30 s run got 584 BUSY replies. Even then the
  accepted rate was the same (5582 − 584 = 4998 in 30 s ≈ 166.6/s). BUSY frames
  are not drawn. The bursts could not be triggered on demand. Nothing else
  had the device open (`hid-generic` only; no Solaar/OpenRGB/ratbag), and
  typing had no effect. **Cause unproven**, with two open hypotheses:
  (a) the device rejects fast while busy internally; (b) stale BUSY replies
  queued in the hidraw buffer get matched to later requests. The probe
  reuses one sw_id (`0x0C`) for every request, so a late reply is
  indistinguishable from a fresh one, and 584 BUSY frames costing ~zero
  time fits (b) as well as (a). Which function (fn 6 or fn 7) got BUSY was
  not recorded. `latency` now counts BUSY instead of aborting.
- At ~167 Hz the red/blue alternation is seen as steady magenta.
- Typing during the run: works normally. In this keyboard mode, keystrokes
  did **not** appear on `/dev/hidraw2` (0 input reports while typing); they
  arrive via interface 0. Interface 1 still declares an NKRO keyboard
  collection, so in NKRO mode they could appear there. `match_reply`
  ignores them regardless.

## Handoff to Phase 2 (ripple daemon)

- Interface: the hidapi `hidraw` entry for `046d:c33f` with usage page
  `0xFF43`, usage `0x0602` (here `/dev/hidraw2`, interface 1), opened with
  `import hidraw`. Typing is unaffected.
- Packets: setRgbZonesSingleValue (fn 6) and frameEnd (fn 7) on feature
  0x8081, which sits at index 0x10 (discover via root getFeature, don't hardcode).
  Host mode (`0x8100` fn 1 = `02`) is set before painting, and `restore` (`01`)
  hands back to the onboard effect. Whether host mode is strictly
  required was not isolated.
- Key zones: `usage - 3` for the main block (`0x01-0x67`), modifiers
  `0x68-0x6f` (`usage - 0x78`), media `0x99, 0x9b-0x9e`, G1-G5 `0xb4-0xb8`,
  logo `0xd2`. Any invalid zone makes the device reject its whole 13-zone report,
  so paint only known-valid zones.
- Budget: ~333 acknowledged reports/s when waiting for every reply. A
  ripple frame with K distinct colors costs about Σ⌈keys_per_color/13⌉ + 1
  reports. Example: 8 brightness rings of ≤13 keys each = ~9 reports →
  ~37 fps, which is "ok (>=30)", not "smooth". Levers for Phase 2: quantize
  ripple colors to fewer levels, try fn 1 (individual colors, 4 keys/report)
  or the consecutive/delta-compressed functions, and test pipelining writes
  without waiting for each reply (the endpoint may allow far more than 3 ms
  per round trip).
- Phase 2 must tolerate BUSY replies (skip or retry the frame) rather
  than treat them as fatal. It should also rotate the sw_id per request
  (1-15) and log which function got BUSY, to settle hypothesis (a) vs (b)
  above.
