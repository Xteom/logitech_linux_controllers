from __future__ import annotations

import usb.core

from logitech_lighting.devices.base import DeviceConfig, DeviceInfo
from logitech_lighting.devices.g560.config import G560Config

# Registry of all supported devices
DEVICE_CONFIGS: dict[str, DeviceConfig] = {
    "g560": G560Config(),
}


def get_device_config(device_id: str) -> DeviceConfig:
    """Get device configuration by ID."""
    if device_id not in DEVICE_CONFIGS:
        available = ", ".join(DEVICE_CONFIGS.keys())
        raise ValueError(f"Unknown device '{device_id}'. Available: {available}")
    return DEVICE_CONFIGS[device_id]


def discover_devices() -> list[DeviceInfo]:
    """Discover all connected supported devices."""
    discovered = []
    
    for device_id, config in DEVICE_CONFIGS.items():
        dev = usb.core.find(idVendor=config.vendor_id, idProduct=config.product_id)
        discovered.append(DeviceInfo(
            config_id=device_id,
            name=config.name,
            vendor_id=config.vendor_id,
            product_id=config.product_id,
            connected=(dev is not None)
        ))
    
    return discovered


def get_default_device() -> str:
    """Get the first connected device, or default to g560."""
    devices = discover_devices()
    for device in devices:
        if device.connected:
            return device.config_id
    return "g560"
