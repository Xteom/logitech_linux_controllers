# g560ctl/test/test_new_g815_frame.py
from logitech_lighting.devices.g815.frame import (
    FN_SET_INDIVIDUAL, FN_SET_RANGE, FN_SET_SINGLE, ResyncRotor, encode,
)

R, B, W = (255, 0, 0), (0, 0, 255), (255, 255, 255)
VALID = frozenset(range(1, 40)) | {0x68, 0xB4, 0xD2}


def _zones_painted(writes):
    painted = {}
    for fn, p in writes:
        assert len(p) <= 16
        if fn == FN_SET_RANGE:
            for i in range(0, len(p), 5):
                s, e, r, g, b = p[i:i + 5]
                for z in range(s, e + 1):
                    painted.setdefault(z, []).append((r, g, b))
        elif fn == FN_SET_SINGLE:
            color = tuple(p[:3])
            for z in sorted(set(p[3:])):
                painted.setdefault(z, []).append(color)
        elif fn == FN_SET_INDIVIDUAL:
            for i in range(0, len(p), 4):
                z, r, g, b = p[i:i + 4]
                painted.setdefault(z, []).append((r, g, b))
    return painted


def test_no_change_no_packets() -> None:
    frame = {1: R, 2: R}
    assert encode(frame, dict(frame), VALID) == []


def test_run_of_three_uses_range() -> None:
    writes = encode({1: B, 2: B, 3: B}, {1: R, 2: R, 3: R}, VALID)
    assert writes == [(FN_SET_RANGE, bytes([1, 3, 255, 0, 0]))]


def test_scattered_shared_color_uses_single_value_padded_with_own_zone() -> None:
    nxt = {1: R, 5: R, 9: R, 13: R}
    writes = encode({z: B for z in nxt}, nxt, VALID)
    assert writes == [(FN_SET_SINGLE, bytes([255, 0, 0, 1, 5, 9, 13] + [1] * 9))]


def test_singletons_use_individual_four_per_packet() -> None:
    prev = {1: B, 3: B, 5: B, 7: B, 9: B}
    nxt = {1: (1, 1, 1), 3: (2, 2, 2), 5: (3, 3, 3), 7: (4, 4, 4), 9: (5, 5, 5)}
    writes = encode(prev, nxt, VALID)
    assert [fn for fn, _ in writes] == [FN_SET_INDIVIDUAL, FN_SET_INDIVIDUAL]
    assert writes[0][1] == bytes([1, 1, 1, 1, 3, 2, 2, 2, 5, 3, 3, 3, 7, 4, 4, 4])
    assert writes[1][1] == bytes([9, 5, 5, 5])


def test_invalid_zones_never_emitted() -> None:
    nxt = {1: R, 2: R, 0x50: R, 0xFE: R}
    painted = _zones_painted(encode(None, nxt, VALID))
    assert set(painted) == {1, 2}


def test_range_never_spans_invalid_zone() -> None:
    valid = frozenset({1, 2, 3, 5, 6, 7})                 # 4 is missing
    nxt = {z: R for z in range(1, 8)}
    for fn, p in encode(None, nxt, valid):
        if fn == FN_SET_RANGE:
            for i in range(0, len(p), 5):
                assert not (p[i] <= 4 <= p[i + 1])


def test_full_repaint_covers_every_valid_zone_once() -> None:
    nxt = {z: W for z in VALID}
    painted = _zones_painted(encode(None, nxt, VALID))
    assert set(painted) == set(VALID)
    assert all(colors == [W] for colors in painted.values())


def test_uncertain_cache_repaints_everything() -> None:
    nxt = {z: R for z in range(1, 6)}
    assert set(_zones_painted(encode(None, nxt, VALID))) == set(range(1, 6))


def test_resync_zones_are_resent_unchanged() -> None:
    frame = {1: R, 2: B, 3: R}
    painted = _zones_painted(encode(frame, dict(frame), VALID, resync=(2,)))
    assert painted == {2: [B]}


def test_resync_rotor_cycles_all_zones() -> None:
    rotor = ResyncRotor(frozenset({1, 2, 3, 4, 5}), per_frame=2)
    seen = [z for _ in range(3) for z in rotor.next()]
    assert seen == [1, 2, 3, 4, 5, 1]
