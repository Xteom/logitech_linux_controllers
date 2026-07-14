from __future__ import annotations

import argparse
import sys

from logitech_lighting import (
    LogitechLightingError,
    UnifiedController,
    get_device_config,
    get_default_device,
    parse_color,
    resolve_zones,
    discover_devices,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Control Logitech gaming peripherals lighting on Linux"
    )
    parser.add_argument(
        "--device",
        default=None,
        help="Device ID (e.g., g560). Auto-detected if not specified."
    )
    
    sub = parser.add_subparsers(dest="command", required=True)

    # List devices
    p_list_devices = sub.add_parser("list-devices", help="List supported devices")
    p_list_devices.set_defaults(func="list_devices")

    # Off
    p_off = sub.add_parser("off", help="Turn lights off")
    p_off.add_argument("--zones", default="all", help="Comma-separated zones or aliases")
    p_off.set_defaults(func="off")

    # Solid
    p_solid = sub.add_parser("solid", help="Set a solid RGB color")
    p_solid.add_argument("color", help="6-digit hex RGB value, e.g. ff6600")
    p_solid.add_argument("--zones", default="all", help="Comma-separated zones or aliases")
    p_solid.set_defaults(func="solid")

    # Breathe
    p_breathe = sub.add_parser("breathe", help="Single-color breathing mode")
    p_breathe.add_argument("color", help="6-digit hex RGB value, e.g. 00aaff")
    p_breathe.add_argument("--rate", type=int, default=3000, help="Rate in ms (100-65535)")
    p_breathe.add_argument("--brightness", type=int, default=100, help="Brightness 1-100")
    p_breathe.add_argument("--zones", default="all", help="Comma-separated zones or aliases")
    p_breathe.set_defaults(func="breathe")

    # Cycle
    p_cycle = sub.add_parser("cycle", help="Cycle through colors")
    p_cycle.add_argument("--rate", type=int, default=8000, help="Rate in ms (100-65535)")
    p_cycle.add_argument("--brightness", type=int, default=100, help="Brightness 1-100")
    p_cycle.add_argument("--zones", default="all", help="Comma-separated zones or aliases")
    p_cycle.set_defaults(func="cycle")

    # List zones
    p_list = sub.add_parser("list-zones", help="List supported zones and aliases")
    p_list.set_defaults(func="list_zones")

    # TUI
    p_tui = sub.add_parser("tui", help="Launch the interactive terminal UI")
    p_tui.set_defaults(func="tui")

    return parser


def print_devices() -> None:
    """Print all supported devices."""
    devices = discover_devices()
    print("Supported devices:")
    for device in devices:
        status = "✓ connected" if device.connected else "✗ not found"
        print(f"  {device.config_id:<12} {device.name:<30} {status}")


def print_zones(device_config) -> None:
    """Print zones and aliases for a device."""
    print(f"Zones for {device_config.name}:")
    for zone_name in sorted(device_config.zones.keys()):
        label = device_config.zone_labels.get(zone_name, zone_name)
        print(f"  {zone_name:<16} -> {label}")
    
    print("\nAliases:")
    for alias, zones in sorted(device_config.zone_aliases.items()):
        values = ", ".join(zones)
        print(f"  {alias:<16} -> {values}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        # Handle list-devices without device requirement
        if args.func == "list_devices":
            print_devices()
            return 0

        # Get device config
        device_id = args.device or get_default_device()
        device_config = get_device_config(device_id)
        controller = UnifiedController(device_config)

        # Handle list-zones
        if args.func == "list_zones":
            print_zones(device_config)
            return 0

        # Handle TUI
        if args.func == "tui":
            try:
                from logitech_lighting.tui import run_tui
                return run_tui(controller, device_config)
            except ImportError:
                print("Error: TUI requires textual. Install with: pip install 'textual>=0.50'", file=sys.stderr)
                return 1

        # Resolve zones
        zones = resolve_zones(args.zones, device_config)

        # Handle commands
        if args.func == "off":
            controller.off(zones)
        elif args.func == "solid":
            controller.solid(parse_color(args.color), zones)
        elif args.func == "breathe":
            controller.breathe(
                parse_color(args.color),
                zones,
                rate_ms=args.rate,
                brightness=args.brightness,
            )
        elif args.func == "cycle":
            controller.cycle(
                zones,
                rate_ms=args.rate,
                brightness=args.brightness,
            )
        else:
            parser.print_help()
            return 2

        return 0

    except LogitechLightingError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
