import sys

sys.coinit_flags = 0  # Force Multi-Threaded Apartment mode for Windows Bluetooth callbacks

import asyncio
import threading
import queue
import cv2
import numpy as np
from bleak import BleakClient

# Fix for Windows GUI / OpenCV threading conflict with Bleak callbacks
try:
    from bleak.backends.winrt.util import uninitialize_sta

    uninitialize_sta()
except ImportError:
    pass

# Configuration
LIGHT_MAC_ADDRESS = "36:46:3F:52:DB:31"
CAPTUR_CARD_INDEX = 2  # Adjust if your capture card index is different

# Define your base color here (Red, Green, Blue from 0 to 255)
# Examples: Cyan = (0, 255, 255), Purple = (255, 0, 255), Red = (255, 0, 0), Blue = (0, 0, 255)
BASE_COLOR = (255, 255, 255)  # Currently set to White
GREEN_COLOR = (0, 255, 0)
OFF_COLOR = (0, 0, 0)  # Color to turn off the lights (black)

# Thread-safe queue and animation lock
_ble_queue = queue.Queue()
_is_animating = threading.Event()


def _ble_worker():
    """Background worker thread to run asynchronous BLE code safely away from OpenCV GUI"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def run_client(is_startup=False, is_trigger=False):
        try:
            async with BleakClient(LIGHT_MAC_ADDRESS, timeout=5.0) as client:
                if client.is_connected:
                    target_char = None
                    for service in client.services:
                        for char in service.characteristics:
                            if "write" in char.properties or "write-without-response" in char.properties:
                                target_char = char.uuid
                                break
                        if target_char:
                            break

                    if target_char:
                        base_cmd = bytearray([0x56, BASE_COLOR[0], BASE_COLOR[1], BASE_COLOR[2], 0x00, 0xF0, 0xAA])

                        if is_startup:
                            # Set lights to base color immediately on startup
                            await client.write_gatt_char(target_char, base_cmd)
                        elif is_trigger:
                            steps = 5
                            fade_duration = 0.8
                            interval = fade_duration / steps

                            # 1. Start at base color baseline
                            await client.write_gatt_char(target_char, base_cmd)

                            # 2. Buzzing Strobe effect for green
                            for i in range(steps + 1):
                                await client.write_gatt_char(target_char, bytearray(
                                    [0x56, GREEN_COLOR[0], GREEN_COLOR[1], GREEN_COLOR[2], 0x00, 0xF0, 0xAA]))
                                await asyncio.sleep(interval / 2)
                                # Flash off (or base/black)
                                await client.write_gatt_char(target_char, bytearray(
                                    [0x56, OFF_COLOR[0], OFF_COLOR[1], OFF_COLOR[2], 0x00, 0xF0, 0xAA]))
                                await asyncio.sleep(interval / 2)

                                # 3. Hold solid green for about a second longer
                            await client.write_gatt_char(target_char, bytearray(
                                [0x56, GREEN_COLOR[0], GREEN_COLOR[1], GREEN_COLOR[2], 0x00, 0xF0, 0xAA]))
                            await asyncio.sleep(1.0)

                            # 4. Fade back from Green to Base Color
                            for i in range(steps + 1):
                                progress = i / steps
                                r = int(GREEN_COLOR[0] + (BASE_COLOR[0] - GREEN_COLOR[0]) * progress)
                                g = int(GREEN_COLOR[1] + (BASE_COLOR[1] - GREEN_COLOR[1]) * progress)
                                b = int(GREEN_COLOR[2] + (BASE_COLOR[2] - GREEN_COLOR[2]) * progress)

                                color_cmd = bytearray([0x56, r, g, b, 0x00, 0xF0, 0xAA])
                                await client.write_gatt_char(target_char, color_cmd)
                                await asyncio.sleep(interval)

                            # 5. End on solid base color
                            await client.write_gatt_char(target_char, base_cmd)
                    else:
                        print("Bluetooth error: No writable characteristic found on this device.")
        except Exception as e:
            print(f"Bluetooth error: {e}")

    while True:
        action = _ble_queue.get()
        if action is None:
            break
        if action == "startup":
            loop.run_until_complete(run_client(is_startup=True))
        elif action == "trigger":
            _is_animating.set()
            loop.run_until_complete(run_client(is_trigger=True))
            _is_animating.clear()  # Unlock detection only when the full LED sequence completes
        _ble_queue.task_done()


def trigger_leds():
    """Safe wrapper to run async Bluetooth tasks from synchronous loops"""
    if _is_animating.is_set():
        return  # Ignore triggers if an animation is already in progress
    _ble_queue.put("trigger")


def run_detection():
    # Start background BLE worker thread once when detection begins
    t = threading.Thread(target=_ble_worker, daemon=True)
    t.start()

    # Request base color lights immediately upon starting
    _ble_queue.put("startup")

    # Use DirectShow backend to prevent MSMF locks with OBS
    cap = cv2.VideoCapture(CAPTUR_CARD_INDEX, cv2.CAP_DSHOW)

    # Load the template image in color (BGR) for precise color matching
    template = cv2.imread('../images/green_j.png', cv2.IMREAD_COLOR)
    if template is None:
        print(
            "Error: 'template.png' not found! Please save a screenshot of the banner as 'template.png' in this directory.")
        return

    print("Started monitoring for 'TIMING EXCELLENT' banner... Press 'q' to exit.")

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            print("Failed to grab frame from capture card.")
            break

        # Run multi-channel color template matching directly on the BGR frame
        result = cv2.matchTemplate(frame, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)

        # Show live feed window
        cv2.imshow('Banner Template Matching', frame)

        # If confidence score exceeds 85% and LEDs are completely idle, trigger reaction
        if max_val > 0.85 and not _is_animating.is_set():
            print(f"\nGreen release matched! (Confidence: {max_val:.2f})")
            trigger_leds()

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    run_detection()