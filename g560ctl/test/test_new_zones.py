from logitech_lighting import get_device_config, resolve_zones
from logitech_lighting.core.exceptions import ValidationError


def test_resolve_all_g560() -> None:
    config = get_device_config("g560")
    zones = resolve_zones("all", config)
    assert "left_primary" in zones
    assert "right_primary" in zones
    assert "left_secondary" in zones
    assert "right_secondary" in zones


def test_resolve_comma_list() -> None:
    config = get_device_config("g560")
    zones = resolve_zones("left_primary,right_secondary", config)
    assert zones == frozenset({"left_primary", "right_secondary"})


def test_resolve_aliases() -> None:
    config = get_device_config("g560")
    zones = resolve_zones("left,primary", config)
    assert zones == frozenset({
        "left_secondary",
        "left_primary",
        "right_primary",
    })


def test_unknown_zone_raises() -> None:
    config = get_device_config("g560")
    try:
        resolve_zones("banana", config)
        assert False, "Expected ValidationError"
    except ValidationError:
        pass
