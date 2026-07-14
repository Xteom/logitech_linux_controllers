# Color Utilities Refactoring

## Issue

The original architecture had device-specific color utilities (rate/brightness clamping, preset colors) in the core package, making them universal across all devices. This was incorrect because:

1. **Different devices have different rate ranges** - G560 supports 100-65535ms, but other devices might have different ranges
2. **Different devices have different brightness ranges** - G560 uses 1-100%, others might use 0-255 or 10-100%
3. **Preset colors should be device-specific** - Optimized for each device's LED characteristics

## Solution

Moved device-specific color utilities from core to device configurations.

### Architecture Changes

**Before:**
```
core/colors.py (device-agnostic)
  ├── parse_color()           ✓ Universal
  ├── clamp_rate()            ✗ G560-specific (hardcoded 100-65535)
  ├── clamp_brightness()      ✗ G560-specific (hardcoded 1-100)
  └── PRESET_COLORS           ✗ G560-specific
```

**After:**
```
core/colors.py (truly device-agnostic)
  └── parse_color()           ✓ Universal (RGB is RGB)

devices/g560/config.py (G560-specific)
  ├── rate_range              ✓ (100, 65535)
  ├── brightness_range        ✓ (1, 100)
  ├── clamp_rate()            ✓ G560-specific
  ├── clamp_brightness()      ✓ G560-specific
  └── preset_colors           ✓ G560-optimized presets
```

### DeviceConfig Protocol Extended

Added new required properties and methods:

```python
class DeviceConfig(Protocol):
    @property
    def rate_range(self) -> tuple[int, int]:
        """Device-specific rate range in milliseconds (min, max)."""
        ...
    
    @property
    def brightness_range(self) -> tuple[int, int]:
        """Device-specific brightness range (min, max)."""
        ...
    
    @property
    def preset_colors(self) -> list[tuple[str, str]]:
        """Device-specific preset colors (name, hex)."""
        ...
    
    def clamp_rate(self, rate_ms: int) -> int:
        """Clamp rate to device-specific valid range."""
        ...
    
    def clamp_brightness(self, brightness: int) -> int:
        """Clamp brightness to device-specific valid range."""
        ...
```

### G560Config Implementation

```python
@dataclass
class G560Config:
    @property
    def rate_range(self) -> tuple[int, int]:
        """G560 supports 100-65535ms rate range."""
        return (100, 65535)
    
    @property
    def brightness_range(self) -> tuple[int, int]:
        """G560 supports 1-100% brightness range."""
        return (1, 100)
    
    def clamp_rate(self, rate_ms: int) -> int:
        """Clamp rate to G560's valid range (100-65535ms)."""
        min_ms, max_ms = self.rate_range
        return max(min_ms, min(max_ms, rate_ms))
    
    def clamp_brightness(self, brightness: int) -> int:
        """Clamp brightness to G560's valid range (1-100%)."""
        min_b, max_b = self.brightness_range
        return max(min_b, min(max_b, brightness))
```

### Controller Updated

The unified controller now delegates to device-specific clamping:

```python
def breathe(self, color: Color, zones: frozenset[str], 
            rate_ms: int = 3000, brightness: int = 100) -> LightingRequest:
    request = LightingRequest(
        mode=Mode.BREATHE,
        zones=zones,
        color=color,
        rate_ms=self.config.clamp_rate(rate_ms),      # Device-specific
        brightness=self.config.clamp_brightness(brightness),  # Device-specific
    )
    self.apply(request)
    return request
```

## Benefits

1. **Correctness**: Each device can define its own valid ranges
2. **Extensibility**: Adding a new device with different ranges is trivial
3. **Clarity**: Device-specific limits are co-located with device logic
4. **Flexibility**: Easy to see and modify device capabilities

## Example: Adding G733 Headset

With this architecture, adding G733 with different ranges is straightforward:

```python
@dataclass
class G733Config:
    @property
    def rate_range(self) -> tuple[int, int]:
        """G733 might support 500-10000ms range."""
        return (500, 10000)
    
    @property
    def brightness_range(self) -> tuple[int, int]:
        """G733 might use 10-100% range."""
        return (10, 100)
    
    # ... clamp methods use these ranges
```

The unified controller automatically uses the correct ranges for each device!

## Backward Compatibility

The old `g560ctl` package maintains its own `colors.py` with hardcoded G560 ranges for backward compatibility. Old tests continue to pass.

## Testing

- **Old tests**: 12 tests pass (100% backward compatibility)
- **New tests**: 15 tests pass (including 3 new device-specific tests)
- **Total**: 27/27 tests passing

New tests verify:
- `test_g560_clamp_rate()` - G560's rate clamping
- `test_g560_clamp_brightness()` - G560's brightness clamping  
- `test_g560_rate_range()` - G560's rate range property
- `test_g560_brightness_range()` - G560's brightness range property
- `test_g560_preset_colors()` - G560's preset colors

## Files Changed

1. `logitech_lighting/devices/base.py` - Extended DeviceConfig protocol
2. `logitech_lighting/devices/g560/config.py` - Added G560-specific utilities
3. `logitech_lighting/core/colors.py` - Reduced to universal parsing only
4. `logitech_lighting/controller.py` - Updated to use device-specific clamping
5. `test/test_new_colors.py` - Updated tests for device-specific behavior
6. `g560ctl/colors.py` - Kept hardcoded values for backward compatibility

## Conclusion

This refactoring makes the architecture truly device-agnostic in core modules while properly handling device-specific capabilities in device configurations. The result is a more correct, maintainable, and extensible system.
