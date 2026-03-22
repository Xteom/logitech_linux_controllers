#!/home/xteom/Documents/personal/speakers_ligth/.venv/bin/python
"""
logitech_g560.py
Simple Logitech G560 LED controller for Linux.

Requires:
  pip install pyusb
  and usually a udev rule or sudo/root access

Examples:
  sudo ./logitech_g560.py off
  sudo ./logitech_g560.py solid 000000
  sudo ./logitech_g560.py solid ff6600
  sudo ./logitech_g560.py breathe 00aaff 3000 80
  sudo ./logitech_g560.py cycle 8000 100
"""

from __future__ import annotations

import argparse
import binascii
import re
import sys
from dataclasses import dataclass

import usb.core
import usb.util

VENDOR_ID = 0x046D
PRODUCT_ID = 0x0A78
INTERFACE = 0x02

# These zone IDs are inferred from the existing G560 scripts:
# 00 left_secondary, 01 right_secondary, 02 left_primary, 03 right_primary
ZONES = ("00", "01", "02", "03")

PREFIX = "11ff043a"
SUFFIX = "000000000000"


class G560Error(Exception):
    pass


@dataclass
class DeviceSession:
    device: usb.core.Device
    detached_kernel_driver: bool = False

    def close(self) -> None:
        try:
            usb.util.release_interface(self.device, INTERFACE)
        except Exception:
            pass

        if self.detached_kernel_driver:
            try:
                self.device.attach_kernel_driver(INTERFACE)
            except Exception:
                pass

        try:
            usb.util.dispose_resources(self.device)
        except Exception:
            pass


def parse_color(value: str) -> str:
    value = value.strip().lower()
    if value.startswith("#"):
        value = value[1:]
    if not re.fullmatch(r"[0-9a-f]{6}", value):
        raise G560Error("Color must be a 6-digit hex RGB value, e.g. ff6600")
    return value


def clamp_rate(ms: int) -> str:
    # Matches the community scripts: clamp to [100, 65535] and encode as 4 hex chars
    ms = max(100, min(65535, int(ms)))
    return f"{ms:04x}"


def clamp_brightness(percent: int) -> str:
    # Matches the community scripts: clamp to [1, 100]
    percent = max(1, min(100, int(percent)))
    return f"{percent:02x}"


def open_device() -> DeviceSession:
    dev = usb.core.find(idVendor=VENDOR_ID, idProduct=PRODUCT_ID)
    if dev is None:
        raise G560Error(
            "Logitech G560 not found. Check USB connection, permissions, or product support."
        )

    detached = False

    try:
        if dev.is_kernel_driver_active(INTERFACE):
            dev.detach_kernel_driver(INTERFACE)
            detached = True
    except (NotImplementedError, usb.core.USBError):
        # Some systems/backends do not expose this cleanly.
        pass

    try:
        usb.util.claim_interface(dev, INTERFACE)
    except usb.core.USBError as e:
        raise G560Error(
            f"Could not claim USB interface {INTERFACE}. "
            f"Try running as root/sudo or add a udev rule. Details: {e}"
        ) from e

    return DeviceSession(device=dev, detached_kernel_driver=detached)


def send_raw(session: DeviceSession, hex_payload: str) -> None:
    try:
        session.device.ctrl_transfer(
            0x21,          # bmRequestType: Host-to-device | Class | Interface
            0x09,          # bRequest: SET_REPORT
            0x0211,        # wValue
            INTERFACE,     # wIndex
            binascii.unhexlify(hex_payload),
        )
    except usb.core.USBError as e:
        raise G560Error(f"USB control transfer failed: {e}") from e


def send_zone_command(session: DeviceSession, zone_hex: str, mode_hex: str, data_hex: str) -> None:
    payload = PREFIX + zone_hex + mode_hex + data_hex + SUFFIX
    send_raw(session, payload)


def send_all_zones(session: DeviceSession, mode_hex: str, data_hex: str) -> None:
    for zone in ZONES:
        send_zone_command(session, zone, mode_hex, data_hex)


def cmd_solid(session: DeviceSession, color: str) -> None:
    # Community scripts use mode 01 and append 5 zero bytes after RGB.
    data = color + "0000000000"
    send_all_zones(session, "01", data)


def cmd_off(session: DeviceSession) -> None:
    # "Off" is implemented as solid black in the cleaner fork.
    cmd_solid(session, "000000")


def cmd_breathe(session: DeviceSession, color: str, rate_ms: int, brightness: int) -> None:
    data = color + clamp_rate(rate_ms) + "00" + clamp_brightness(brightness) + "00"
    send_all_zones(session, "04", data)


def cmd_cycle(session: DeviceSession, rate_ms: int, brightness: int) -> None:
    data = "0000000000" + clamp_rate(rate_ms) + clamp_brightness(brightness)
    send_all_zones(session, "02", data)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Control Logitech G560 lighting on Linux")
    sub = parser.add_subparsers(dest="command", required=True)

    p_off = sub.add_parser("off", help="Turn lights off")
    p_off.set_defaults(func="off")

    p_solid = sub.add_parser("solid", help="Set a solid RGB color")
    p_solid.add_argument("color", help="RGB hex, e.g. ff6600 or #ff6600")
    p_solid.set_defaults(func="solid")

    p_breathe = sub.add_parser("breathe", help="Single-color breathing mode")
    p_breathe.add_argument("color", help="RGB hex, e.g. 00aaff")
    p_breathe.add_argument("rate", nargs="?", type=int, default=10000, help="Rate in ms (100-65535)")
    p_breathe.add_argument("brightness", nargs="?", type=int, default=100, help="Brightness 1-100")
    p_breathe.set_defaults(func="breathe")

    p_cycle = sub.add_parser("cycle", help="Cycle through all colors")
    p_cycle.add_argument("rate", nargs="?", type=int, default=10000, help="Rate in ms (100-65535)")
    p_cycle.add_argument("brightness", nargs="?", type=int, default=100, help="Brightness 1-100")
    p_cycle.set_defaults(func="cycle")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        session = open_device()
    except G560Error as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    try:
        if args.func == "off":
            cmd_off(session)
        elif args.func == "solid":
            cmd_solid(session, parse_color(args.color))
        elif args.func == "breathe":
            cmd_breathe(session, parse_color(args.color), args.rate, args.brightness)
        elif args.func == "cycle":
            cmd_cycle(session, args.rate, args.brightness)
        else:
            parser.print_help()
            return 2

        return 0

    except G560Error as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())