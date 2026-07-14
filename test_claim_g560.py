#!/home/xteom/Documents/personal/speakers_ligth/.venv/bin/python
import usb.core
import usb.util

VENDOR_ID = 0x046d
PRODUCT_ID = 0x0a78
INTERFACE = 2

dev = usb.core.find(idVendor=VENDOR_ID, idProduct=PRODUCT_ID)
if dev is None:
    raise SystemExit("G560 not found")

detached = False

try:
    if dev.is_kernel_driver_active(INTERFACE):
        dev.detach_kernel_driver(INTERFACE)
        detached = True
        print("Detached kernel driver")
except Exception as e:
    print(f"Kernel driver check/detach skipped: {e}")

try:
    usb.util.claim_interface(dev, INTERFACE)
    print("Claimed interface successfully")
finally:
    try:
        usb.util.release_interface(dev, INTERFACE)
        print("Released interface")
    except Exception as e:
        print(f"Release failed: {e}")

    if detached:
        try:
            dev.attach_kernel_driver(INTERFACE)
            print("Reattached kernel driver")
        except Exception as e:
            print(f"Reattach failed: {e}")