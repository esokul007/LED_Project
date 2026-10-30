"""Reusable Bluetooth RGB LED controller for the existing 0x56 RGB protocol.

Requires: pip install bleak

Example:
    from led_control import LEDController, GREEN

    leds = LEDController()
    leds.start()                 # non-blocking; connects in background
    leds.animate(GREEN)          # non-blocking; ignores overlapping animations
    # When exiting:
    leds.close()
"""

import asyncio
import queue
import sys
import threading
from typing import Optional, Tuple

# Set before importing Bleak on Windows.
sys.coinit_flags = 0
from bleak import BleakClient

try:
    from bleak.backends.winrt.util import uninitialize_sta
    uninitialize_sta()
except ImportError:
    pass

RGB = Tuple[int, int, int]
WHITE: RGB = (255, 255, 255)
GREEN: RGB = (0, 255, 0)
RED: RGB = (255, 0, 0)
BLUE: RGB = (0, 0, 255)
OFF: RGB = (0, 0, 0)

# Set this to the MAC address of your LED controller, or pass it to LEDController() on init
DEFAULT_ADDRESS = "36:46:3F:52:DB:31"


def _validate_color(color) -> RGB:
    if not isinstance(color, (tuple, list)) or len(color) != 3:
        raise ValueError("Color must be an RGB tuple/list, e.g. (0, 255, 0)")
    if any(type(v) is not int or not 0 <= v <= 255 for v in color):
        raise ValueError("Each RGB channel must be an integer from 0 to 255")
    return tuple(color)


class LEDController:
    def __init__(self, address: str = DEFAULT_ADDRESS, base_color: RGB = WHITE,
                 characteristic_uuid: Optional[str] = None, timeout: float = 5.0):
        self.address = address
        self.base_color = _validate_color(base_color)
        self.characteristic_uuid = characteristic_uuid
        self.timeout = timeout
        self._queue = queue.Queue()
        self._thread = None
        self._animation_pending = threading.Event()
        self._closed = False
        self._lock = threading.Lock()

    def start(self):
        """Start worker and queue initial base color; safe to call repeatedly."""
        with self._lock:
            if self._closed:
                raise RuntimeError("Controller has been closed")
            if self._thread is None:
                self._thread = threading.Thread(target=self._worker, daemon=True)
                self._thread.start()
                self._queue.put(("color", self.base_color))
        return self

    def set_color(self, color: RGB):
        """Queue a color change without blocking capture/detection."""
        color = _validate_color(color)
        self.start()
        self._queue.put(("color", color))

    def reset(self):
        self.set_color(self.base_color)

    def turn_off(self):
        self.set_color(OFF)

    def flash(self, color: RGB, count: int = 5, interval: float = 0.16,
              restore: bool = True) -> bool:
        """Flash a color count times, then optionally restore base color."""
        color = _validate_color(color)
        if count < 1 or interval <= 0:
            raise ValueError("count must be >= 1 and interval > 0")
        self.start()
        if self._animation_pending.is_set():
            return False
        self._animation_pending.set()
        self._queue.put(("flash", (color, count, interval, restore)))
        return True
