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


def build_parser():
    parser = argparse.ArgumentParser(description="G815 lighting probe (Phase 1 spike)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p = subparsers.add_parser("enumerate", help="rung A: find and open the HID++ interface")
    p.set_defaults(func=cmd_enumerate)

    p = subparsers.add_parser("solid", help="rung B: whole keyboard to one color")
    p.add_argument("color", help="6-digit hex RGB, e.g. ff6600")
    p.set_defaults(func=cmd_solid)

    p = subparsers.add_parser("restore", help="hand lighting back to the onboard profile")
    p.set_defaults(func=cmd_restore)

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
