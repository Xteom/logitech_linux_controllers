# Logitech Lighting Control

A unified Linux CLI/TUI for controlling RGB lighting on Logitech gaming peripherals over USB.

## Supported Devices

- **Logitech G560** Gaming Speakers

Future support planned for G733 headset and other Logitech gaming devices.

## Features

- Off / solid / breathe / cycle modes
- Per-zone control or grouped aliases (`all`, `left`, `right`, `primary`, `secondary`)
- Clean CLI with device auto-detection
- Designed for isolated installation via `pipx`
- Extensible architecture for supporting multiple device types

## Installation

### Development

```bash
cd g560ctl
python -m venv .venv
source .venv/bin/activate
pip install -e '.[tui]'
```

### End-user (recommended)

```bash
cd g560ctl
pipx install '.[tui]'
```

## Usage

The package provides two CLI commands:
- `logitech-lighting` - New unified CLI for all devices
- `g560ctl` - Backward-compatible G560-specific command

### Basic Commands

```bash
# List supported devices
logitech-lighting list-devices

# List zones for your device
logitech-lighting list-zones

# Control lighting
logitech-lighting off --zones all
logitech-lighting solid ff6600 --zones left_primary,right_primary
logitech-lighting breathe 00aaff --rate 3000 --brightness 80 --zones all
logitech-lighting cycle --rate 8000 --brightness 100 --zones secondary

# Specify device explicitly (auto-detected by default)
logitech-lighting --device g560 solid ff6600
```

### G560-Specific Commands (backward compatible)

```bash
g560ctl list-zones
g560ctl off --zones all
g560ctl solid ff6600 --zones left
g560ctl breathe 00aaff --rate 3000 --brightness 80
```

## Permissions

Use a udev rule to avoid `sudo`.

Example (preferred with dedicated group):

```bash
sudo groupadd -f logitech-lighting
sudo usermod -aG logitech-lighting "$USER"
sudo tee /etc/udev/rules.d/99-logitech-gaming.rules >/dev/null <<'RULE'
# Logitech G560 Gaming Speakers
SUBSYSTEM=="usb", ATTR{idVendor}=="046d", ATTR{idProduct}=="0a78", MODE="0660", GROUP="logitech-lighting"
RULE
sudo udevadm control --reload-rules
sudo udevadm trigger
```

Then unplug/replug the device and log out/in if group membership changed.

## Architecture

The codebase is organized to support multiple Logitech devices:

```
g560ctl/src/
├── logitech_lighting/          # Main package
│   ├── core/                   # Device-agnostic core
│   │   ├── models.py           # Common models (Color, Mode, etc.)
│   │   ├── colors.py           # Color utilities
│   │   ├── transport.py        # USB transport layer
│   │   └── exceptions.py       # Error types
│   ├── devices/                # Device-specific implementations
│   │   ├── base.py             # Device configuration protocol
│   │   └── g560/               # G560 configuration
│   │       └── config.py       # G560-specific packet encoding
│   ├── controller.py           # Unified controller
│   ├── cli.py                  # Main CLI
│   └── utils.py                # Zone resolution utilities
└── g560ctl/                    # Backward-compatible wrapper
    └── cli.py                  # Delegates to logitech_lighting
```

## Adding New Devices

To add support for a new device:

1. Create a new device config in `logitech_lighting/devices/<device_name>/config.py`
2. Implement the `DeviceConfig` protocol
3. Register the device in `logitech_lighting/devices/__init__.py`
4. Add tests in `test/`

The unified controller automatically works with any device configuration.

## Notes

- The current design writes lighting state but does not read the current state back from the device.
- TUI support is planned for the refactored architecture.

## Legacy Files

Legacy standalone scripts have been moved to `archive/legacy_scripts/` for reference.
