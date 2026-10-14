"""Daemon state machine (pure): the user's choice + observed conditions -> one state."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class State(str, Enum):
    OFF = "off"                     # user chose `wave off`: keyboard released
    DISCONNECTED = "disconnected"   # wave wanted, keyboard absent or claim failed
    LOCKED = "locked"               # claimed, screen locked or lock state unknown: base only
    ACTIVE = "active"               # claimed, unlocked: rings live


def decide(off: bool, claimed: bool, locked: bool | None) -> State:
    """OFF is sticky; unknown lock state (None) counts as locked."""
    if off:
        return State.OFF
    if not claimed:
        return State.DISCONNECTED
    if locked is not False:
        return State.LOCKED
    return State.ACTIVE


@dataclass(frozen=True)
class Effects:
    release: bool   # hand the keyboard back to onboard lighting
    clear: bool     # drop every ring now, so the next frame is all base
    rings: bool     # presses start rings in the new state


def effects(prev: State, new: State) -> Effects:
    claimed = (State.LOCKED, State.ACTIVE)
    return Effects(
        release=new is State.OFF and prev in claimed,
        clear=new is not State.ACTIVE and prev is not new,
        rings=new is State.ACTIVE,
    )
