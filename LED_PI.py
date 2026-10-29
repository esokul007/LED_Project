import sys
import asyncio
import threading
import queue
import time
from pathlib import Path

import cv2
import numpy as np
from bleak import BleakClient

# Windows-specific Bluetooth configuration
if sys.platform.startswith("win"):
    sys.coinit_flags = 0
    try:
        from bleak.backends.winrt.util import uninitialize_sta
        uninitialize_sta()
    except ImportError:
        pass


# ==========================================
# CONFIGURATION
# ==========================================

LIGHT_MAC_ADDRESS = "36:46:3F:52:DB:31"

# Physical capture card (0 on Pi, 1 on Windows)
CAPTURE_CARD_INDEX = 0

CAPTURE_WIDTH = 1920
CAPTURE_HEIGHT = 1080

# Timing box where the right edge stops at the X center of the screen
CROP_WIDTH = 180
CROP_HEIGHT = 60

# Right edge is at the center (1920 / 2 = 960), so left edge starts at 960 - 360 = 600
CROP_X = (CAPTURE_WIDTH // 2) - CROP_WIDTH
CROP_Y = 18

# Template image path
TEMPLATE_PATH = (
    Path(__file__).parent / "images" / "green_shot_only.png"
)

MATCH_THRESHOLD = 0.85
REARM_FRAMES = 5

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
            async with BleakClient(
                LIGHT_MAC_ADDRESS,
                timeout=5.0
            ) as client:
                target_char = None

                for service in client.services:
                    for char in service.characteristics:
                        if (
                            "write" in char.properties
                            or "write-without-response" in char.properties
                        ):
                            target_char = char.uuid
                            break

                    if target_char:
                        break

                if not target_char:
                    print("Bluetooth error: No writable characteristic found.")
                    return

                async def set_color(color):
                    command = bytearray([
                        0x56,
                        color[0],
                        color[1],
                        color[2],
                        0x00,
                        0xF0,
                        0xAA
                    ])
                    await client.write_gatt_char(
                        target_char,
                        command
                    )

                # Set base color at startup
                if action == "startup":
                    await set_color(BASE_COLOR)
                    print("LEDs initialized.")
                    return

                # Green animation
                if action == "trigger":
                    steps = 5
                    fade_duration = 0.8
                    interval = fade_duration / steps

                    # Start at base color
                    await set_color(BASE_COLOR)

                    # Flash green
                    for _ in range(steps + 1):
                        await set_color(GREEN_COLOR)
                        await asyncio.sleep(interval / 2)

                        await set_color(OFF_COLOR)
                        await asyncio.sleep(interval / 2)

                    # Hold green
                    await set_color(GREEN_COLOR)
                    await asyncio.sleep(1.0)

                    # Fade from green to base color
                    for i in range(steps + 1):
                        progress = i / steps
                        color = tuple(
                            int(
                                GREEN_COLOR[c]
                                + (
                                    BASE_COLOR[c]
                                    - GREEN_COLOR[c]
                                ) * progress
                            )
                            for c in range(3)
                        )
                        await set_color(color)
                        await asyncio.sleep(interval)

                    # Return to base color
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
            loop.run_until_complete(
                run_client(action)
            )
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

    # Lock immediately to avoid duplicate triggers
    _is_animating.set()
    _ble_queue.put("trigger")


# ==========================================
# FRAME CROPPING
# ==========================================

def crop_frame(frame):
    frame_height, frame_width = frame.shape[:2]

    scale_x = frame_width / CAPTURE_WIDTH
    scale_y = frame_height / CAPTURE_HEIGHT

    x1 = int(CROP_X * scale_x)
    y1 = int(CROP_Y * scale_y)
    x2 = int((CROP_X + CROP_WIDTH) * scale_x)
    y2 = int((CROP_Y + CROP_HEIGHT) * scale_y)

    x1 = max(0, x1)
    y1 = max(0, y1)
    x2 = min(frame_width, x2)
    y2 = min(frame_height, y2)

    cropped = frame[y1:y2, x1:x2]

    if cropped.size == 0:
        raise ValueError(
            "Invalid crop region. Check capture card resolution."
        )

    cropped = cv2.resize(
        cropped,
        (CROP_WIDTH, CROP_HEIGHT),
        interpolation=cv2.INTER_AREA
    )

    return cropped


# ==========================================
# TEMPLATE MATCHING
# ==========================================

def load_template():
    template = cv2.imread(
        str(TEMPLATE_PATH),
        cv2.IMREAD_COLOR
    )

    if template is None:
        raise FileNotFoundError(
            f"Cannot load template: {TEMPLATE_PATH}"
        )

    template = cv2.resize(
        template,
        (CROP_WIDTH, CROP_HEIGHT),
        interpolation=cv2.INTER_AREA
    )

    print(
        f"Template loaded: "
        f"{template.shape[1]}x{template.shape[0]}"
    )

    return template


def match_banner(cropped, template):
    result = cv2.matchTemplate(
        cropped,
        template,
        cv2.TM_CCOEFF_NORMED
    )
    _, confidence, _, _ = cv2.minMaxLoc(result)
    return confidence


# ==========================================
# MAIN DETECTION
# ==========================================

def run_detection():
    # Start Bluetooth worker
    worker = threading.Thread(
        target=_ble_worker,
        daemon=True
    )
    worker.start()

    # Initialize LEDs
    _ble_queue.put("startup")

    # Open capture card with cross-platform backend handling
    if sys.platform.startswith("win"):
        cap = cv2.VideoCapture(CAPTURE_CARD_INDEX, cv2.CAP_DSHOW)
    else:
        cap = cv2.VideoCapture(CAPTURE_CARD_INDEX, cv2.CAP_V4L2)

    if not cap.isOpened():
        print("ERROR: Could not open capture card.")
        _ble_queue.put(None)
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAPTURE_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAPTURE_HEIGHT)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    actual_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    print(f"Capture card resolution: {actual_width}x{actual_height}")

    try:
        template = load_template()
    except FileNotFoundError as e:
        print(e)
        cap.release()
        _ble_queue.put(None)
        return

    print("Monitoring for TIMING EXCELLENT (Headless Mode)...")
    print("Press Ctrl+C to exit.")

    banner_active = False
    missing_frames = 0
    xbox_on = False

    try:
        while True:
            ret, frame = cap.read()
        
            if not ret or frame is None:
                print("\nERROR, Capture Card is not plugged into PI. Pausing detection...")
                # Check less frequently when off to save CPU (e.g., every 30 seconds)
                time.sleep(30)
                continue

            if np.mean(frame) < 2.0:
                print("\nERROR, XBOX is off. Pausing detection...")
                xbox_on = False

                time.sleep(30)
                continue

            if not xbox_on:
                print("\nXbox detected! Starting detection...")
                xbox_on = True

            # Crop timing box
            cropped = crop_frame(frame)

            # Perform template matching
            confidence = match_banner(cropped, template)
            detected = confidence >= MATCH_THRESHOLD

            # ==================================
            # TRIGGER DETECTION
            # ==================================

            if detected:
                missing_frames = 0

                if not banner_active:
                    banner_active = True
                    print(
                        f"EXCELLENT DETECTED! "
                        f"Confidence: {confidence:.3f}"
                    )
                    trigger_leds()
            else:
                missing_frames += 1

                if missing_frames >= REARM_FRAMES:
                    banner_active = False

            # Small sleep to prevent 100% CPU usage in headless loops (~30 FPS)
            time.sleep(0.03)

    except KeyboardInterrupt:
        print("\nStopped by user.")

    finally:
        cap.release()
        _ble_queue.put(None)
        print("Capture stopped.")


# ==========================================
# START PROGRAM
# ==========================================

if __name__ == "__main__":
    run_detection()
