"""Backward-compatible wrapper for g560ctl command."""

import sys
from logitech_lighting.cli import main

if __name__ == "__main__":
    sys.exit(main())
