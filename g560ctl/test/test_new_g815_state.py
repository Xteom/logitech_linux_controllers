import pytest

from logitech_lighting.devices.g815.state import State, decide, effects


@pytest.mark.parametrize("claimed", [True, False])
@pytest.mark.parametrize("locked", [True, False, None])
def test_off_is_sticky(claimed: bool, locked: bool | None) -> None:
    assert decide(off=True, claimed=claimed, locked=locked) is State.OFF


def test_unclaimed_is_disconnected() -> None:
    assert decide(off=False, claimed=False, locked=False) is State.DISCONNECTED


def test_lock_states() -> None:
    assert decide(off=False, claimed=True, locked=True) is State.LOCKED
    assert decide(off=False, claimed=True, locked=None) is State.LOCKED   # unknown -> locked
    assert decide(off=False, claimed=True, locked=False) is State.ACTIVE


def test_entering_locked_clears_rings() -> None:
    fx = effects(State.ACTIVE, State.LOCKED)
    assert fx.clear and not fx.rings and not fx.release


def test_entering_off_releases_only_when_claimed() -> None:
    assert effects(State.ACTIVE, State.OFF).release
    assert effects(State.LOCKED, State.OFF).release
    assert not effects(State.DISCONNECTED, State.OFF).release


def test_disconnected_to_claimed() -> None:
    assert effects(State.DISCONNECTED, State.ACTIVE).rings
    assert not effects(State.DISCONNECTED, State.LOCKED).rings
    assert effects(State.DISCONNECTED, State.LOCKED).clear


def test_losing_the_keyboard_clears_rings() -> None:
    fx = effects(State.ACTIVE, State.DISCONNECTED)
    assert fx.clear and not fx.release
