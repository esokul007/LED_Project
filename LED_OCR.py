import cv2

from LED_control import LEDController

leds = LEDController()
leds.start()  # non-blocking; connects in background
