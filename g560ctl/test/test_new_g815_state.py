import pytest

from logitech_lighting.devices.g815.state import State, decide, effects


@pytest.mark.parametrize("claimed", [True, False])
def test_off_is_sticky(claimed: bool) -> None:
    assert decide(off=True, claimed=claimed) is State.OFF


def test_unclaimed_is_disconnected() -> None:
    assert decide(off=False, claimed=False) is State.DISCONNECTED


def test_claimed_is_active() -> None:
    # Rings also run on the lock screen (user decision 2026-10-14): there is no LOCKED state.
    assert decide(off=False, claimed=True) is State.ACTIVE
    assert {s.value for s in State} == {"off", "disconnected", "active"}


def test_entering_off_releases_only_when_claimed() -> None:
    assert effects(State.ACTIVE, State.OFF).release
    assert not effects(State.DISCONNECTED, State.OFF).release


def test_disconnected_to_active_starts_rings() -> None:
    fx = effects(State.DISCONNECTED, State.ACTIVE)
    assert fx.rings and not fx.clear and not fx.release


def test_leaving_active_clears_rings() -> None:
    for new in (State.DISCONNECTED, State.OFF):
        fx = effects(State.ACTIVE, new)
        assert fx.clear and not fx.rings
