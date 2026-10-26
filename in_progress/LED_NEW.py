import sys
sys.coinit_flags = 0  # Windows: use MTA for Bluetooth callbacks

import asyncio
import queue
import threading
from bleak import BleakClient
from Capture import run_capture

try:
    from bleak.backends.winrt.util import uninitialize_sta
    uninitialize_sta()
except ImportError:
    pass

# Configuration
LIGHT_MAC_ADDRESS = "36:46:3F:52:DB:31"

# RGB colors
BASE_COLOR = (255, 255, 255)
GREEN_COLOR = (0, 255, 0)
OFF_COLOR = (0, 0, 0)

_ble_queue = queue.Queue()
_animation_pending = threading.Event()


def color_command(rgb):
    return bytearray([0x56, *rgb, 0x00, 0xF0, 0xAA])


async def send_lights(action):
    try:
        print(f"Connecting to Bluetooth light: {LIGHT_MAC_ADDRESS}...")

        async with BleakClient(LIGHT_MAC_ADDRESS, timeout=5.0) as client:

            if client.is_connected:
                print("Bluetooth light CONNECTED")
            else:
                print("Bluetooth light NOT CONNECTED")
                return

            characteristic = next(
                (char for service in client.services
                 for char in service.characteristics
                 if "write" in char.properties or "write-without-response" in char.properties),
                None,
            )

            if characteristic is None:
                print("Bluetooth error: No writable characteristic found.")
                return

            # Keep the rest of your existing animation code here

    except Exception as exc:
        print(f"Bluetooth connection FAILED: {exc}")


def ble_worker():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        while True:
            action = _ble_queue.get()

            try:
                if action is None:
                    return

                loop.run_until_complete(send_lights(action))

            finally:
                if action == "trigger":
                    _animation_pending.clear()

                _ble_queue.task_done()

    finally:
        loop.close()


def trigger_leds():
    if not _animation_pending.is_set():
        _animation_pending.set()
        _ble_queue.put("trigger")


def run_detection():
    worker = threading.Thread(target=ble_worker, daemon=True)
    worker.start()

    _ble_queue.put("startup")

    try:
        run_capture(on_detect=trigger_leds)

    finally:
        _ble_queue.put(None)
        worker.join(timeout=2)


if __name__ == "__main__":
    run_detection()
