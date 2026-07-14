#!/home/xteom/Documents/personal/speakers_ligth/.venv/bin/python
import binascii
import usb.core
import usb.util

VENDOR_ID = 0x046d
PRODUCT_ID = 0x0a78
INTERFACE = 2
ZONES = ["00", "01", "02", "03"]

dev = usb.core.find(idVendor=VENDOR_ID, idProduct=PRODUCT_ID)
if dev is None:
    raise SystemExit("G560 not found")

detached = False

try:
    try:
        if dev.is_kernel_driver_active(INTERFACE):
            dev.detach_kernel_driver(INTERFACE)
            detached = True
    except Exception:
        pass

    usb.util.claim_interface(dev, INTERFACE)

    for zone in ZONES:
        payload = "11ff043a" + zone + "01" + "ff0000" + "0000000000" + "000000000000"
        dev.ctrl_transfer(0x21, 0x09, 0x0211, INTERFACE, binascii.unhexlify(payload))
        print(f"Sent green to zone {zone}")
finally:
    try:
        usb.util.release_interface(dev, INTERFACE)
    except Exception:
        pass
    if detached:
        try:
            dev.attach_kernel_driver(INTERFACE)
        except Exception:
            pass