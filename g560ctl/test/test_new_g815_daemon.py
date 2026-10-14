import json
import subprocess

import pytest

from g815_fakes import FakeConnector, FakeKeys
from logitech_lighting.devices.g815.daemon import (
    CLAIM_BACKOFF, CONTROL_CHECK, RECONNECT_POLL, Daemon, StateFile, query_lock,
)
from logitech_lighting.devices.g815.hidpp import DeviceGone
from logitech_lighting.devices.g815.keyboard import ClaimError
from logitech_lighting.devices.g815.layout import BY_NAME
from logitech_lighting.devices.g815.presets import BASE, PRESETS
from logitech_lighting.devices.g815.state import State


def _daemon(tmp_path, locked=False, state=None):
    path = tmp_path / "wave.json"
    if state is not None:
        path.write_text(json.dumps(state))
    lock = {"value": locked}
    conn, keys = FakeConnector(), FakeKeys()
    d = Daemon(conn, keys, lambda: lock["value"], StateFile(path))
    return d, conn, keys, lock


def test_state_file_round_trip_and_default(tmp_path) -> None:
    sf = StateFile(tmp_path / "sub" / "wave.json")
    assert sf.load() == ("red", False)
    sf.save("blue", True)
    assert sf.load() == ("blue", True)


@pytest.mark.parametrize("content", ["{not json", '{"preset": "green", "off": false}', '{"preset": "red"}', "[]"])
def test_corrupt_state_file_falls_back_and_is_rewritten(tmp_path, content) -> None:
    path = tmp_path / "wave.json"
    path.write_text(content)
    assert StateFile(path).load() == ("red", False)
    assert json.loads(path.read_text()) == {"preset": "red", "off": False}


def _loginctl(display: str = "2\n", locked: str = "no\n", code: int = 0):
    """Fake subprocess.run for `loginctl show-user` / `show-session`; records the argv."""
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        if argv[1] == "show-user":
            return subprocess.CompletedProcess(argv, 0, stdout=display, stderr="")
        return subprocess.CompletedProcess(argv, code, stdout=locked, stderr="")

    return run, calls


@pytest.mark.parametrize("locked,code,expected", [
    ("yes\n", 0, True), ("no\n", 0, False), ("garbage", 0, None), ("", 1, None),
])
def test_query_lock_reads_logind_locked_hint(locked, code, expected) -> None:
    # GNOME's ScreenSaver.GetActive proved unreliable on this Pop!_OS session (true for 8 s
    # of one lock, never during the next); logind's LockedHint tracked lock/unlock exactly.
    run, calls = _loginctl(locked=locked, code=code)
    assert query_lock(run, uid=1000) is expected
    assert calls[0][1:3] == ["show-user", "1000"] and calls[1][1:3] == ["show-session", "2"]
    assert "LockedHint" in calls[1]


def test_query_lock_without_graphical_session_is_unknown() -> None:
    run, _ = _loginctl(display="\n")
    assert query_lock(run, uid=1000) is None


@pytest.mark.parametrize("exc", [FileNotFoundError("loginctl"), subprocess.TimeoutExpired("loginctl", 0.5)])
def test_query_lock_failure_is_unknown(exc) -> None:
    def run(*a, **k):
        raise exc
    assert query_lock(run, uid=1000) is None


def test_connects_then_active_when_unlocked(tmp_path) -> None:
    d, conn, _, _ = _daemon(tmp_path)
    d.tick(10.0)
    assert d.state is State.ACTIVE and conn.connects == 1


def test_unknown_lock_state_means_locked(tmp_path) -> None:
    d, _, _, _ = _daemon(tmp_path, locked=None)
    d.tick(10.0)
    assert d.state is State.LOCKED and d.status()["lock"] == "unknown"


def test_presses_ripple_only_when_active(tmp_path) -> None:
    d, conn, keys, lock = _daemon(tmp_path, locked=True)
    d.tick(10.0)
    keys.pending = ["g"]
    d.tick(10.02)
    assert set(conn.kb.frames[-1].values()) == {BASE}
    lock["value"] = False
    keys.pending = ["g"]
    d.tick(10.04)
    d.tick(10.06)
    assert conn.kb.frames[-1][BY_NAME["g"].zone] == PRESETS["red"].stops[0]


def test_locking_clears_rings_and_commits_base_at_once(tmp_path) -> None:
    d, conn, keys, lock = _daemon(tmp_path)
    d.tick(10.0)
    keys.pending = ["g"]
    d.tick(10.02)
    lock["value"] = True
    d.tick(10.04)
    assert d.state is State.LOCKED and set(conn.kb.frames[-1].values()) == {BASE}


def test_off_releases_and_is_sticky(tmp_path) -> None:
    d, conn, _, _ = _daemon(tmp_path)
    d.tick(10.0)
    reply = d.handle({"cmd": "off"}, 10.1)
    assert reply["ok"] and reply["state"] == "off" and conn.kb.released == 1
    for i in range(50):
        d.tick(11.0 + i)
    assert conn.connects == 1
    assert json.loads((tmp_path / "wave.json").read_text()) == {"preset": "red", "off": True}


def test_off_state_file_means_no_claim_at_start(tmp_path) -> None:
    d, conn, _, _ = _daemon(tmp_path, state={"preset": "blue", "off": True})
    d.tick(10.0)
    assert d.state is State.OFF and conn.connects == 0


def test_preset_command_leaves_off_and_switches_colors(tmp_path) -> None:
    d, conn, keys, _ = _daemon(tmp_path, state={"preset": "red", "off": True})
    reply = d.handle({"cmd": "preset", "name": "blue"}, 10.0)
    assert reply["ok"] and reply["preset"] == "blue"
    d.tick(10.0)
    keys.pending = ["g"]
    d.tick(10.02)
    d.tick(10.04)
    assert d.state is State.ACTIVE
    assert conn.kb.frames[-1][BY_NAME["g"].zone] == PRESETS["blue"].stops[0]


def test_bad_commands_list_valid_choices(tmp_path) -> None:
    d, _, _, _ = _daemon(tmp_path)
    bad = d.handle({"cmd": "preset", "name": "green"}, 1.0)
    assert not bad["ok"] and "blue, red" in bad["error"]
    assert not d.handle({"cmd": "dance"}, 1.0)["ok"]


def test_absent_keyboard_polls_every_2s(tmp_path) -> None:
    d, conn, _, _ = _daemon(tmp_path)
    conn.error = DeviceGone("keyboard not found")
    d.tick(10.0)
    d.tick(10.0 + RECONNECT_POLL / 2)
    assert conn.connects == 1
    d.tick(10.0 + RECONNECT_POLL)
    assert conn.connects == 2 and d.state is State.DISCONNECTED


def test_claim_failures_back_off(tmp_path) -> None:
    d, conn, _, _ = _daemon(tmp_path)
    conn.error = ClaimError("nope")
    d.tick(10.0)
    d.tick(10.0 + CLAIM_BACKOFF[0])
    d.tick(10.0 + CLAIM_BACKOFF[0] + CLAIM_BACKOFF[1] - 0.1)
    assert conn.connects == 2


def test_keyboard_loss_goes_disconnected_then_reconnects(tmp_path) -> None:
    d, conn, _, _ = _daemon(tmp_path)
    d.tick(10.0)
    conn.kb.fail = DeviceGone("write failed", io_error=True)
    d.tick(10.02)
    assert d.state is State.DISCONNECTED and conn.drops[-1].io_error
    conn.kb.fail = None
    d.tick(10.02 + RECONNECT_POLL)
    assert d.state is State.ACTIVE and conn.connects == 2


def test_takeover_and_abandoned_frames_reclaim(tmp_path) -> None:
    d, conn, _, _ = _daemon(tmp_path)
    d.tick(10.0)
    conn.kb.control_ok = False
    d.tick(10.0 + CONTROL_CHECK)
    assert conn.reclaims == 1
    conn.kb.control_ok = True
    conn.kb.needs_reclaim = True
    d.tick(10.0 + CONTROL_CHECK + 0.02)
    assert conn.reclaims == 2


def test_fps_reports_last_burst(tmp_path) -> None:
    d, _, _, _ = _daemon(tmp_path)
    for i in range(31):
        d._commits.append(100.0 + i / 30)
    for i in range(5):
        d._commits.append(200.0 + i)                          # sparse, not a burst
    assert d.fps() == 0.0
    d._commits.clear()
    for i in range(31):
        d._commits.append(300.0 + i / 30)
    assert d.fps() == pytest.approx(30.0)


def test_leaving_off_connects_immediately(tmp_path) -> None:
    d, conn, _, _ = _daemon(tmp_path)
    conn.error = ClaimError("busy keyboard")
    for i in range(5):                                        # next retry 30 s away
        d.tick(10.0 + sum(CLAIM_BACKOFF[:i]))
    d.handle({"cmd": "off"}, 40.5)
    conn.error = None
    d.handle({"cmd": "preset", "name": "red"}, 41.0)
    d.tick(41.0)
    assert d.state is State.ACTIVE


def test_unwritable_state_file_keeps_running(tmp_path) -> None:
    d, conn, _, _ = _daemon(tmp_path)
    d.state_file.path = tmp_path / "missing-dir-file" / "x" / "wave.json"
    (tmp_path / "missing-dir-file").write_text("a file, so mkdir under it fails")
    d.tick(10.0)
    assert d.handle({"cmd": "off"}, 10.1)["ok"] and conn.kb.released == 1


def test_press_on_lock_tick_does_not_ring(tmp_path) -> None:
    d, conn, keys, lock = _daemon(tmp_path)
    d.tick(10.0)
    lock["value"] = True
    keys.pending = ["g"]
    d.tick(10.02)
    assert set(conn.kb.frames[-1].values()) == {BASE}


def test_failed_reclaim_goes_disconnected_and_retries(tmp_path) -> None:
    d, conn, _, _ = _daemon(tmp_path)
    d.tick(10.0)
    conn.kb.control_ok = False
    conn.error = ClaimError("still taken")
    d.tick(10.0 + CONTROL_CHECK)
    assert d.state is State.DISCONNECTED
    conn.error = None
    conn.kb.control_ok = True
    d.tick(10.0 + CONTROL_CHECK + CLAIM_BACKOFF[0])
    assert d.state is State.ACTIVE


def test_gkey_presses_ripple_when_active(tmp_path) -> None:
    d, conn, _, lock = _daemon(tmp_path)
    d.tick(10.0)
    conn.kb.gkeys = ["g3"]
    d.tick(10.02)
    d.tick(10.04)
    assert conn.kb.frames[-1][BY_NAME["g3"].zone] == PRESETS["red"].stops[0]
    lock["value"] = True
    d.tick(10.06)
    conn.kb.gkeys = ["g1"]
    d.tick(10.08)
    assert set(conn.kb.frames[-1].values()) == {BASE}
