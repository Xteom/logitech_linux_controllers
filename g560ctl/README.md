# g560ctl / logitech_lighting

A Linux CLI/TUI tool to control Logitech gaming peripherals RGB lighting.

## Quick Start

### Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[tui]'
```

### Usage

```bash
# New unified CLI
logitech-lighting list-devices
logitech-lighting list-zones
logitech-lighting solid ff6600 --zones all

# Backward-compatible G560 command
g560ctl list-zones
g560ctl off
g560ctl solid ff6600
g560ctl breathe 00aaff --rate 3000 --brightness 80
g560ctl cycle --rate 8000 --brightness 100
```

## Supported Devices

- **Logitech G560** Gaming Speakers (fully supported)

Future device support is planned through the extensible architecture.

## Features

- Turn lights off
- Solid color mode
- Breathe mode
- Cycle mode
- Select all zones or individual zones
- Device auto-detection
- No hardcoded virtualenv path
- Works well with `pipx`

## Zone Aliases (G560)

- `all` - All zones
- `left` - Left speaker (primary + secondary)
- `right` - Right speaker (primary + secondary)
- `primary` - Both front zones
- `secondary` - Both rear zones
- Individual zones: `left_primary`, `right_primary`, `left_secondary`, `right_secondary`

## udev Rule

To avoid running with `sudo`, create a rule like:

```bash
sudo groupadd -f logitech-lighting
sudo usermod -aG logitech-lighting "$USER"

sudo tee /etc/udev/rules.d/99-logitech-gaming.rules >/dev/null <<'RULE'
SUBSYSTEM=="usb", ATTR{idVendor}=="046d", ATTR{idProduct}=="0a78", MODE="0660", GROUP="logitech-lighting"
RULE

sudo udevadm control --reload-rules
sudo udevadm trigger
```

Then unplug/replug the device and log out/in.

## Architecture

This package provides a unified architecture for controlling multiple Logitech devices:

- **Core modules**: Device-agnostic models, colors, transport
- **Device configs**: Device-specific packet encoding and zone definitions
- **Unified controller**: Single controller that works with any device config
- **Backward compatibility**: `g560ctl` command still works as before

## Adding New Devices

The architecture makes it easy to add new devices:

1. Create a device configuration class implementing the `DeviceConfig` protocol
2. Define device-specific zones, packet structure, and encoding logic
3. Register the device in the device registry
4. The unified controller automatically supports the new device

See `logitech_lighting/devices/g560/config.py` for an example.

## Notes

This project does not currently read the actual lighting state back from the device. Commands write new state but cannot discover existing hardware state.
