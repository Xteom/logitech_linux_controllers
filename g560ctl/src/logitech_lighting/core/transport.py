from __future__ import annotations

import binascii
from dataclasses import dataclass
from typing import Protocol

import usb.core
import usb.util

from logitech_lighting.core.exceptions import DeviceNotFoundError, PermissionDeniedError, TransferError


@dataclass
class DeviceSession:
    """Generic USB device session."""
    device: usb.core.Device
    interface: int
    detached_kernel_driver: bool = False

    def close(self) -> None:
        try:
            usb.util.release_interface(self.device, self.interface)
        except Exception:
            pass

        if self.detached_kernel_driver:
            try:
                self.device.attach_kernel_driver(self.interface)
            except Exception:
                pass

        try:
            usb.util.dispose_resources(self.device)
        except Exception:
            pass


class USBTransport:
    """Generic USB transport for Logitech devices."""
    
    def __init__(self, vendor_id: int, product_id: int, interface: int):
        self.vendor_id = vendor_id
        self.product_id = product_id
        self.interface = interface

    def open(self) -> DeviceSession:
        dev = usb.core.find(idVendor=self.vendor_id, idProduct=self.product_id)
        if dev is None:
            raise DeviceNotFoundError(
                f"Device {self.vendor_id:04x}:{self.product_id:04x} not found. "
                "Check USB connection and product support."
            )

        detached = False
        try:
            if dev.is_kernel_driver_active(self.interface):
                dev.detach_kernel_driver(self.interface)
                detached = True
        except (NotImplementedError, usb.core.USBError):
            pass

        try:
            usb.util.claim_interface(dev, self.interface)
        except usb.core.USBError as exc:
            raise PermissionDeniedError(
                f"Could not claim USB interface {self.interface}. "
                "Try a udev rule or root privileges."
            ) from exc

        return DeviceSession(
            device=dev,
            interface=self.interface,
            detached_kernel_driver=detached
        )

    def send_packet(self, session: DeviceSession, payload_hex: str) -> None:
        try:
            session.device.ctrl_transfer(
                0x21,
                0x09,
                0x0211,
                self.interface,
                binascii.unhexlify(payload_hex),
            )
        except usb.core.USBError as exc:
            raise TransferError(f"USB control transfer failed: {exc}") from exc
