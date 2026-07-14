from __future__ import annotations

from collections.abc import Iterable

from logitech_lighting.core.exceptions import ValidationError
from logitech_lighting.devices.base import DeviceConfig


def resolve_zones(
    values: str | Iterable[str] | None,
    device_config: DeviceConfig
) -> frozenset[str]:
    """Resolve zone names/aliases to concrete zone names for a device."""
    zone_aliases = device_config.zone_aliases
    
    if values is None:
        return frozenset(zone_aliases["all"])

    tokens: list[str] = []

    if isinstance(values, str):
        raw_items = values.split(",")
    else:
        raw_items = []
        for item in values:
            raw_items.extend(str(item).split(","))

    for item in raw_items:
        token = item.strip().lower()
        if token:
            tokens.append(token)

    if not tokens:
        raise ValidationError("No zones selected")

    resolved: set[str] = set()
    for token in tokens:
        if token not in zone_aliases:
            valid = ", ".join(sorted(zone_aliases))
            raise ValidationError(f"Unknown zone '{token}'. Valid zones: {valid}")
        resolved.update(zone_aliases[token])

    if not resolved:
        raise ValidationError("No zones selected")

    return frozenset(resolved)
