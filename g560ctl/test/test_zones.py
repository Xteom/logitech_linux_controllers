from g560ctl.models import ValidationError, Zone
from g560ctl.zones import resolve_zones


def test_resolve_all() -> None:
    zones = resolve_zones("all")
    assert Zone.LEFT_PRIMARY in zones
    assert Zone.RIGHT_PRIMARY in zones
    assert Zone.LEFT_SECONDARY in zones
    assert Zone.RIGHT_SECONDARY in zones


def test_resolve_comma_list() -> None:
    zones = resolve_zones("left_primary,right_secondary")
    assert zones == frozenset({Zone.LEFT_PRIMARY, Zone.RIGHT_SECONDARY})


def test_resolve_aliases() -> None:
    zones = resolve_zones(["left", "primary"])
    assert zones == frozenset({
        Zone.LEFT_SECONDARY,
        Zone.LEFT_PRIMARY,
        Zone.RIGHT_PRIMARY,
    })


def test_unknown_zone_raises() -> None:
    try:
        resolve_zones("banana")
        assert False, "Expected ValidationError"
    except ValidationError:
        pass