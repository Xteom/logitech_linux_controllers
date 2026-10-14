import json
import os
import socket
import threading

import pytest

from g815_fakes import FakeConnector, FakeKeys
from logitech_lighting.devices.g815 import daemon as dmod
from logitech_lighting.devices.g815.daemon import (
    Daemon, StateFile, acquire_lock, bind_socket, run_daemon, serve,
)
from logitech_lighting.devices.g815.wave_cli import NOT_RUNNING, send_command


def _daemon(tmp_path):
    return Daemon(FakeConnector(), FakeKeys(), lambda: False, StateFile(tmp_path / "wave.json"))


def _serving(tmp_path):
    """Start serve() on a thread; returns (stop, thread, listener)."""
    listener = bind_socket(tmp_path / "w.sock")
    stop = threading.Event()
    t = threading.Thread(target=serve, args=(_daemon(tmp_path), listener, stop))
    t.start()
    return stop, t, listener


def test_lock_is_exclusive(tmp_path) -> None:
    first = acquire_lock(tmp_path / "w.lock")
    assert first is not None
    assert acquire_lock(tmp_path / "w.lock") is None
    os.close(first)
    again = acquire_lock(tmp_path / "w.lock")
    assert again is not None
    os.close(again)


def test_bind_socket_replaces_stale_file_with_0600(tmp_path) -> None:
    path = tmp_path / "w.sock"
    path.write_text("stale")
    sock = bind_socket(path)
    try:
        assert oct(path.stat().st_mode & 0o777) == "0o600"
    finally:
        sock.close()


def test_socket_round_trip(tmp_path) -> None:
    stop, t, listener = _serving(tmp_path)
    try:
        assert send_command({"cmd": "status"}, tmp_path / "w.sock")["ok"]
        assert send_command({"cmd": "preset", "name": "blue"}, tmp_path / "w.sock")["preset"] == "blue"
    finally:
        stop.set()
        t.join(2)
        listener.close()


def _env(tmp_path, **extra):
    return {"XDG_RUNTIME_DIR": str(tmp_path), "DISPLAY": ":1", "XAUTHORITY": "/x", **extra}


def test_missing_display_exits_0_with_hint(tmp_path, caplog) -> None:
    env = _env(tmp_path)
    del env["XAUTHORITY"]
    assert run_daemon(env=env) == 0
    assert "import-environment DISPLAY XAUTHORITY" in caplog.text


def test_second_daemon_exits_already_running_and_keeps_socket(tmp_path, capsys) -> None:
    held = acquire_lock(tmp_path / dmod.LOCK_NAME)
    (tmp_path / dmod.SOCKET_NAME).write_text("live daemon's socket")
    try:
        assert run_daemon(env=_env(tmp_path), make_keys=FakeKeys) == 1
        assert "already running" in capsys.readouterr().out
        assert (tmp_path / dmod.SOCKET_NAME).read_text() == "live daemon's socket"
    finally:
        os.close(held)


def test_x_connection_loss_releases_and_exits_0(tmp_path) -> None:
    from Xlib.error import ConnectionClosedError

    conn = FakeConnector()
    keys = FakeKeys()
    polls = {"n": 0}

    def poll():
        polls["n"] += 1
        if polls["n"] >= 3:
            raise ConnectionClosedError("display")
        return []

    keys.poll = poll
    code = run_daemon(env=_env(tmp_path), make_keys=lambda: keys, make_connector=lambda: conn,
                      lock_query=lambda: False, state_path=tmp_path / "wave.json")
    assert code == 0 and conn.kb.released == 1
    assert not (tmp_path / dmod.SOCKET_NAME).exists()


def test_cli_without_daemon_says_not_running(tmp_path, monkeypatch, capsys) -> None:
    from logitech_lighting import cli

    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setattr(cli, "UnifiedController", lambda *a, **k: pytest.fail("G560 touched"))
    monkeypatch.setattr(cli, "get_default_device", lambda: pytest.fail("G560 probed"))
    assert cli.main(["wave", "status"]) == 1
    assert NOT_RUNNING in capsys.readouterr().err


def test_garbage_request_gets_error_reply(tmp_path) -> None:
    stop, t, listener = _serving(tmp_path)
    try:
        with socket.socket(socket.AF_UNIX) as s:
            s.connect(str(tmp_path / "w.sock"))
            s.sendall(b"not json\n")
            assert json.loads(s.makefile().readline()) == {"ok": False, "error": "bad request"}
        assert send_command({"cmd": "status"}, tmp_path / "w.sock")["ok"]
    finally:
        stop.set()
        t.join(2)
        listener.close()


def test_sigterm_never_interrupts_keyboard_io_and_releases(tmp_path) -> None:
    # hidapi's read() fails with "read error" when a signal lands in its poll(), which
    # looked like an unplug and skipped the release. The daemon must block SIGTERM/SIGINT
    # in the I/O thread and take them on a dedicated thread instead.
    import signal

    conn = FakeConnector()
    keys = FakeKeys()
    seen = {}

    def poll():
        if "mask" not in seen:
            seen["mask"] = signal.pthread_sigmask(signal.SIG_BLOCK, [])
            os.kill(os.getpid(), signal.SIGTERM)
        return []

    keys.poll = poll
    before = signal.pthread_sigmask(signal.SIG_BLOCK, [])
    code = run_daemon(env=_env(tmp_path), make_keys=lambda: keys, make_connector=lambda: conn,
                      lock_query=lambda: False, state_path=tmp_path / "wave.json")
    assert code == 0 and conn.kb.released == 1
    assert {signal.SIGTERM, signal.SIGINT} <= seen["mask"]
    assert signal.pthread_sigmask(signal.SIG_BLOCK, []) == before
