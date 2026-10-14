"""`logitech-lighting wave red|blue|off|status|daemon`: a thin client of the wave daemon."""
from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

NOT_RUNNING = "wave daemon not running — start it with: systemctl --user start g815-wave"


class DaemonNotRunning(Exception):
    pass


def send_command(req: dict, path: Path | None = None, timeout: float = 3.0) -> dict:
    from logitech_lighting.devices.g815.daemon import socket_path

    path = path or socket_path()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        try:
            sock.connect(str(path))
        except (FileNotFoundError, ConnectionRefusedError) as exc:
            raise DaemonNotRunning(str(exc)) from exc
        sock.sendall(json.dumps(req).encode() + b"\n")
        data = b""
        while not data.endswith(b"\n"):
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
    return json.loads(data)


def format_status(reply: dict) -> str:
    lines = [
        f"preset:   {reply['preset']}",
        f"state:    {reply['state']}",
        f"keyboard: {'connected' if reply['connected'] else 'not connected'}",
        f"fps:      {reply['fps']} (last burst of frames)",
    ]
    if reply.get("lock") == "unknown":
        lines.append("lock state unknown — rings stay paused until GNOME ScreenSaver answers")
    return "\n".join(lines)


def run_wave(action: str, path: Path | None = None) -> int:
    if action == "daemon":
        from logitech_lighting.devices.g815.daemon import run_daemon

        return run_daemon()
    if action == "status":
        req = {"cmd": "status"}
    elif action == "off":
        req = {"cmd": "off"}
    else:
        req = {"cmd": "preset", "name": action}
    try:
        reply = send_command(req, path)
    except DaemonNotRunning:
        print(NOT_RUNNING, file=sys.stderr)
        return 1
    except (socket.timeout, ValueError) as exc:
        print(f"Error: wave daemon did not answer ({exc})", file=sys.stderr)
        return 1
    if not reply.get("ok"):
        print(f"Error: {reply.get('error')}", file=sys.stderr)
        return 1
    print(format_status(reply))
    return 0
