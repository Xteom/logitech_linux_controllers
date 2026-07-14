"""TUI support for logitech_lighting (stub for now)."""

from __future__ import annotations

import sys


def run_tui(controller, device_config) -> int:
    """Run the TUI (not yet implemented for new architecture)."""
    print("TUI is not yet implemented in the refactored version.", file=sys.stderr)
    print("Please use the CLI commands for now:", file=sys.stderr)
    print("  logitech-lighting list-zones", file=sys.stderr)
    print("  logitech-lighting solid ff6600", file=sys.stderr)
    print("  logitech-lighting breathe 00aaff --rate 3000", file=sys.stderr)
    return 1
