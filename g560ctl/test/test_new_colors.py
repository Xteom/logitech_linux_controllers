from logitech_lighting.core.colors import parse_color
from logitech_lighting.core.exceptions import ValidationError
from logitech_lighting import get_device_config


def test_parse_color_accepts_hash() -> None:
    color = parse_color("#ff6600")
    assert color.hex_value == "ff6600"
    assert color.rgb == (255, 102, 0)


def test_parse_color_rejects_invalid() -> None:
    try:
        parse_color("zzzzzz")
        assert False, "Expected ValidationError"
    except ValidationError:
        pass


def test_g560_clamp_rate() -> None:
    """Test G560-specific rate clamping."""
    config = get_device_config("g560")
    assert config.clamp_rate(50) == 100
    assert config.clamp_rate(3000) == 3000
    assert config.clamp_rate(999999) == 65535


def test_g560_clamp_brightness() -> None:
    """Test G560-specific brightness clamping."""
    config = get_device_config("g560")
    assert config.clamp_brightness(0) == 1
    assert config.clamp_brightness(50) == 50
    assert config.clamp_brightness(101) == 100


def test_g560_rate_range() -> None:
    """Test G560's rate range property."""
    config = get_device_config("g560")
    assert config.rate_range == (100, 65535)


def test_g560_brightness_range() -> None:
    """Test G560's brightness range property."""
    config = get_device_config("g560")
    assert config.brightness_range == (1, 100)


def test_g560_preset_colors() -> None:
    """Test G560's preset colors."""
    config = get_device_config("g560")
    presets = config.preset_colors
    assert len(presets) > 0
    assert ("Red", "ff0000") in presets
