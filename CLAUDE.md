# Logitech G560 speaker lighting — agent guide

This repo controls the RGB lighting on a **Logitech G560** gaming speaker set on
Linux. If you are an AI agent asked to "change the lights", everything you need
is below.

## TL;DR — change the lights

Use the `./lights` wrapper at the repo root. It hides the virtualenv path and
the USB-permission handling, so a single call just works:

```bash
./lights solid 0000ff --zones primary      # front zones -> blue
./lights solid ff0000 --zones secondary    # rear zones  -> red
./lights solid ff6600 --zones all          # everything  -> orange
./lights off                               # all zones off
```

Prefer `./lights` over calling the CLI directly — it transparently re-runs
under the `logitech-lighting` group (via `sg`) when the current shell doesn't
carry that group yet. See [Why the `sg` wrapper](#why-the-sg-wrapper).

## Commands

`./lights <command>` accepts:

| Command | Purpose | Example |
| --- | --- | --- |
| `solid <hex>` | Set a solid color | `./lights solid 00ff00 --zones left` |
| `off` | Turn zones off | `./lights off --zones secondary` |
| `breathe <hex>` | Pulsing single color | `./lights breathe 00aaff --rate 3000 --brightness 80` |
| `cycle` | Cycle through the spectrum | `./lights cycle --rate 8000 --brightness 100` |
| `list-zones` | Show zones + aliases | `./lights list-zones` |
| `list-devices` | Show detected devices | `./lights list-devices` |

- **Color** is a 6-digit hex RGB value, with or without a leading `#` (e.g.
  `ff6600` or `#ff6600`).
- **`--zones`** takes a comma-separated list of zones or aliases; defaults to
  `all`.
- **`--rate`** is in milliseconds (100–65535); **`--brightness`** is 1–100.

## Zones (G560)

The G560 has four addressable zones — a front ("primary") and rear
("secondary") zone on each speaker. Convenient aliases:

| Alias | Expands to |
| --- | --- |
| `all` | all four zones |
| `primary` | both **front** zones |
| `secondary` | both **rear** zones |
| `left` | left speaker (front + rear) |
| `right` | right speaker (front + rear) |
| individual | `left_primary`, `right_primary`, `left_secondary`, `right_secondary` |

"Up/front" = **primary**, "down/rear" = **secondary**.

## Current state

The lights are configured as **primary (front) = blue `0000ff`**, **secondary
(rear) = red `ff0000`**. The device does not report its state back, so this is
recorded here rather than read from hardware. Re-apply with:

```bash
./lights solid 0000ff --zones primary && ./lights solid ff0000 --zones secondary
```

## Why the `sg` wrapper

The udev rule (see [Setup](#setup)) makes the USB device node owned by group
`logitech-lighting`, mode `0660`. To write lighting changes, the calling
process must be a member of that group. Group membership is fixed when a process
starts, so a shell (or an agent session) launched **before** the group was
created — or before you last logged in — won't have it, and a direct CLI call
fails with:

```
Error: Could not claim USB interface 2. Try a udev rule or root privileges.
```

`./lights` detects this and re-execs the command under `sg logitech-lighting`,
which re-reads group membership at invocation. No password is needed because the
user is already a member. A terminal opened after a fresh login has the group
automatically and could call the CLI directly, but `./lights` works either way.

## Setup

Both steps below are **one-time** and were already completed on this machine.
They are documented for a fresh checkout or a different machine.

**1. Install the CLI (creates the project virtualenv):**

```bash
python3 -m venv g560ctl/.venv
g560ctl/.venv/bin/pip install -e g560ctl
# optional TUI: g560ctl/.venv/bin/pip install -e 'g560ctl[tui]'
```

**2. Grant non-root USB access (needs sudo; run in a real terminal):**

```bash
sudo groupadd -f logitech-lighting
sudo usermod -aG logitech-lighting "$USER"
sudo tee /etc/udev/rules.d/99-logitech-gaming.rules >/dev/null <<'RULE'
SUBSYSTEM=="usb", ATTR{idVendor}=="046d", ATTR{idProduct}=="0a78", MODE="0660", GROUP="logitech-lighting"
RULE
sudo udevadm control --reload-rules
sudo udevadm trigger
```

Then unplug/replug the speakers. New logins pick up the group automatically;
existing sessions use the `sg` fallback that `./lights` applies for you.

## Troubleshooting

- **`Could not claim USB interface`** → the process lacks the group. Use
  `./lights` (it applies `sg`), or open a freshly logged-in terminal.
- **`list-devices` shows the G560 as `✗ not found`** → replug the USB cable and
  confirm `lsusb -d 046d:0a78` lists it.
- **`sg` asks for a password** → the user isn't in the group. Re-run step 2 of
  Setup (`usermod -aG`) and log out/in.

## Testing

```bash
g560ctl/.venv/bin/python -m pytest g560ctl/test -q
```

## Codebase layout (for maintainers)

The **live** implementation is the `logitech_lighting` package — a unified,
multi-device architecture. Both console scripts (`logitech-lighting` and the
backward-compatible `g560ctl`) run it; `g560ctl/src/g560ctl/cli.py` is only a
thin shim that imports it.

```
g560ctl/
  src/
    logitech_lighting/        # LIVE code
      cli.py                  #   CLI entry point (both scripts land here)
      controller.py           #   UnifiedController
      core/                   #   device-agnostic: colors, models, transport, exceptions
      devices/g560/config.py  #   G560 zones + packet encoding
      tui.py                  #   textual TUI
    g560ctl/                  # LEGACY / DEAD CODE (kept for reference)
      cli.py                  #   live shim -> logitech_lighting
      colors|controller|device|models|zones|tui.py   # superseded; see file-top banners
  test/
    test_new_*.py             # tests for the live logitech_lighting package
    test_*.py                 # LEGACY tests for the dead g560ctl modules
```

The dead `g560ctl/*` modules and their `test_*.py` carry a `DEAD CODE` banner at
the top of each file naming the `logitech_lighting` module that replaced them.
They are retained deliberately — **do not delete them, and do not extend them.**
New work goes in `logitech_lighting`.
