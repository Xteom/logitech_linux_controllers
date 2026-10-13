# G815 static controller experiment — design

**Date:** 2026-07-14
**Status:** Approved (design)
**Type:** Phase 1 spike (throwaway experiment)

## Context

This repo controls the Logitech **G560** speaker lighting on Linux via the
`logitech_lighting` package. The goal now is to add reactive **ripple-on-keypress**
lighting for the connected Logitech **G815 mechanical keyboard** (`046d:c33f`),
following the same playbook we used for the speakers: study existing repos, lift
the useful protocol/architecture knowledge, and write our own clean Python
implementation. We explicitly do **not** want to depend on OpenRGB — only to be
inspired by it and by g810-led / keyleds.

### Why the keyboard is not like the speaker

The G560 is a "dumb" USB target: we detach its kernel driver and send a single
`ctrl_transfer`, and the device holds the effect (breathe/cycle run on-device).
The G815:

- has **no built-in "ripple on keypress" mode** we can trigger — a ripple must
  be produced by a persistent host-side daemon that listens to keystrokes and
  streams per-key color frames to the keyboard; and
- exposes its lighting on a separate **HID++ vendor interface**. We must **not**
  detach the kernel driver from the active keyboard interface, or typing would
  stop. The safe path is **hidraw** (via `hidapi`), which reaches the vendor
  collection without disturbing the input driver.

## Three-phase decomposition

Each phase is an independent sub-project with its own spec → plan → implementation
cycle. This document covers **Phase 1 only**.

1. **Phase 1 — Static controller experiment** (this doc): a throwaway spike that
   proves we can talk to the G815 and set key colors from Python, no OpenRGB.
   This is the riskiest unknown, de-risked first, in isolation.
2. **Phase 2 — Ripple daemon**: the reactive keypress effect (evdev listener +
   render loop), building on the transport proven in Phase 1.
3. **Phase 3 — Full CLI keyboard controller**: productionize into the
   `logitech_lighting` package, accessible like `./lights`.

## Existing repos we borrow from

- **g810-led** — has the G815 per-key wire protocol reverse-engineered (per-key
  address map + commit-frame packet). Source of the byte formats we port.
- **OpenRGB** (`LogitechG815Controller`) — cross-check for the same protocol.
- **keyleds** — the reactive-daemon *architecture* (evdev + render loop + effect
  plugins). Does **not** support the G815, so it informs Phase 2, not the wire
  protocol.

Protocol facts are not copyrightable; we reimplement cleanly in Python (as we did
for the G560).

## Goal & non-goals

**Goal:** validated protocol knowledge — enough confidence to design Phase 2.

**Non-goals (Phase 1):** no keypress listening, no animation, no changes to the
live `logitech_lighting` package, no reusable/production code. Nothing here is
imported by the package.

## Transport approach (decision)

**Chosen: `hidapi` (Python `hid`) + protocol ported from g810-led.**

Opens the G815's HID++ **vendor collection** (usage page `0xFF00`) and writes
20-byte HID++ reports; the kernel keeps its keyboard driver attached, so typing is
never interrupted.

Rejected alternatives:

- **pyusb** (already a repo dep): reaching the HID++ interface this way requires
  detaching the kernel driver from a keyboard interface — a bug could freeze
  typing mid-session. Wrong tool for a live keyboard.
- **raw `/dev/hidrawN`** (`os.write`, no library): zero deps and maximally
  transparent, but requires manually locating the hidraw node and hand-rolling
  everything. Kept as a fallback / mental model only.

## Structure

```
experiments/
  g815_probe.py          # the whole spike — CLI with A/B/C/D subcommands
  README.md              # how to run it, what each rung proves, findings log
  99-logitech-g815.rules # udev rule for hidraw access (documented, applied once)
```

- New dependency: `hidapi` (Python `hid`), installed into `g560ctl/.venv`.
- The script is **not** imported by `logitech_lighting`; it stays isolated in
  `experiments/`.
- No changes to `logitech_lighting/` in Phase 1.

## Transport core (inside the script)

Three small functions — the entire keyboard-facing surface:

- `open_keyboard()` — enumerate `046d:c33f`, select the **HID++ vendor
  collection** by usage page `0xFF00` (not the keyboard collection), open via
  hidraw. Never detaches the input driver.
- `send(report_bytes)` — write one 20-byte HID++ report.
- `commit()` — the G815 buffers per-key colors and only displays them after a
  "commit frame" packet; this sends it. Exact commit/address bytes are ported
  from g810-led and confirmed by rung B.

## The A→D ladder (success bar: through D)

Each subcommand is one rung; each rung is a real go/no-go gate. If a rung fails,
stop there.

| Rung | Subcommand | Proves |
| --- | --- | --- |
| A | `python experiments/g815_probe.py enumerate` | Opens the correct HID++ vendor interface without disturbing typing; lists interfaces and shows which we'll use. |
| B | `python experiments/g815_probe.py solid RRGGBB` | Whole keyboard to one color + commit — basic control and the commit-frame step. |
| C | `python experiments/g815_probe.py key KEYNAME RRGGBB` | One key by name — per-key addressing, which the ripple depends on. |
| D | `python experiments/g815_probe.py latency [KEYNAME]` | Flips a key's color in a loop and prints sustained updates/sec, so we know with a number whether a smooth ripple (~30–60 fps) is realistic. |

## Permissions / udev

hidraw needs its own node rule (the speaker's `usb`-subsystem rule doesn't cover
it):

```
KERNEL=="hidraw*", ATTRS{idVendor}=="046d", ATTRS{idProduct}=="c33f", MODE="0660", GROUP="logitech-lighting"
```

Reuses the existing `logitech-lighting` group, so the `./lights` group / `sg`
story carries over. One-time `sudo` step, run in a real terminal (same pattern as
the speaker setup), documented in `experiments/README.md`.

## Error handling & safety

- **Typing safety is the top invariant.** The script asserts it opened the vendor
  collection (usage page `0xFF00`) and refuses to touch the boot-keyboard
  interface. If it cannot find the vendor collection, it aborts with a clear
  message rather than guessing.
- Clear, actionable errors for the three likely failures: device not found
  (replug), permission denied (udev/group — same hint as `./lights`),
  wrong-interface / commit-failed (protocol mismatch to investigate).
- The script only ever **writes** lighting; it never remaps or captures keys in
  Phase 1 (keypress listening is Phase 2).

## Deliverable (handoff to Phase 2)

A short **findings log** in `experiments/README.md` recording:

- which interface / usage page worked,
- the confirmed solid + per-key packet formats, and
- the measured update rate from rung D.

That log — not reusable code — is the spike's deliverable and the input to the
Phase 2 (ripple daemon) spec.

## Testing

This is a hardware spike; "tests" are the A→D rungs run against the real device,
each observed visually (the keyboard changes color) or numerically (rung D prints
Hz). No unit-test suite is added in Phase 1. Production tests arrive with Phase 3.
