from __future__ import annotations

import binascii
from dataclasses import dataclass

import usb.core
import usb.util

from .models import DeviceNotFoundError, PermissionDeniedError, TransferError

VENDOR_ID = 0x046D
PRODUCT_ID = 0x0A78
INTERFACE = 0x02

PREFIX = "11ff043a"
SUFFIX = "000000000000"


@dataclass
class DeviceSession:
    device: usb.core.Device
    detached_kernel_driver: bool = False

    def close(self) -> None:
        try:
            usb.util.release_interface(self.device, INTERFACE)
        except Exception:
            pass

        if self.detached_kernel_driver:
            try:
                self.device.attach_kernel_driver(INTERFACE)
            except Exception:
                pass

        try:
            usb.util.dispose_resources(self.device)
        except Exception:
            pass


class G560Transport:
    def open(self) -> DeviceSession:
        dev = usb.core.find(idVendor=VENDOR_ID, idProduct=PRODUCT_ID)
        if dev is None:
            raise DeviceNotFoundError(
                "Logitech G560 not found. Check USB connection and product support."
            )

        detached = False
        try:
            if dev.is_kernel_driver_active(INTERFACE):
                dev.detach_kernel_driver(INTERFACE)
                detached = True
        except (NotImplementedError, usb.core.USBError):
            pass

        try:
            usb.util.claim_interface(dev, INTERFACE)
        except usb.core.USBError as exc:
            raise PermissionDeniedError(
                f"Could not claim USB interface {INTERFACE}. "
                "Try a udev rule or root privileges."
            ) from exc

        return DeviceSession(device=dev, detached_kernel_driver=detached)

    def send_packet(self, session: DeviceSession, payload_hex: str) -> None:
        try:
            session.device.ctrl_transfer(
                0x21,
                0x09,
                0x0211,
                INTERFACE,
                binascii.unhexlify(payload_hex),
            )
        except usb.core.USBError as exc:
            raise TransferError(f"USB control transfer failed: {exc}") from exc

    def make_payload(self, zone_hex: str, mode_hex: str, data_hex: str) -> str:
        return PREFIX + zone_hex + mode_hex + data_hex + SUFFIX