import sys

# Windows Bluetooth threading configuration
sys.coinit_flags = 0

import asyncio
import threading
import queue
import time
from pathlib import Path

import cv2
import numpy as np
from bleak import BleakClient
import pytesseract

try:
    from bleak.backends.winrt.util import uninitialize_sta
    uninitialize_sta()
except ImportError:
    pass

# ==========================================
# CONFIGURATION
# ==========================================

LIGHT_MAC_ADDRESS = "36:46:3F:52:DB:31"
CAPTURE_CARD_INDEX = 1
CAPTURE_WIDTH = 800
CAPTURE_HEIGHT = 450

crop_coords = []

# LED colors (RGB)
BASE_COLOR = (255, 255, 255)
GREEN_COLOR = (0, 255, 0)
OFF_COLOR = (0, 0, 0)

# Bluetooth thread synchronization
_ble_queue = queue.Queue()
_is_animating = threading.Event()


# ==========================================
# BLUETOOTH LED CONTROL
# ==========================================

def _ble_worker():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def run_client(action):
        try:
            async with BleakClient(LIGHT_MAC_ADDRESS, timeout=5.0) as client:
                target_char = None
                for service in client.services:
                    for char in service.characteristics:
                        if "write" in char.properties or "write-without-response" in char.properties:
                            target_char = char.uuid
                            break
                    if target_char:
                        break

                if not target_char:
                    print("Bluetooth error: No writable characteristic found.")
                    return

                async def set_color(color):
                    command = bytearray([0x56, color[0], color[1], color[2], 0x00, 0xF0, 0xAA])
                    await client.write_gatt_char(target_char, command)

                if action == "startup":
                    await set_color(BASE_COLOR)
                    print("LEDs initialized.")
                    return

                if action == "trigger":
                    steps = 5
                    fade_duration = 0.8
                    interval = fade_duration / steps

                    await set_color(BASE_COLOR)

                    for _ in range(steps + 1):
                        await set_color(GREEN_COLOR)
                        await asyncio.sleep(interval / 2)
                        await set_color(OFF_COLOR)
                        await asyncio.sleep(interval / 2)

                    await set_color(GREEN_COLOR)
                    await asyncio.sleep(1.0)

                    for i in range(steps + 1):
                        progress = i / steps
                        color = tuple(
                            int(GREEN_COLOR[c] + (BASE_COLOR[c] - GREEN_COLOR[c]) * progress)
                            for c in range(3)
                        )
                        await set_color(color)
                        await asyncio.sleep(interval)

                    await set_color(BASE_COLOR)
                    print("LED animation completed.")

        except Exception as e:
            print(f"Bluetooth error: {e}")

    while True:
        action = _ble_queue.get()
        if action is None:
            _ble_queue.task_done()
            break
        try:
            loop.run_until_complete(run_client(action))
        finally:
            if action == "trigger":
                _is_animating.clear()
            _ble_queue.task_done()

    loop.close()


def trigger_leds():
    if _is_animating.is_set():
        return
    if not _ble_queue.empty():
        return
    _is_animating.set()
    _ble_queue.put("trigger")


# ==========================================
# HELPER FUNCTIONS
# ==========================================

def crop_image(image, x1, y1, x2, y2):
    """Crop the image to the specified coordinates, handling any coordinate order."""
    return image[min(y1, y2):max(y1, y2), min(x1, x2):max(x1, x2)]


def get_num(image):
    """Extract the number from the cropped image using pytesseract."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    config = r'--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789'
    text = pytesseract.image_to_string(gray, config=config).strip()
    if text.isdigit():
        num = int(text)
        # Limit to a reasonable range to avoid false positives
        if (num > 150):
            return None
        else:
            return num
    else:
        return None



def mouse_callback(event, x, y, flags, param):
    if event == cv2.EVENT_LBUTTONDOWN:
        print(f"Left click at coordinates: X={x}, Y={y}")
        if len(crop_coords) >= 2:
            crop_coords.pop(0)
        crop_coords.append((x, y))


# ==========================================
# LIVE POLLING LOOP
# ==========================================

def run_live_detection(cap, x1, y1, x2, y2):
    """Monitors the cropped region at ~5 FPS and triggers LEDs if the number increases."""
    print("\nLive monitoring started (5 Hz). Press 'q' to exit.")
    
    previous_number = None
    poll_interval = 0.2  # 5 times per second
    last_check_time = time.time()

    while True:
        ret, frame = cap.read()
        if not ret:
            print("ERROR: Failed to read capture card frame.")
            break
        
        current_time = time.time()
        if current_time - last_check_time >= poll_interval:
            last_check_time = current_time

            cropped_img = crop_image(frame, x1, y1, x2, y2)

            if cropped_img.size > 0:
                cropped_img = cv2.resize(cropped_img, (cropped_img.shape[1] * 4, cropped_img.shape[0] * 4), interpolation=cv2.INTER_AREA)
                current_number = get_num(cropped_img)

                if current_number is not None:
                    print(f"Detected Number: {current_number} (Previous: {previous_number})")

                    if previous_number is not None and current_number > previous_number:
                        print("Number increased! Triggering LEDs...")
                        trigger_leds()

                    previous_number = current_number if (previous_number is None or (current_number > previous_number and (current_number < previous_number + 4))) else previous_number

        cv2.imshow("Live Monitor", frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break


# ==========================================
# MAIN EXECUTION
# ==========================================

if __name__ == "__main__":
    # Start Bluetooth worker thread
    worker = threading.Thread(target=_ble_worker, daemon=True)
    worker.start()
    _ble_queue.put("startup")

    # Open capture card
    cap = cv2.VideoCapture(CAPTURE_CARD_INDEX, cv2.CAP_DSHOW)
    if not cap.isOpened():
        print("ERROR: Could not open capture card.")
        _ble_queue.put(None)
        exit(1)

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAPTURE_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAPTURE_HEIGHT)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    ret, sample_frame = cap.read()
    if not ret:
        print("ERROR: Could not grab sample frame from capture card.")
        cap.release()
        _ble_queue.put(None)
        exit(1)

    window_name = "Select Crop Region"
    cv2.namedWindow(window_name)
    cv2.setMouseCallback(window_name, mouse_callback)

    print("Click two points on the capture feed to set your region. Press 'q' to quit.")

    # Setup phase: wait until 2 points are clicked
    while len(crop_coords) < 2:
        cv2.imshow(window_name, sample_frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            cap.release()
            cv2.destroyAllWindows()
            _ble_queue.put(None)
            exit(0)

    cv2.destroyAllWindows()

    x1, y1 = crop_coords[0]
    x2, y2 = crop_coords[1]
    print(f"Crop region locked: ({x1}, {y1}) to ({x2}, {y2})")

    # Transition into live 5-Hz monitoring loop
    try:
        run_live_detection(cap, x1, y1, x2, y2)
    finally:
        cap.release()
        cv2.destroyAllWindows()
        _ble_queue.put(None)
        print("Capture stopped.")