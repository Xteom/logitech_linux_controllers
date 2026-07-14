# g560ctl

A small Linux CLI/TUI tool to control Logitech G560 lighting.

## Features

- Turn lights off
- Solid color mode
- Breathe mode
- Cycle mode
- Select all zones or individual zones
- Optional Textual terminal UI
- No hardcoded virtualenv path
- Works well with `pipx`

## Installation

### Development install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[tui]'
With pipx
pipx install '.[tui]'
udev rule

To avoid running with sudo, create a rule like:

sudo groupadd -f g560
sudo usermod -aG g560 "$USER"

sudo tee /etc/udev/rules.d/99-logitech-g560.rules >/dev/null <<'EOF'
SUBSYSTEM=="usb", ATTR{idVendor}=="046d", ATTR{idProduct}=="0a78", MODE="0660", GROUP="g560"
EOF

sudo udevadm control --reload-rules
sudo udevadm trigger

Then unplug/replug the speaker and log out/in.

Usage
g560ctl list-zones
g560ctl off
g560ctl solid ff6600
g560ctl solid 00aaff --zones left_primary,right_primary
g560ctl breathe 00aaff --rate 3000 --brightness 80
g560ctl cycle --rate 8000 --brightness 100
g560ctl tui
Zone aliases
all
left
right
primary
secondary
left_primary
right_primary
left_secondary
right_secondary
Notes

This project does not currently read the actual lighting state back from the device. The TUI can restore the last known committed state from the session, but it cannot discover unknown pre-launch state from hardware.


---

# `src/g560ctl/__init__.py`

```python
__all__ = ["__version__"]

__version__ = "0.1.0"