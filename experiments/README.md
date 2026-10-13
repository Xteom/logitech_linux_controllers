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

Uses `import hidraw` (never `hid`, which is hidapi's libusb backend and would
detach the keyboard driver).

## Rungs

| Rung | Command | Proves |
| --- | --- | --- |
| A | `g560ctl/.venv/bin/python experiments/g815_probe.py enumerate` | Opens the HID++ vendor collection without disturbing typing; lists features |
| B | `g560ctl/.venv/bin/python experiments/g815_probe.py solid ff0000` | Whole keyboard one color + frameEnd commit |
| — | `g560ctl/.venv/bin/python experiments/g815_probe.py restore` | Hands lighting back to the onboard profile |

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
- Not painted: Windows, Shift, Alt (and Ctrl on the red run — unclear on the
  blue run). These are the modifiers (HID usages `0xE0-0xE7` → zones
  `0xDD-0xE4` under `usage - 3`), which sat in rejected chunks. Everything else
  (letters, numbers, F-row, arrows, etc.) lies in `0x01-0x68`.
- `restore` returns the keyboard to its onboard effect.
