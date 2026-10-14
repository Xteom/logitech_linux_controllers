"""Daemon state machine (pure): the user's choice + whether the keyboard is claimed -> one state.

Rings also run on the lock screen (user decision 2026-10-14), so there is no LOCKED state.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class State(str, Enum):
    OFF = "off"                     # user chose `wave off`: keyboard released
    DISCONNECTED = "disconnected"   # wave wanted, keyboard absent or claim failed
    ACTIVE = "active"               # claimed: rings live


def decide(off: bool, claimed: bool) -> State:
    """OFF is sticky."""
    if off:
        return State.OFF
    if not claimed:
        return State.DISCONNECTED
    return State.ACTIVE


@dataclass(frozen=True)
class Effects:
    release: bool   # hand the keyboard back to onboard lighting
    clear: bool     # drop every ring now
    rings: bool     # presses start rings in the new state


def effects(prev: State, new: State) -> Effects:
    return Effects(
        release=new is State.OFF and prev is State.ACTIVE,
        clear=new is not State.ACTIVE and prev is not new,
        rings=new is State.ACTIVE,
    )
