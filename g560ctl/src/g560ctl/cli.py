from __future__ import annotations

import argparse
import sys

from .colors import parse_color
from .controller import G560Controller
from .models import G560Error, Zone
from .tui import run_tui
from .zones import ZONE_ALIASES, ZONE_LABELS, resolve_zones


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Control Logitech G560 lighting on Linux")
    sub = parser.add_subparsers(dest="command", required=True)

    p_off = sub.add_parser("off", help="Turn lights off")
    p_off.add_argument("--zones", default="all", help="Comma-separated zones or aliases")
    p_off.set_defaults(func="off")

    p_solid = sub.add_parser("solid", help="Set a solid RGB color")
    p_solid.add_argument("color", help="6-digit hex RGB value, e.g. ff6600")
    p_solid.add_argument("--zones", default="all", help="Comma-separated zones or aliases")
    p_solid.set_defaults(func="solid")

    p_breathe = sub.add_parser("breathe", help="Single-color breathing mode")
    p_breathe.add_argument("color", help="6-digit hex RGB value, e.g. 00aaff")
    p_breathe.add_argument("--rate", type=int, default=3000, help="Rate in ms (100-65535)")
    p_breathe.add_argument("--brightness", type=int, default=100, help="Brightness 1-100")
    p_breathe.add_argument("--zones", default="all", help="Comma-separated zones or aliases")
    p_breathe.set_defaults(func="breathe")

    p_cycle = sub.add_parser("cycle", help="Cycle through colors")
    p_cycle.add_argument("--rate", type=int, default=8000, help="Rate in ms (100-65535)")
    p_cycle.add_argument("--brightness", type=int, default=100, help="Brightness 1-100")
    p_cycle.add_argument("--zones", default="all", help="Comma-separated zones or aliases")
    p_cycle.set_defaults(func="cycle")

    p_list = sub.add_parser("list-zones", help="List supported zones and aliases")
    p_list.set_defaults(func="list_zones")

    p_tui = sub.add_parser("tui", help="Launch the interactive terminal UI")
    p_tui.set_defaults(func="tui")

    return parser


def print_zones() -> None:
    print("Zones:")
    for zone in Zone:
        print(f"  {zone.value:<16} -> {ZONE_LABELS[zone]}")
    print("\nAliases:")
    for alias, zones in sorted(ZONE_ALIASES.items()):
        values = ", ".join(zone.value for zone in zones)
        print(f"  {alias:<16} -> {values}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    controller = G560Controller()

    try:
        if args.func == "list_zones":
            print_zones()
            return 0

        if args.func == "tui":
            return run_tui(controller)

        zones = resolve_zones(args.zones)

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

    except G560Error as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1