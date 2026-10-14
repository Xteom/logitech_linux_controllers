#!/usr/bin/env python3
"""Gate B probe: XI2.2 raw key presses from the G815 only, via python-xlib.

python-xlib 0.29's helper negotiates XI 2.0 and has no RawKeyPress decoder,
so this negotiates 2.2 itself (FIRST, before any other XI call) and registers
its own decoder for XI_RawKeyPress.
Run: g560ctl/.venv/bin/python experiments/g815_gate_b.py
Prints only key NAMES for G815 presses (never logs anything else).
"""
import sys

from Xlib import display
from Xlib.ext import xinput
from Xlib.protocol import rq

from logitech_lighting.devices.g815.layout import BY_EVDEV

G815_NAME = "Logitech G815 RGB MECHANICAL GAMING KEYBOARD"
RAW_KEY_PRESS = 13          # XI_RawKeyPress
HIERARCHY_CHANGED = 11      # XI_HierarchyChanged

RawKeyEventData = rq.Struct(
    rq.Card16("deviceid"),
    rq.Card32("time"),
    rq.Card32("detail"),
    rq.Card16("sourceid"),
    rq.Card16("valuators_len"),
    rq.Card32("flags"),
    rq.Pad(4),
)


def g815_ids(d):
    info = d.xinput_query_device(xinput.AllDevices)
    return {dev.deviceid for dev in info.devices
            if dev.name.startswith(G815_NAME) and dev.use == xinput.SlaveKeyboard}


def main():
    d = display.Display()
    opcode = d.display.get_extension_major("XInputExtension")
    v = xinput.XIQueryVersion(display=d.display, opcode=opcode, major_version=2, minor_version=2)
    print(f"XI negotiated {v.major_version}.{v.minor_version}")
    if (v.major_version, v.minor_version) < (2, 1):
        print("FAIL: server XI < 2.1")
        return 1
    d.ge_add_event_data(opcode, RAW_KEY_PRESS, RawKeyEventData)  # method lives on Display, not d.display
    root = d.screen().root
    root.xinput_select_events([
        (xinput.AllMasterDevices, 1 << RAW_KEY_PRESS),
        (xinput.AllDevices, 1 << HIERARCHY_CHANGED),
    ])
    ids = g815_ids(d)
    print("G815 slave keyboard ids:", sorted(ids))
    while True:
        ev = d.next_event()
        if getattr(ev, "evtype", None) == HIERARCHY_CHANGED:
            ids = g815_ids(d)
            print("hierarchy changed; G815 ids now:", sorted(ids))
        elif getattr(ev, "evtype", None) == RAW_KEY_PRESS:
            data = ev.data
            if data.sourceid not in ids:
                print("(ignored: other device)")
                continue
            key = BY_EVDEV.get(data.detail - 8)
            print("G815 press:", key.name if key else "(unmapped)")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
