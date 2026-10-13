# G815 Static Controller Experiment (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A throwaway script, `experiments/g815_probe.py`, that proves from Python (no OpenRGB) that we can open the G815's HID++ interface without disturbing typing, paint the whole keyboard, paint one key, and measure the sustained update rate. The result is recorded in a findings log.

**Architecture:** This is one standalone CLI script with four subcommands, one per rung (A `enumerate`, B `solid`, C `key`, D `latency`). It talks HID++ 2.0 long reports over hidraw through hidapi's `hidraw` module. Feature indexes are discovered at runtime through the HID++ root feature instead of being hardcoded. The per-key lighting feature (`0x8081`) carries the colors, and its `frameEnd` function is the commit step. Nothing here is imported by `logitech_lighting`.

**Tech Stack:** Python 3.10 (project venv `g560ctl/.venv`), `hidapi==0.15.0` (`import hidraw`), argparse, a udev rule for hidraw.

**Spec:** `docs/superpowers/specs/2026-07-14-g815-static-controller-experiment-design.md`

## Global Constraints

- Device: Logitech G815, `046d:c33f`.
- **Typing safety is the top invariant.** Import `hidraw`, **never** `hid`. In this wheel `hid` is the libusb backend, which detaches the kernel driver, while `hidraw` writes to `/dev/hidrawN` and leaves the input driver attached.
- Select only the collection with **usage page `0xFF43`, usage `0x0602`** and refuse anything else. *Spec correction:* the spec says `0xFF00`, but the G815's report descriptor (read from sysfs while planning) puts its HID++ long collection on `0xFF43`. The spec's intent, "vendor collection, never the keyboard collection", is unchanged.
- Write only 20-byte HID++ long reports (report ID `0x11`, device index `0xFF`).
- New dependency: `hidapi==0.15.0`, installed into `g560ctl/.venv` only and not added to `pyproject.toml`. It was already installed during planning.
- No changes to `g560ctl/src/logitech_lighting/` and no unit-test suite in Phase 1 (spec). Pure helpers are checked with inline `python -c` asserts, and the rungs are checked on hardware.
- udev rule, verbatim from the spec: `KERNEL=="hidraw*", ATTRS{idVendor}=="046d", ATTRS{idProduct}=="c33f", MODE="0660", GROUP="logitech-lighting"`
- Run the script as `g560ctl/.venv/bin/python experiments/g815_probe.py <subcommand>`. If the shell predates the group, wrap it as `sg logitech-lighting -c "..."`.
- Stop at the first rung that fails and record why in the findings log. Do not guess past it.

## Review Focus

1. **Keystrokes arriving while the script waits for a reply.** `/dev/hidraw2` also carries the NKRO keyboard, mouse and consumer input reports. A reply wait must skip them, never mistake one for a HID++ reply, and never time out just because the user is typing. *(Task 1: `match_reply` asserts.)*
2. **A HID++ error reply** (e.g. an invalid zone, `INVALID_ARGUMENT`) must surface as a named error that says which request failed, not as a timeout or a silent success. *(Task 1: `match_reply` asserts. Task 2: `solid` reports failed chunks.)*
3. **Malformed color input** (`ff660`, `gggggg`, `#FF6600`) gives a clear one-line error, and upper case or a leading `#` is accepted, the same as `./lights`. *(Task 2 asserts.)*
4. **Unknown or reserved key names** (`foo`, `0x00`, `0xff`) give a clear error listing valid names instead of writing a bad zone. *(Task 3 asserts.)*
5. **Missing permissions** (no udev rule yet, or a shell without the group) give the udev/`sg` hint, not a Python traceback. *(Task 1 Step 6, run before the rule is installed.)*

---

### Task 1: Scaffold, udev rule, and rung A (`enumerate`)

**Files:**
- Create: `experiments/g815_probe.py`
- Create: `experiments/99-logitech-g815.rules`
- Create: `experiments/README.md`
- Commit (already written, untracked): `docs/superpowers/specs/2026-07-14-g815-static-controller-experiment-design.md`, this plan

**Interfaces:**
- Produces (used by Tasks 2–4):
  - `ProbeError(Exception)`, `HidppError(ProbeError)` with `.feature_index`, `.function`, `.code`
  - `build_report(feature_index: int, function: int, params: bytes = b"") -> bytes` (20 bytes)
  - `match_reply(request: bytes, reply: bytes) -> str | None` returns `"reply"`, `"error"` or `None`
  - `select_hidpp_interface(entries: list[dict]) -> dict`
  - `open_keyboard() -> tuple[hidraw.device, dict]`
  - `send(dev, report: bytes) -> bytes` writes one report, waits for its reply, raises `HidppError` / `ProbeError`
  - `find_feature(dev, feature_id: int) -> int | None`
  - Constants `FEATURES` (name → id), `SW_ID`, `REPORT_LEN`
  - `main(argv=None) -> int` with a `subparsers` object that later tasks extend inside `build_parser()`

- [ ] **Step 1: Branch and commit the spec and plan**

```bash
git switch -c exp/g815-probe
git add docs/superpowers/specs/2026-07-14-g815-static-controller-experiment-design.md \
        docs/superpowers/plans/2026-10-13-g815-static-controller-experiment.md
git commit -m "docs: add G815 phase 1 spec and plan"
```

- [ ] **Step 2: Confirm the dependency and the backend**

Run:
```bash
g560ctl/.venv/bin/python -c "import hidraw; [print(e['path'], e['interface_number'], hex(e['usage_page']), hex(e['usage'])) for e in hidraw.enumerate(0x046d, 0xc33f)]"
```
Expected: one line reads `b'/dev/hidraw2' 1 0xff43 0x602`. If `import hidraw` fails, run `g560ctl/.venv/bin/pip install hidapi==0.15.0`.

- [ ] **Step 3: Write `experiments/g815_probe.py` (core + rung A)**

```python
#!/usr/bin/env python3
"""G815 static lighting probe: Phase 1 throwaway spike.

Not imported by logitech_lighting. See experiments/README.md for the rungs and
the findings log.

Run: g560ctl/.venv/bin/python experiments/g815_probe.py <subcommand> ...
"""
import argparse
import sys
import time

# hidapi's hidraw backend writes to /dev/hidrawN and never detaches the kernel
# keyboard driver. Do NOT import `hid`: in this wheel it is the libusb backend.
import hidraw

VENDOR_ID = 0x046D
PRODUCT_ID = 0xC33F
HIDPP_USAGE_PAGE = 0xFF43  # from the G815 report descriptor (spec said 0xFF00)
HIDPP_LONG_USAGE = 0x0602  # collection carrying 20-byte HID++ long reports
REPORT_LONG = 0x11
REPORT_LEN = 20
DEVICE_INDEX = 0xFF  # wired device
SW_ID = 0x0C
TIMEOUT_MS = 1000

ROOT_INDEX = 0x00
FEATURES = {
    "per_key_lighting_v2": 0x8081,
    "rgb_effects": 0x8071,
    "onboard_profiles": 0x8100,
}

HIDPP_ERRORS = {
    1: "UNKNOWN",
    2: "INVALID_ARGUMENT",
    3: "OUT_OF_RANGE",
    4: "HW_ERROR",
    5: "LOGITECH_INTERNAL",
    6: "INVALID_FEATURE_INDEX",
    7: "INVALID_FUNCTION_ID",
    8: "BUSY",
    9: "UNSUPPORTED",
}

PERMISSION_HINT = (
    "Install experiments/99-logitech-g815.rules (see experiments/README.md); "
    "if this shell predates the logitech-lighting group, run via "
    "`sg logitech-lighting -c \"...\"`."
)


class ProbeError(Exception):
    pass


class HidppError(ProbeError):
    def __init__(self, feature_index, function, code):
        self.feature_index = feature_index
        self.function = function
        self.code = code
        name = HIDPP_ERRORS.get(code, f"0x{code:02x}")
        super().__init__(
            f"HID++ error {name} from feature index 0x{feature_index:02x} "
            f"function {function}"
        )


def build_report(feature_index, function, params=b""):
    """One HID++ 2.0 long report: [0x11, 0xff, feature_index, fn<<4|sw_id, params...]."""
    if len(params) > REPORT_LEN - 4:
        raise ProbeError(f"{len(params)} parameter bytes do not fit a long report")
    header = bytes([REPORT_LONG, DEVICE_INDEX, feature_index, (function << 4) | SW_ID])
    return (header + bytes(params)).ljust(REPORT_LEN, b"\x00")


def match_reply(request, reply):
    """Classify a report read back from hidraw against the request we sent.

    The hidraw node also carries keystroke/mouse/consumer input reports, which
    must be ignored (None), never mistaken for a reply.
    """
    if len(reply) < 6 or reply[0] != REPORT_LONG:
        return None
    if reply[2] == 0xFF and reply[3] == request[2] and reply[4] == request[3]:
        return "error"
    if reply[2] == request[2] and reply[3] == request[3]:
        return "reply"
    return None


def select_hidpp_interface(entries):
    for entry in entries:
        if entry["usage_page"] == HIDPP_USAGE_PAGE and entry["usage"] == HIDPP_LONG_USAGE:
            return entry
    raise ProbeError(
        "HID++ vendor collection (usage page 0xFF43, usage 0x0602) not found; "
        "refusing to guess an interface."
    )


def open_keyboard():
    entries = hidraw.enumerate(VENDOR_ID, PRODUCT_ID)
    if not entries:
        raise ProbeError(
            "G815 (046d:c33f) not found. Replug the USB cable and confirm "
            "`lsusb -d 046d:c33f` lists it."
        )
    entry = select_hidpp_interface(entries)
    dev = hidraw.device()
    try:
        dev.open_path(entry["path"])
    except OSError as exc:
        raise ProbeError(f"cannot open {entry['path'].decode()}: {exc}. {PERMISSION_HINT}")
    return dev, entry


def send(dev, report):
    """Write one HID++ long report and wait for its reply; return the reply."""
    if len(report) != REPORT_LEN or report[0] != REPORT_LONG:
        raise ProbeError("refusing to write anything but a 20-byte HID++ long report")
    dev.write(report)
    deadline = time.monotonic() + TIMEOUT_MS / 1000
    while (remaining := deadline - time.monotonic()) > 0:
        reply = bytes(dev.read(64, max(1, int(remaining * 1000))))
        kind = match_reply(report, reply)
        if kind == "error":
            raise HidppError(report[2], report[3] >> 4, reply[5])
        if kind == "reply":
            return reply
    raise ProbeError(f"no reply to {report[:4].hex(' ')} within {TIMEOUT_MS} ms")


def find_feature(dev, feature_id):
    """Root feature getFeature(id): returns the feature's index, or None if absent."""
    reply = send(dev, build_report(ROOT_INDEX, 0, feature_id.to_bytes(2, "big")))
    return reply[4] or None


def cmd_enumerate(args):
    entries = hidraw.enumerate(VENDOR_ID, PRODUCT_ID)
    if not entries:
        raise ProbeError("G815 (046d:c33f) not found. Replug the USB cable.")
    chosen = select_hidpp_interface(entries)
    for entry in entries:
        mark = "->" if entry is chosen else "  "
        print(
            f"{mark} {entry['path'].decode()}  interface {entry['interface_number']}  "
            f"usage_page 0x{entry['usage_page']:04x}  usage 0x{entry['usage']:04x}"
        )
    dev, _ = open_keyboard()
    try:
        print("opened via hidraw (kernel keyboard driver untouched)")
        for name, feature_id in FEATURES.items():
            index = find_feature(dev, feature_id)
            where = f"index 0x{index:02x}" if index else "not supported"
            print(f"feature 0x{feature_id:04x} {name}: {where}")
    finally:
        dev.close()


def build_parser():
    parser = argparse.ArgumentParser(description="G815 lighting probe (Phase 1 spike)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p = subparsers.add_parser("enumerate", help="rung A: find and open the HID++ interface")
    p.set_defaults(func=cmd_enumerate)

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except ProbeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Offline checks of the pure helpers (Review Focus 1, 2)**

Run:
```bash
g560ctl/.venv/bin/python -c "
import sys; sys.path.insert(0, 'experiments')
from g815_probe import *
r = build_report(0x10, 6, b'\x01\x02')
assert r == bytes([0x11, 0xff, 0x10, 0x6c, 1, 2]) + bytes(14), r.hex()
assert len(build_report(0x00, 0)) == 20
req = build_report(0x10, 7)
assert match_reply(req, bytes([0x01, 0, 0x04, 0, 0, 0, 0, 0])) is None          # NKRO keystroke
assert match_reply(req, bytes([0x11, 0xff, 0x0f, 0x7c]) + bytes(16)) is None    # other feature
assert match_reply(req, bytes([0x11, 0xff, 0x10, 0x7c]) + bytes(16)) == 'reply'
assert match_reply(req, bytes([0x11, 0xff, 0xff, 0x10, 0x7c, 0x02]) + bytes(14)) == 'error'
e = HidppError(0x10, 6, 2); assert 'INVALID_ARGUMENT' in str(e)
try: select_hidpp_interface([{'usage_page': 1, 'usage': 6}]); raise SystemExit('should refuse')
except ProbeError: pass
print('ok')
"
```
Expected: `ok`

- [ ] **Step 5: Write `experiments/99-logitech-g815.rules`**

```
# G815 (046d:c33f) hidraw access for experiments/g815_probe.py.
# Note: this grants the logitech-lighting group read access to the raw
# keyboard report stream (the HID++ node also carries keystrokes).
KERNEL=="hidraw*", ATTRS{idVendor}=="046d", ATTRS{idProduct}=="c33f", MODE="0660", GROUP="logitech-lighting"
```

- [ ] **Step 6: Check the permission error before the rule is installed (Review Focus 5)**

Run: `g560ctl/.venv/bin/python experiments/g815_probe.py enumerate`
Expected: the interface list prints with `->` on `/dev/hidraw2 ... 0xff43 ... 0x0602`, then a one-line `Error: cannot open /dev/hidraw2: ... Install experiments/99-logitech-g815.rules ...` and exit code 1, with no traceback. (Skip if `ls -l /dev/hidraw2` already shows group `logitech-lighting`.)

- [ ] **Step 7: The user installs the rule (sudo, in a real terminal)**

Ask the user to run:
```bash
sudo cp experiments/99-logitech-g815.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
```
Then verify: `ls -l /dev/hidraw1 /dev/hidraw2` shows `crw-rw---- root logitech-lighting`.

- [ ] **Step 8: Run rung A on hardware**

Run: `g560ctl/.venv/bin/python experiments/g815_probe.py enumerate`
Expected: the `->` line on `/dev/hidraw2`, `opened via hidraw ...`, and `feature 0x8081 per_key_lighting_v2: index 0x..` (not "not supported"). Ask the user to type in another window while running it and confirm typing still works. **Gate:** if 0x8081 is not supported, stop and record that.

- [ ] **Step 9: Write `experiments/README.md`**

````markdown
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

## Findings log

### Rung A — enumerate

- Interface: <fill in from the Step 8 output: path, interface number, usage page/usage>
- Feature indexes: <fill in each `feature 0x....` line>
- Typing during the run: <works / broke>
````

When writing the file, replace each `<fill in ...>` with the actual Step 8 output. Nothing should remain in angle brackets.

- [ ] **Step 10: Commit**

```bash
git add experiments/
git commit -m "feat(experiments): G815 probe rung A - open HID++ interface over hidraw"
```

---

### Task 2: Rung B (`solid`) with host mode, commit frame, and `restore`

**Files:**
- Modify: `experiments/g815_probe.py`
- Modify: `experiments/README.md`

**Interfaces:**
- Consumes: `build_report`, `send`, `find_feature`, `FEATURES`, `ProbeError`, `HidppError`, `open_keyboard`, `build_parser` (Task 1)
- Produces (used by Tasks 3–4):
  - `parse_color(text: str) -> tuple[int, int, int]`
  - `single_value_reports(lighting_index: int, zones, rgb) -> list[bytes]`
  - `prepare(dev) -> int` resolves the 0x8081 index and switches the keyboard to host mode
  - `paint(dev, lighting_index, zones, rgb) -> list[tuple[list[int], HidppError]]` (failed chunks)
  - `commit(dev, lighting_index) -> None`

Protocol notes (ported from g810-led / OpenRGB, matching HID++ feature `0x8081`): function 6 `setRgbZonesSingleValue` = `[r, g, b, zone × 13]`, function 7 `frameEnd` = the commit. `0x8100` onboard profiles, function 1 `setOnboardMode` = `0x02` host / `0x01` onboard. Host mode stops the onboard effect from overwriting our colors.

- [ ] **Step 1: Add the helpers after `find_feature`**

```python
ZONES_PER_REPORT = 13
ALL_ZONES = range(0x01, 0xFF)  # probe every possible zone id; 0x00/0xFF are reserved
FN_SET_SINGLE_VALUE = 6
FN_FRAME_END = 7
FN_SET_ONBOARD_MODE = 1
MODE_ONBOARD = 0x01
MODE_HOST = 0x02


def parse_color(text):
    digits = text[1:] if text.startswith("#") else text
    try:
        if len(digits) != 6:
            raise ValueError
        return tuple(bytes.fromhex(digits))
    except ValueError:
        raise ProbeError(f"color must be 6 hex digits like ff6600, got {text!r}")


def single_value_reports(lighting_index, zones, rgb):
    """setRgbZonesSingleValue reports covering `zones`, 13 zones per report.

    A short final chunk is padded by repeating its last zone, so no filler
    byte is ever interpreted as a zone id.
    """
    zones = list(zones)
    if not zones:
        raise ProbeError("no zones to paint")
    reports = []
    for start in range(0, len(zones), ZONES_PER_REPORT):
        chunk = zones[start:start + ZONES_PER_REPORT]
        chunk += [chunk[-1]] * (ZONES_PER_REPORT - len(chunk))
        reports.append(build_report(lighting_index, FN_SET_SINGLE_VALUE, bytes(rgb) + bytes(chunk)))
    return reports


def set_onboard_mode(dev, mode):
    index = find_feature(dev, FEATURES["onboard_profiles"])
    if index:
        send(dev, build_report(index, FN_SET_ONBOARD_MODE, bytes([mode])))


def prepare(dev):
    lighting = find_feature(dev, FEATURES["per_key_lighting_v2"])
    if not lighting:
        raise ProbeError("per-key lighting feature 0x8081 not supported by this firmware")
    set_onboard_mode(dev, MODE_HOST)
    return lighting


def paint(dev, lighting_index, zones, rgb):
    failed = []
    for report in single_value_reports(lighting_index, zones, rgb):
        try:
            send(dev, report)
        except HidppError as exc:
            failed.append((list(report[7:]), exc))
    return failed


def commit(dev, lighting_index):
    send(dev, build_report(lighting_index, FN_FRAME_END))
```

- [ ] **Step 2: Add the subcommands after `cmd_enumerate`**

```python
def cmd_solid(args):
    rgb = parse_color(args.color)
    dev, _ = open_keyboard()
    try:
        lighting = prepare(dev)
        failed = paint(dev, lighting, ALL_ZONES, rgb)
        commit(dev, lighting)
    finally:
        dev.close()
    total = len(single_value_reports(lighting, ALL_ZONES, rgb))
    print(f"painted #{args.color.lstrip('#')}: {total - len(failed)}/{total} chunks accepted")
    for zones, exc in failed:
        print(f"  rejected zones 0x{zones[0]:02x}-0x{zones[-1]:02x}: {exc}")


def cmd_restore(args):
    dev, _ = open_keyboard()
    try:
        set_onboard_mode(dev, MODE_ONBOARD)
    finally:
        dev.close()
    print("keyboard returned to onboard mode")
```

In `build_parser()`, before `return parser`:

```python
    p = subparsers.add_parser("solid", help="rung B: whole keyboard to one color")
    p.add_argument("color", help="6-digit hex RGB, e.g. ff6600")
    p.set_defaults(func=cmd_solid)

    p = subparsers.add_parser("restore", help="hand lighting back to the onboard profile")
    p.set_defaults(func=cmd_restore)
```

- [ ] **Step 3: Offline checks (Review Focus 3)**

```bash
g560ctl/.venv/bin/python -c "
import sys; sys.path.insert(0, 'experiments')
from g815_probe import *
assert parse_color('ff6600') == (0xff, 0x66, 0x00)
assert parse_color('#FF6600') == (0xff, 0x66, 0x00)
for bad in ('ff660', 'gggggg', '', '#ff66001'):
    try: parse_color(bad); raise SystemExit(f'accepted {bad!r}')
    except ProbeError as e: assert '6 hex digits' in str(e)
reps = single_value_reports(0x10, ALL_ZONES, (1, 2, 3))
assert len(reps) == 20 and all(len(r) == 20 for r in reps)
assert reps[0][:7] == bytes([0x11, 0xff, 0x10, 0x6c, 1, 2, 3]) and reps[0][7] == 0x01
assert reps[-1][7:] == bytes([0xf8, 0xf9, 0xfa, 0xfb, 0xfc, 0xfd, 0xfe] + [0xfe] * 6)
assert single_value_reports(0x10, [0x29], (0, 0, 0))[0][7:] == bytes([0x29] * 13)
print('ok')
"
```
Expected: `ok`

- [ ] **Step 4: Run rung B on hardware**

Run: `g560ctl/.venv/bin/python experiments/g815_probe.py solid ff0000`, then `... solid 0000ff`.
Expected: the whole keyboard turns red, then blue (ask the user to confirm visually), and `painted #ff0000: N/20 chunks accepted`. Rejected chunks are acceptable and informative (zones the board doesn't have). The rung passes on a visible color change. Then run `... restore` and confirm the onboard effect comes back. **Gate:** if the color doesn't change, stop and record the output.

- [ ] **Step 5: Update `experiments/README.md`**

Add these rows to the Rungs table:
```markdown
| B | `g560ctl/.venv/bin/python experiments/g815_probe.py solid ff0000` | Whole keyboard one color + frameEnd commit |
| — | `g560ctl/.venv/bin/python experiments/g815_probe.py restore` | Hands lighting back to the onboard profile |
```
Add this section to the findings log, filled from Step 4:
```markdown
### Rung B — solid

- Packet: `11 ff <0x8081 idx> 6c RR GG BB z×13`, commit `11 ff <idx> 7c`; host mode via 0x8100 fn1 `02`.
- Result: <visible change yes/no>; chunks accepted <N>/20; rejected zone ranges <list or none>.
- Onboard effect overrode colors without host mode? <only if observed>
```
Replace each `<...>` with the actual observations.

- [ ] **Step 6: Commit**

```bash
git add experiments/
git commit -m "feat(experiments): G815 probe rung B - solid color and commit frame"
```

---

### Task 3: Rung C (`key`)

**Files:**
- Modify: `experiments/g815_probe.py`
- Modify: `experiments/README.md`

**Interfaces:**
- Consumes: `open_keyboard`, `prepare`, `paint`, `commit`, `parse_color`, `ProbeError`, `build_parser` (Tasks 1–2)
- Produces (used by Task 4): `KEYS: dict[str, int]`, `resolve_key(name: str) -> int` (zone id)

Zone ids ported from g810-led / OpenRGB: for the main key block, zone = HID keyboard usage − 3 (`a` usage 0x04 → zone 0x01). Raw `0xNN` is accepted so rung C can probe a key whose name or id is wrong.

- [ ] **Step 1: Add the key map after `commit`**

```python
def _usage_keys():
    usages = {chr(ord("a") + i): 0x04 + i for i in range(26)}
    usages.update({str(n): 0x1E + (n - 1) for n in range(1, 10)})
    usages["0"] = 0x27
    usages.update({"enter": 0x28, "esc": 0x29, "backspace": 0x2A, "tab": 0x2B, "space": 0x2C})
    usages.update({f"f{n}": 0x3A + (n - 1) for n in range(1, 13)})
    return {name: usage - 3 for name, usage in usages.items()}


KEYS = _usage_keys()


def resolve_key(name):
    text = name.lower()
    if text.startswith("0x"):
        try:
            zone = int(text, 16)
        except ValueError:
            zone = -1
        if 0x01 <= zone <= 0xFE:
            return zone
        raise ProbeError(f"raw zone must be 0x01-0xfe, got {name!r}")
    if text in KEYS:
        return KEYS[text]
    raise ProbeError(f"unknown key {name!r}; known: {', '.join(sorted(KEYS))} or raw 0xNN")
```

- [ ] **Step 2: Add the subcommand after `cmd_restore`**

```python
def cmd_key(args):
    zone = resolve_key(args.key)
    rgb = parse_color(args.color)
    dev, _ = open_keyboard()
    try:
        lighting = prepare(dev)
        failed = paint(dev, lighting, [zone], rgb)
        if failed:
            raise failed[0][1]
        commit(dev, lighting)
    finally:
        dev.close()
    print(f"key {args.key} (zone 0x{zone:02x}) -> #{args.color.lstrip('#')}")
```

In `build_parser()`, before `return parser`:

```python
    p = subparsers.add_parser("key", help="rung C: one key by name")
    p.add_argument("key", help="key name (a, esc, space, f1, ...) or raw zone 0xNN")
    p.add_argument("color", help="6-digit hex RGB, e.g. 00ff00")
    p.set_defaults(func=cmd_key)
```

- [ ] **Step 3: Offline checks (Review Focus 4)**

```bash
g560ctl/.venv/bin/python -c "
import sys; sys.path.insert(0, 'experiments')
from g815_probe import *
assert resolve_key('a') == 0x01 and resolve_key('A') == 0x01
assert resolve_key('esc') == 0x26 and resolve_key('space') == 0x29
assert resolve_key('1') == 0x1b and resolve_key('0') == 0x24 and resolve_key('f12') == 0x42
assert resolve_key('0x68') == 0x68
for bad in ('foo', '0x00', '0xff', '0xzz'):
    try: resolve_key(bad); raise SystemExit(f'accepted {bad!r}')
    except ProbeError: pass
print('ok')
"
```
Expected: `ok`

- [ ] **Step 4: Run rung C on hardware**

First run `g560ctl/.venv/bin/python experiments/g815_probe.py solid 000000` to blank the board. Then run `... key a 00ff00`, `... key esc ff0000`, `... key space 0000ff`, `... key f12 ffffff`. Ask the user to confirm that each named key, **and only that key**, lights up. If a key is wrong, use `key 0xNN` to find the right zone and record the offset. **Gate:** if no single key can be addressed, stop and record that.

- [ ] **Step 5: Update `experiments/README.md`**

Add this row to the Rungs table:
```markdown
| C | `g560ctl/.venv/bin/python experiments/g815_probe.py key a 00ff00` | Per-key addressing by name (or raw zone `0xNN`) |
```
Add this section to the findings log:
```markdown
### Rung C — key

- Zone rule `usage - 3` confirmed for: <keys that lit correctly>
- Mismatches: <key → actual zone, or none>
```
Replace each `<...>` with the actual observations.

- [ ] **Step 6: Commit**

```bash
git add experiments/
git commit -m "feat(experiments): G815 probe rung C - per-key addressing"
```

---

### Task 4: Rung D (`latency`) and the handoff summary

**Files:**
- Modify: `experiments/g815_probe.py`
- Modify: `experiments/README.md`

**Interfaces:**
- Consumes: `open_keyboard`, `prepare`, `single_value_reports`, `send`, `commit`, `resolve_key`, `build_parser` (Tasks 1–3)
- Produces: the final findings log (the spike's deliverable)

One frame here = one acknowledged `setRgbZonesSingleValue` report + one acknowledged `frameEnd`. That is the cheapest possible frame, so it is an upper bound. Reports/sec is printed as well, so Phase 2 can estimate how much a multi-report ripple frame costs.

- [ ] **Step 1: Add the subcommand after `cmd_key`**

```python
def cmd_latency(args):
    zone = resolve_key(args.key)
    colors = [(0xFF, 0x00, 0x00), (0x00, 0x00, 0xFF)]
    dev, _ = open_keyboard()
    try:
        lighting = prepare(dev)
        frames = [single_value_reports(lighting, [zone], rgb)[0] for rgb in colors]
        count = 0
        start = time.monotonic()
        while (elapsed := time.monotonic() - start) < args.seconds:
            send(dev, frames[count % 2])
            commit(dev, lighting)
            count += 1
    finally:
        dev.close()
    fps = count / elapsed
    verdict = "smooth (>=60)" if fps >= 60 else "ok (>=30)" if fps >= 30 else "too slow (<30)"
    print(f"{count} frames in {elapsed:.2f}s on {args.key}: {fps:.1f} frames/s, "
          f"{2 * fps:.1f} reports/s -> {verdict}")
```

In `build_parser()`, before `return parser`:

```python
    p = subparsers.add_parser("latency", help="rung D: sustained updates/sec on one key")
    p.add_argument("key", nargs="?", default="space", help="key to flip (default: space)")
    p.add_argument("--seconds", type=float, default=5.0, help="measurement length")
    p.set_defaults(func=cmd_latency)
```

- [ ] **Step 2: Offline smoke check of the CLI surface**

Run: `g560ctl/.venv/bin/python experiments/g815_probe.py --help` and `g560ctl/.venv/bin/python experiments/g815_probe.py latency --help`
Expected: lists `enumerate, solid, restore, key, latency`. The latency help shows `--seconds`.

- [ ] **Step 3: Run rung D on hardware**

Run `g560ctl/.venv/bin/python experiments/g815_probe.py latency` three times, then once with `latency esc --seconds 10`. The space key should flicker red/blue. Ask the user to type in another window during one run and confirm typing works. Then run `... restore`.
Expected: one summary line per run. Record all four.

- [ ] **Step 4: Finish `experiments/README.md`**

Add this row to the Rungs table:
```markdown
| D | `g560ctl/.venv/bin/python experiments/g815_probe.py latency [KEY] [--seconds N]` | Sustained acknowledged frames/sec |
```
Add these sections to the findings log:
```markdown
### Rung D — latency

- Runs: <each summary line>
- Typing during the run: <works / broke>

## Handoff to Phase 2 (ripple daemon)

- Interface: <hidraw path pattern / usage page 0xFF43 usage 0x0602>, opened with `import hidraw`.
- Packets: setRgbZonesSingleValue (fn 6) and frameEnd (fn 7) on feature 0x8081 at index <idx>; host mode required? <yes/no>.
- Key zones: <rule + exceptions>.
- Budget: ~<reports/s> acknowledged reports/s. A ripple frame touching K distinct colors costs ≈ K/13-zone-chunks + 1 reports, so <fps estimate for a typical ripple>.
```
Replace each `<...>` with measured or observed values.

- [ ] **Step 5: Commit**

```bash
git add experiments/
git commit -m "feat(experiments): G815 probe rung D - latency and findings handoff"
```
