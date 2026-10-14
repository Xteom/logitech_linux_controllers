#!/usr/bin/env python3
"""Gate A probe: verify the G815 claim sequence, write echoes, and committed fps.

Throwaway, like experiments/g815_probe.py. Run with the project venv:
  g560ctl/.venv/bin/python experiments/g815_gate_a.py <subcommand>
"""
import argparse
import random
import sys
import time

import hidraw  # never `hid` (libusb backend detaches the keyboard driver)

from logitech_lighting.devices.g815.frame import FN_FRAME_END, ResyncRotor, encode
from logitech_lighting.devices.g815.layout import BY_NAME, KEYS, PHASE1_VALID_ZONES
from logitech_lighting.devices.g815.presets import BASE, PRESETS
from logitech_lighting.devices.g815.ripple import Ripple

VID, PID = 0x046D, 0xC33F
FEATURES = {"root": 0x0000, "perkey": 0x8081, "effects": 0x8071, "onboard": 0x8100, "disable_keys": 0x4522,
            "gkey": 0x8010, "mkeys": 0x8020}
SW_ACTIVE, SW_RELEASE = bytes([0x01, 0x03, 0x04]), bytes([0x01, 0x00, 0x00])


class Dev:
    def __init__(self):
        entry = next(e for e in hidraw.enumerate(VID, PID)
                     if e["usage_page"] == 0xFF43 and e["usage"] == 0x0602)
        self.h = hidraw.device()
        self.h.open_path(entry["path"])
        self.sw = 0
        self.idx = {}

    def next_sw(self):
        self.sw = self.sw % 15 + 1
        return self.sw

    def report(self, feat, fn, params=b"", sw=None):
        sw = self.next_sw() if sw is None else sw
        return (bytes([0x11, 0xFF, feat, (fn << 4) | sw]) + bytes(params)).ljust(20, b"\x00")

    def read(self, ms):
        r = bytes(self.h.read(64, ms))
        return r if len(r) >= 6 and r[0] == 0x11 else None

    def request(self, feat, fn, params=b"", timeout=1.0):
        """Send one request, wait for its reply; return (kind, reply)."""
        rep = self.report(feat, fn, params)
        self.h.write(rep)
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            r = self.read(50)
            if r is None:
                continue
            if r[2] == 0xFF and r[3] == rep[2] and r[4] == rep[3]:
                return "error", r
            if r[2] == rep[2] and r[3] == rep[3]:
                return "ok", r
        return "timeout", None

    def discover(self):
        for name, fid in FEATURES.items():
            if name == "root":
                self.idx[name] = 0
                continue
            kind, r = self.request(0, 0, fid.to_bytes(2, "big"))
            self.idx[name] = r[4] if kind == "ok" and r[4] else None
        return self.idx


def cmd_claim(args):
    d = Dev()
    print("features:", {k: (hex(v) if v is not None else None) for k, v in d.discover().items()})
    if d.idx["onboard"]:
        print("onboard host mode:", d.request(d.idx["onboard"], 1, b"\x02")[0])
    if d.idx["effects"] and not args.no_sw_control:
        print("SetSWControl SW_ACTIVE:", d.request(d.idx["effects"], 5, SW_ACTIVE)[0])
    zones = set()
    for page in range(3):
        kind, r = d.request(d.idx["perkey"], 0, bytes([0x00, page, 0x00]))
        if kind != "ok":
            print(f"zone page {page}: {kind}")
            continue
        bitmap = r[6:20]
        zones |= {page * 112 + i * 8 + b for i, byte in enumerate(bitmap) for b in range(8) if byte >> b & 1}
    print("discovered zones:", len(zones), "== phase1:", zones == set(PHASE1_VALID_ZONES))
    print("  only discovered:", sorted(hex(z) for z in zones - PHASE1_VALID_ZONES))
    print("  only phase1:    ", sorted(hex(z) for z in PHASE1_VALID_ZONES - zones))
    base = {k.zone: BASE for k in KEYS}
    for fn, params in encode(None, base, frozenset(PHASE1_VALID_ZONES)):
        print(f"  base write fn{fn}:", d.request(d.idx["perkey"], fn, params)[0])
    print("frameEnd:", d.request(d.idx["perkey"], FN_FRAME_END, b"\x00")[0])
    print("base painted; watch the keyboard for 60 s without touching anything")


def cmd_release(args):
    d = Dev()
    d.discover()
    if d.idx["effects"]:
        print("SetSWControl release:", d.request(d.idx["effects"], 5, SW_RELEASE)[0])
    if d.idx["onboard"]:
        print("onboard mode:", d.request(d.idx["onboard"], 1, b"\x01")[0])
        if args.reselect_profile:                       # onboard mode alone keeps our last frame
            kind, r = d.request(d.idx["onboard"], 4)    # getCurrentProfile
            print("current profile:", kind, r[4:6].hex(" ") if r else None)
            if kind == "ok":
                print("reselect profile:", d.request(d.idx["onboard"], 3, r[4:6])[0])  # setCurrentProfile


def cmd_zone(args):
    d = Dev()
    d.discover()
    zone, rgb = int(args.zone, 16), bytes.fromhex(args.color)
    print("fn1:", d.request(d.idx["perkey"], 1, bytes([zone]) + rgb)[0])
    print("frameEnd:", d.request(d.idx["perkey"], FN_FRAME_END, b"\x00")[0])


def cmd_echo(args):
    d = Dev()
    d.discover()
    pk = d.idx["perkey"]
    probes = {
        "fn1 individual": (1, bytes([0x01, 0x10, 0x20, 0x30])),
        "fn5 range": (5, bytes([0x02, 0x04, 0x40, 0x50, 0x60])),
        "fn6 single": (6, bytes([0x70, 0x80, 0x90] + [0x05] * 13)),
    }
    for name, (fn, params) in probes.items():
        kind, r = d.request(pk, fn, params)
        echoed = kind == "ok" and r[4:4 + len(params)] == params
        print(f"{name}: {kind}, echoes params: {echoed}, reply params: {r[4:20].hex(' ') if r else None}")
    print("frameEnd:", d.request(pk, FN_FRAME_END, b"\x00")[0])
    ping = random.randrange(1, 256)
    kind, r = d.request(0, 1, bytes([0x00, 0x00, ping]))
    print(f"ping {ping:#04x}: {kind}, echoed byte at params[2]: {r[6] == ping if r else None}")
    # Ordering: 6 pipelined fn1 writes with distinct colors; record reply order.
    sent = []
    for i in range(6):
        rep = d.report(pk, 1, bytes([0x01, i, i, i]))
        d.h.write(rep)
        sent.append(rep[3])
    got, errors, end = [], [], time.monotonic() + 1.0
    while len(got) < 6 and time.monotonic() < end:
        r = d.read(50)
        if r is not None and r[2] == pk:
            got.append(r[3])
        elif r is not None and r[2] == 0xFF and r[3] == pk:
            errors.append(f"{r[4]:#04x}:err{r[5]:#04x}")
    print("ordering: sent", [hex(s) for s in sent], "got", [hex(g) for g in got], "in order:", got == sent)
    print("ordering errors (request byte:error code):", errors)
    d.request(pk, FN_FRAME_END, b"\x00")


def cmd_gkeys(args):
    """Divert G/M keys (0x8010 fn2 [01], as Solaar's "Divert G and M Keys") and print
    only reports from the GKey/MKeys features; undo the diversion at the end."""
    d = Dev()
    print("features:", {k: (hex(v) if v is not None else None) for k, v in d.discover().items()})
    if not d.idx["gkey"]:
        print("no 0x8010 GKey feature")
        return
    print("divert on:", d.request(d.idx["gkey"], 2, b"\x01")[0])
    watch = {d.idx["gkey"]: "gkey", d.idx["mkeys"]: "mkeys"}
    other, end = 0, time.monotonic() + args.seconds
    print(f"press G1..G5 and M1..M3 now ({args.seconds:.0f} s)")
    while time.monotonic() < end:
        r = d.read(100)
        if r is None:
            continue
        if r[2] in watch:
            print(f"  {watch[r[2]]}: {r[:12].hex(' ')}")
        else:
            other += 1
    print("divert off:", d.request(d.idx["gkey"], 2, b"\x00")[0], f"(other reports ignored: {other})")


def cmd_fps(args):
    d = Dev()
    d.discover()
    pk = d.idx["perkey"]
    valid = frozenset(PHASE1_VALID_ZONES)
    ripple = Ripple(preset=PRESETS[args.preset])
    rotor = ResyncRotor(valid)
    names = [k.name for k in KEYS if k.evdev is not None and len(k.name) == 1]
    prev = None
    committed = abandoned = busy_end = writes_total = 0
    end_kinds, abandon_kinds = {}, {}               # frameEnd non-ok results; abandon causes
    next_press = start = time.monotonic()
    while (now := time.monotonic()) - start < args.seconds:
        while next_press <= now:                       # synthetic fast typing
            ripple.press(random.choice(names), next_press)
            next_press += 1.0 / args.rate
        nxt = ripple.render(now)
        writes = encode(prev, nxt, valid, rotor.next())
        writes_total += len(writes)
        pending, ok, queue = {}, True, list(writes)
        deadline = now + 0.060
        while (queue or pending) and ok:
            while queue and len(pending) < args.window:
                fn, params = queue.pop(0)
                rep = d.report(pk, fn, params)
                d.h.write(rep)
                pending[rep[3]] = rep
                if args.gap_ms:                         # back-to-back writes are dropped
                    time.sleep(args.gap_ms / 1000)
            if time.monotonic() > deadline:
                ok = False
                abandon_kinds["deadline"] = abandon_kinds.get("deadline", 0) + 1
                break
            r = d.read(5)
            if r is None:
                continue
            if r[2] == 0xFF and r[4] in pending:
                ok = False
                code = f"err{r[5]:#04x}"
                abandon_kinds[code] = abandon_kinds.get(code, 0) + 1
            elif r[2] == pk and r[3] in pending:
                pending.pop(r[3])
        if not ok:
            abandoned += 1
            prev = None
            time.sleep(0.05)
            while d.read(5) is not None:                # drain
                pass
            continue
        end = time.monotonic() + 0.150
        while time.monotonic() < end:
            kind, r = d.request(pk, FN_FRAME_END, b"\x00", timeout=0.05)
            if kind != "ok":
                label = f"err{r[5]:#04x}" if kind == "error" else kind
                end_kinds[label] = end_kinds.get(label, 0) + 1
            if kind == "ok":
                committed += 1
                prev = nxt
                break
            busy_end += 1
            time.sleep(0.003)
        else:
            prev = None
    elapsed = time.monotonic() - start
    print(f"{committed} committed frames in {elapsed:.1f}s = {committed / elapsed:.1f} fps "
          f"(window {args.window}, {args.rate}/s presses, {writes_total / max(committed, 1):.1f} writes/frame, "
          f"{abandoned} abandoned, {busy_end} frameEnd retries)")
    print(f"  frameEnd non-ok by kind: {end_kinds}; abandon causes: {abandon_kinds}")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("claim"); s.add_argument("--no-sw-control", action="store_true"); s.set_defaults(f=cmd_claim)
    s = sub.add_parser("release"); s.add_argument("--reselect-profile", action="store_true"); s.set_defaults(f=cmd_release)
    s = sub.add_parser("zone"); s.add_argument("zone"); s.add_argument("color"); s.set_defaults(f=cmd_zone)
    sub.add_parser("echo").set_defaults(f=cmd_echo)
    s = sub.add_parser("gkeys"); s.add_argument("--seconds", type=float, default=20.0); s.set_defaults(f=cmd_gkeys)
    s = sub.add_parser("fps")
    s.add_argument("--seconds", type=float, default=10.0)
    s.add_argument("--rate", type=float, default=12.0)
    s.add_argument("--window", type=int, default=4)
    s.add_argument("--gap-ms", type=float, default=0.0)
    s.add_argument("--preset", default="red", choices=sorted(PRESETS))
    s.set_defaults(f=cmd_fps)
    args = p.parse_args(argv)
    args.f(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
