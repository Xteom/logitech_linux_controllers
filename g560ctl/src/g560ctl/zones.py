"""DEAD CODE — legacy G560-only module, not on the runtime path.

Superseded by ``logitech_lighting.devices.g560.config``. Both console scripts
(``g560ctl`` and ``logitech-lighting``) run the ``logitech_lighting`` package;
``g560ctl/cli.py`` is only a thin shim that imports it. This module is retained
for reference and is exercised solely by the legacy ``test/`` suite — do not
extend it.
"""

from __future__ import annotations

from collections.abc import Iterable

from .models import ValidationError, Zone

ZONE_TO_DEVICE_ID: dict[Zone, str] = {
    Zone.LEFT_SECONDARY: "00",
    Zone.RIGHT_SECONDARY: "01",
    Zone.LEFT_PRIMARY: "02",
    Zone.RIGHT_PRIMARY: "03",
}

ZONE_LABELS: dict[Zone, str] = {
    Zone.LEFT_SECONDARY: "Left rear",
    Zone.RIGHT_SECONDARY: "Right rear",
    Zone.LEFT_PRIMARY: "Left front",
    Zone.RIGHT_PRIMARY: "Right front",
}

ZONE_ALIASES: dict[str, tuple[Zone, ...]] = {
    "all": (
        Zone.LEFT_SECONDARY,
        Zone.RIGHT_SECONDARY,
        Zone.LEFT_PRIMARY,
        Zone.RIGHT_PRIMARY,
    ),
    "left": (
        Zone.LEFT_SECONDARY,
        Zone.LEFT_PRIMARY,
    ),
    "right": (
        Zone.RIGHT_SECONDARY,
        Zone.RIGHT_PRIMARY,
    ),
    "primary": (
        Zone.LEFT_PRIMARY,
        Zone.RIGHT_PRIMARY,
    ),
    "secondary": (
        Zone.LEFT_SECONDARY,
        Zone.RIGHT_SECONDARY,
    ),
    "left_secondary": (Zone.LEFT_SECONDARY,),
    "right_secondary": (Zone.RIGHT_SECONDARY,),
    "left_primary": (Zone.LEFT_PRIMARY,),
    "right_primary": (Zone.RIGHT_PRIMARY,),
}


def resolve_zones(values: str | Iterable[str] | None) -> frozenset[Zone]:
    if values is None:
        return frozenset(ZONE_ALIASES["all"])

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

    resolved: set[Zone] = set()
    for token in tokens:
        if token not in ZONE_ALIASES:
            valid = ", ".join(sorted(ZONE_ALIASES))
            raise ValidationError(f"Unknown zone '{token}'. Valid zones: {valid}")
        resolved.update(ZONE_ALIASES[token])

    if not resolved:
        raise ValidationError("No zones selected")

    return frozenset(resolved)