"""The wave daemon: frame loop, control socket, state file, lock-screen watch, reconnect."""
from __future__ import annotations

import collections
import fcntl
import json
import logging
import os
import selectors
import signal
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

from logitech_lighting.devices.g815.frame import ResyncRotor
from logitech_lighting.devices.g815.hidpp import DeviceGone
from logitech_lighting.devices.g815.keyboard import ClaimError, Connector, Keyboard
from logitech_lighting.devices.g815.layout import KEYS
from logitech_lighting.devices.g815.presets import BASE, PRESETS, Color
from logitech_lighting.devices.g815.ripple import Ripple
from logitech_lighting.devices.g815.state import State, decide, effects

log = logging.getLogger("g815-wave")

DEFAULT_PRESET = "red"
FRAME_INTERVAL = 1 / 60
CONTROL_CHECK = 10.0
RECONNECT_POLL = 2.0
CLAIM_BACKOFF = (2.0, 4.0, 8.0, 16.0, 30.0)
LOCK_POLL = 1.0
GDBUS = "/usr/bin/gdbus"
SOCKET_NAME = "g815-wave.sock"
LOCK_NAME = "g815-wave.lock"
STOP_SIGNALS = {signal.SIGTERM, signal.SIGINT}
ENV_HINT = "systemctl --user import-environment DISPLAY XAUTHORITY"


def runtime_dir(env: dict[str, str] | os._Environ = os.environ) -> Path:
    return Path(env.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}")


def socket_path(env: dict[str, str] | os._Environ = os.environ) -> Path:
    return runtime_dir(env) / SOCKET_NAME


def default_state_path() -> Path:
    return Path.home() / ".config" / "logitech-lighting" / "wave.json"


def base_frame() -> dict[int, Color]:
    return {k.zone: BASE for k in KEYS}


class StateFile:
    """The user's choice only: {"preset": "red"|"blue", "off": bool}."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> tuple[str, bool]:
        try:
            data = json.loads(self.path.read_text())
            preset, off = data["preset"], data["off"]
            if preset not in PRESETS or not isinstance(off, bool):
                raise ValueError(f"bad values {data!r}")
            return preset, off
        except FileNotFoundError:
            return DEFAULT_PRESET, False
        except (OSError, ValueError, KeyError, TypeError) as exc:
            log.warning("corrupt state file %s (%s); using defaults", self.path, exc)
            try:
                self.save(DEFAULT_PRESET, False)
            except OSError as save_exc:
                log.warning("cannot rewrite %s: %s", self.path, save_exc)
            return DEFAULT_PRESET, False

    def save(self, preset: str, off: bool) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"preset": preset, "off": off}) + "\n")
        tmp.replace(self.path)


def query_lock(run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> bool | None:
    """GNOME ScreenSaver GetActive: True/False, or None when unknown (treated as locked)."""
    try:
        out = run([GDBUS, "call", "--session", "--dest", "org.gnome.ScreenSaver",
                   "--object-path", "/org/gnome/ScreenSaver",
                   "--method", "org.gnome.ScreenSaver.GetActive"],
                  capture_output=True, text=True, timeout=0.5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    return {"(true,)": True, "(false,)": False}.get(out.stdout.strip())


class LockWatcher(threading.Thread):
    """Polls the lock state off the frame loop, so a slow gdbus never stalls frames."""

    def __init__(self, query: Callable[[], bool | None] = query_lock, interval: float = LOCK_POLL) -> None:
        super().__init__(name="lock-watch", daemon=True)
        self._query = query
        self._interval = interval
        self._stop = threading.Event()
        self.locked: bool | None = None

    def run(self) -> None:
        while not self._stop.is_set():
            self.locked = self._query()
            self._stop.wait(self._interval)

    def stop(self) -> None:
        self._stop.set()


class Daemon:
    def __init__(
        self,
        connector: Connector,
        keys,                                   # .poll() -> list[str] of key names
        lock_state: Callable[[], bool | None],
        state_file: StateFile,
    ) -> None:
        self.connector = connector
        self.keys = keys
        self.lock_state = lock_state
        self.state_file = state_file
        self.preset, self.off = state_file.load()
        self.ripple = Ripple(preset=PRESETS[self.preset])
        self.ripple.pause()
        self.kb: Keyboard | None = None
        self.rotor: ResyncRotor | None = None
        self.state = State.OFF if self.off else State.DISCONNECTED
        self.locked: bool | None = None
        self._lock_warned = False
        self._next_connect = 0.0
        self._backoff = 0
        self._last_check = 0.0
        self._commits: collections.deque[float] = collections.deque(maxlen=64)

    # -- control socket commands ------------------------------------------

    def handle(self, req: dict, now: float) -> dict:
        cmd = req.get("cmd")
        if cmd == "preset":
            name = req.get("name")
            if name not in PRESETS:
                return {"ok": False, "error": f"unknown preset {name!r}; choose one of: {', '.join(sorted(PRESETS))}"}
            if self.off:
                self._next_connect, self._backoff = now, 0     # leaving OFF: connect at once
            self.preset, self.off = name, False
            self.ripple.set_preset(PRESETS[name])
            self._save()
            self._apply(now)
            return {"ok": True, **self.status()}
        if cmd == "off":
            self.off = True
            self._save()
            self._apply(now)
            return {"ok": True, **self.status()}
        if cmd == "status":
            return {"ok": True, **self.status()}
        return {"ok": False, "error": "unknown command; valid: preset, off, status"}

    def _save(self) -> None:
        try:
            self.state_file.save(self.preset, self.off)
        except OSError as exc:
            log.warning("cannot save %s: %s", self.state_file.path, exc)

    def status(self) -> dict:
        return {
            "preset": self.preset,
            "state": self.state.value,
            "connected": self.kb is not None,
            "lock": "unknown" if self.locked is None else ("locked" if self.locked else "unlocked"),
            "fps": round(self.fps(), 1),
        }

    def fps(self) -> float:
        """Committed frames per second over the most recent burst of frames."""
        times = list(self._commits)
        run = times[-1:]
        for a, b in zip(reversed(times[:-1]), reversed(times[1:])):
            if b - a > 0.1:
                break
            run.insert(0, a)
        if len(run) < 2:
            return 0.0
        return (len(run) - 1) / (run[-1] - run[0])

    # -- one loop iteration --------------------------------------------------

    def tick(self, now: float) -> None:
        presses = self.keys.poll()                  # X connection loss propagates to run_daemon
        self.locked = self.lock_state()
        if self.locked is None and not self._lock_warned:
            log.warning("lock state unknown (GNOME ScreenSaver not answering); rings paused")
        self._lock_warned = self.locked is None
        self._apply(now)
        if self.kb is not None:
            try:
                presses += self.kb.poll_keys()      # G-keys arrive as HID++ notifications
            except DeviceGone as exc:
                self._lost(exc, now)
        if self.state is State.ACTIVE:
            for name in presses:
                self.ripple.press(name, now)
        if self.state in (State.LOCKED, State.ACTIVE):
            self._frame(now)
        elif self.state is State.DISCONNECTED and now >= self._next_connect:
            self._connect(now)
            self._apply(now)
            if self.state in (State.LOCKED, State.ACTIVE):
                self._frame(now)

    def _apply(self, now: float) -> None:
        new = decide(self.off, self.kb is not None, self.locked)
        if new is self.state:
            return
        fx = effects(self.state, new)
        if fx.clear:
            self.ripple.clear()
        if fx.release and self.kb is not None:
            self.kb.release()
            self.connector.drop()
            self.kb = None
        if fx.rings:
            self.ripple.resume()
        else:
            self.ripple.pause()
        log.info("state %s -> %s", self.state.value, new.value)
        self.state = new

    def _connect(self, now: float) -> None:
        try:
            self.kb = self.connector.connect(base_frame())
        except DeviceGone as exc:
            log.debug("keyboard not available: %s", exc)
            self._next_connect = now + RECONNECT_POLL
            return
        except ClaimError as exc:
            delay = CLAIM_BACKOFF[min(self._backoff, len(CLAIM_BACKOFF) - 1)]
            self._backoff += 1
            log.warning("claim failed (%s); retrying in %.0f s", exc, delay)
            self._next_connect = now + delay
            return
        self._backoff = 0
        self._last_check = now
        self.rotor = ResyncRotor(self.kb.valid)
        log.info("keyboard claimed (%d zones)", len(self.kb.valid))

    def _lost(self, exc: DeviceGone, now: float) -> None:
        log.warning("keyboard lost: %s", exc)
        self.connector.drop(exc)
        self.kb = None
        self._next_connect = now + RECONNECT_POLL
        self._apply(now)

    def _reclaim(self, now: float) -> None:
        log.warning("re-claiming the keyboard")
        try:
            self.kb = self.connector.reclaim(base_frame())
            self.rotor = ResyncRotor(self.kb.valid)
            self._last_check = now
        except DeviceGone as exc:
            self._lost(exc, now)
        except ClaimError as exc:
            log.warning("re-claim failed: %s", exc)
            self.kb = None
            self._next_connect = now + CLAIM_BACKOFF[0]
            self._apply(now)

    def _frame(self, now: float) -> None:
        assert self.kb is not None and self.rotor is not None
        try:
            if now - self._last_check >= CONTROL_CHECK:
                self._last_check = now
                if not self.kb.check_control():
                    self._reclaim(now)
                    return
            before = self.kb.committed
            self.kb.send_frame(self.ripple.render(now), self.rotor.next())
            if self.kb.committed > before:
                self._commits.append(now)
            if self.kb.needs_reclaim:
                self._reclaim(now)
        except DeviceGone as exc:
            self._lost(exc, now)

    def shutdown(self) -> None:
        if self.kb is not None:
            self.kb.release()
            self.connector.drop()
            self.kb = None


# -- service plumbing ---------------------------------------------------------

def acquire_lock(path: Path) -> int | None:
    """Exclusive flock held for the daemon's lifetime; None if another daemon holds it."""
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None
    return fd


def bind_socket(path: Path) -> socket.socket:
    """Only the lock holder calls this, so removing a leftover socket file is safe."""
    path.unlink(missing_ok=True)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    old = os.umask(0o177)
    try:
        sock.bind(str(path))
    finally:
        os.umask(old)
    os.chmod(path, 0o600)
    sock.listen(4)
    sock.setblocking(False)
    return sock


def _serve_client(listener: socket.socket, daemon: Daemon, now: float) -> None:
    try:
        conn, _ = listener.accept()
    except BlockingIOError:
        return
    with conn:
        conn.settimeout(1.0)
        try:
            data = b""
            while not data.endswith(b"\n") and len(data) < 4096:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
            try:
                req = json.loads(data)
                reply = daemon.handle(req, now) if isinstance(req, dict) else {"ok": False, "error": "bad request"}
            except ValueError:
                reply = {"ok": False, "error": "bad request"}
            conn.sendall(json.dumps(reply).encode() + b"\n")
        except OSError as exc:
            log.debug("control client error: %s", exc)


def serve(daemon: Daemon, listener: socket.socket, stop: threading.Event,
          clock: Callable[[], float] = time.monotonic, wake_fd: int | None = None) -> None:
    sel = selectors.DefaultSelector()
    sel.register(listener, selectors.EVENT_READ)
    if wake_fd is not None:
        sel.register(wake_fd, selectors.EVENT_READ)
    next_tick = clock()
    try:
        while not stop.is_set():
            for key, _ in sel.select(max(0.0, next_tick - clock())):
                if key.fileobj is listener:
                    _serve_client(listener, daemon, clock())
                else:
                    next_tick = clock()          # X input arrived: handle presses now
            now = clock()
            if now >= next_tick:
                daemon.tick(now)
                next_tick = now + FRAME_INTERVAL
    finally:
        sel.close()


def run_daemon(
    env: dict[str, str] | os._Environ = os.environ,
    make_keys: Callable[[], object] | None = None,
    make_connector: Callable[[], Connector] = Connector,
    lock_query: Callable[[], bool | None] = query_lock,
    state_path: Path | None = None,
    stop: threading.Event | None = None,
) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if not env.get("DISPLAY") or not env.get("XAUTHORITY"):
        log.error("DISPLAY/XAUTHORITY missing from the service environment; run: %s", ENV_HINT)
        return 0
    rt = runtime_dir(env)
    lock_fd = acquire_lock(rt / LOCK_NAME)
    if lock_fd is None:
        print("g815 wave daemon already running")
        return 1
    stop = stop or threading.Event()
    watcher = LockWatcher(lock_query)
    listener = None
    daemon = None
    old_mask: set[int] | None = None
    waiter: threading.Thread | None = None
    try:
        from Xlib.error import ConnectionClosedError

        from logitech_lighting.devices.g815.keys import XInputTooOld, XKeySource

        try:
            keys = (make_keys or XKeySource)()
        except XInputTooOld as exc:
            log.error("%s", exc)
            return 1
        listener = bind_socket(rt / SOCKET_NAME)
        daemon = Daemon(make_connector(), keys, lambda: watcher.locked,
                        StateFile(state_path or default_state_path()))
        if threading.current_thread() is threading.main_thread():
            # A signal landing in hidapi's poll() makes read() fail with "read error", which
            # looks like an unplug and would skip the release. So SIGTERM/SIGINT are blocked
            # here (threads started below inherit the mask) and taken by sigwait instead.
            old_mask = signal.pthread_sigmask(signal.SIG_BLOCK, STOP_SIGNALS)
            waiter = threading.Thread(target=lambda: (signal.sigwait(STOP_SIGNALS), stop.set()),
                                      name="signals", daemon=True)
            waiter.start()
        watcher.locked = lock_query()
        watcher.start()
        log.info("wave daemon started (preset %s, %s)", daemon.preset, "off" if daemon.off else "on")
        try:
            serve(daemon, listener, stop, wake_fd=keys.fileno() if hasattr(keys, "fileno") else None)
        except ConnectionClosedError:
            log.info("X session closed; exiting")
        return 0
    finally:
        watcher.stop()
        if daemon is not None:
            daemon.shutdown()
        if listener is not None:
            listener.close()
            (rt / SOCKET_NAME).unlink(missing_ok=True)
        os.close(lock_fd)
        if waiter is not None:
            if waiter.is_alive():
                signal.pthread_kill(waiter.ident, signal.SIGTERM)   # wake sigwait so it exits
            waiter.join(1)
        if old_mask is not None:
            signal.pthread_sigmask(signal.SIG_SETMASK, old_mask)
