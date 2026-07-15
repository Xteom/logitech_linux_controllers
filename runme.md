# runme — G560 speaker lights (copy-paste commands)

Quick reference for controlling the Logitech **G560** speaker lighting.
Run everything from the repo root. Full docs are in [CLAUDE.md](./CLAUDE.md).

---

## Everyday commands

Use the `./lights` wrapper — it handles the venv path and USB permissions
(re-runs under the `logitech-lighting` group via `sg` when needed).

```bash
# Current setup: front = blue, rear = red
./lights solid 0000ff --zones primary && ./lights solid ff0000 --zones secondary

# Solid color examples
./lights solid ff6600 --zones all          # everything orange
./lights solid 00ff00 --zones left         # left speaker green
./lights solid 0000ff --zones primary      # front zones blue
./lights solid ff0000 --zones secondary    # rear zones red

# Off
./lights off                               # all zones off
./lights off --zones secondary             # rear zones off

# Effects (run on-device)
./lights breathe 00aaff --rate 3000 --brightness 80   # pulsing
./lights cycle --rate 8000 --brightness 100           # spectrum cycle

# Info
./lights list-zones                        # zones + aliases
./lights list-devices                      # detected devices
```

### Options

- **Color** — 6-digit hex RGB, with or without `#` (`ff6600` or `#ff6600`).
- **`--zones`** — comma-separated list; defaults to `all`.
- **`--rate`** — milliseconds, `100`–`65535`.
- **`--brightness`** — `1`–`100`.

### Zones & aliases

| Alias | Expands to |
| --- | --- |
| `all` | all four zones |
| `primary` | both **front** zones |
| `secondary` | both **rear** zones |
| `left` | left speaker (front + rear) |
| `right` | right speaker (front + rear) |
| individual | `left_primary`, `right_primary`, `left_secondary`, `right_secondary` |

"Up / front" = **primary**, "down / rear" = **secondary**.

---

## One-time setup (already done on this machine)

Only needed on a fresh checkout or a different machine.

### 1. Install the CLI (creates the virtualenv)

```bash
python3 -m venv g560ctl/.venv
g560ctl/.venv/bin/pip install -e g560ctl
# optional TUI:
g560ctl/.venv/bin/pip install -e 'g560ctl[tui]'
```

### 2. Grant non-root USB access (needs sudo, run in a real terminal)

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

---

## Troubleshooting

```bash
# Confirm the device is on the USB bus
lsusb -d 046d:0a78

# See what the CLI detects
./lights list-devices
```

- **`Could not claim USB interface`** → the shell lacks the group. Use `./lights`
  (applies `sg`), or open a freshly logged-in terminal.
- **`list-devices` shows the G560 as `✗ not found`** → replug the USB cable.
- **`sg` asks for a password** → you're not in the group yet; re-run setup step 2
  and log out/in.

---

## Run the tests

```bash
g560ctl/.venv/bin/python -m pytest g560ctl/test -q
```
