"""Scan for Bluetooth LE LEDs and test RGB colors.

Install: pip install bleak
Run:     python LED_finder.py

Uses the same 0x56 RGB command protocol as LED_control.py.
Not every Bluetooth LED uses this protocol; only test devices you own.
"""
import sys
sys.coinit_flags = 0  # Windows Bluetooth compatibility; set before Bleak import

import asyncio
from bleak import BleakScanner, BleakClient

try:
    from bleak.backends.winrt.util import uninitialize_sta
    uninitialize_sta()
except ImportError:
    pass

KNOWN_ADDRESS = "36:46:3F:52:DB:31"
COLORS = {
    "red": (255, 0, 0),
    "green": (0, 255, 0),
    "blue": (0, 0, 255),
    "white": (255, 255, 255),
    "yellow": (255, 255, 0),
    "purple": (128, 0, 255),
    "off": (0, 0, 0),
}


def rgb_command(color):
    return bytes((0x56, *color, 0x00, 0xF0, 0xAA))


async def scan():
    print("\nScanning for BLE devices for 8 seconds...")
    devices = await BleakScanner.discover(timeout=8.0)
    devices = sorted(devices, key=lambda d: (d.name or "").lower())
    if not devices:
        print("No devices found. Check Bluetooth and LED power.")
        return []
    for i, device in enumerate(devices, 1):
        mark = "  <-- previous LED address" if device.address.upper() == KNOWN_ADDRESS.upper() else ""
        print(f"{i:>2}. {(device.name or '(unnamed)'):<28} {device.address}{mark}")
    print("\nNote: Some Windows BLE addresses may differ from printed MAC addresses.")
    return devices


async def run_led_connection_test(device):
    print(f"\nConnecting to {device.name or 'unnamed device'} ({device.address})...")
    async with BleakClient(device, timeout=12.0) as client:
        writable = []
        for service in client.services:
            for char in service.characteristics:
                if "write" in char.properties or "write-without-response" in char.properties:
                    writable.append(char)
        if not writable:
            print("Connected, but no writable characteristic was found.")
            return
        print("Writable characteristics:")
        for i, char in enumerate(writable, 1):
            print(f"  {i}. {char.uuid} ({', '.join(char.properties)})")
        choice = input("Characteristic number to test [1]: ").strip()
        try:
            char = writable[int(choice or '1') - 1]
        except (ValueError, IndexError):
            print("Invalid characteristic selection.")
            return
        response = "write" in char.properties
        print("\nType a color name, 'rgb R G B', 'demo', or 'quit'.")
        print("Available:", ", ".join(COLORS))

        async def send(color):
            await client.write_gatt_char(char, rgb_command(color), response=response)
            print(f"Sent RGB {color}. Check whether the LEDs changed.")

        while True:
            entry = (await asyncio.to_thread(input, "LED test> ")).strip().lower()
            if entry in ("quit", "q", "exit"):
                break
            if entry == "demo":
                for name in ("red", "green", "blue", "white"):
                    print(name)
                    try:
                        await send(COLORS[name])
                    except Exception as exc:
                        print(f"Write failed: {exc}")
                        break
                    await asyncio.sleep(1)
                continue
            if entry in COLORS:
                color = COLORS[entry]
            elif entry.startswith("rgb "):
                try:
                    parts = [int(x) for x in entry.split()[1:]]
                    if len(parts) != 3 or any(x < 0 or x > 255 for x in parts):
                        raise ValueError
                    color = tuple(parts)
                except ValueError:
                    print("Use: rgb 255 100 0")
                    continue
            else:
                print("Unknown command. Try green, red, demo, rgb 255 100 0, or quit.")
                continue
            try:
                await send(color)
            except Exception as exc:
                print(f"Write failed: {exc}")
                print("Try a different writable characteristic, or the LED may use another protocol.")

    print(f"\nIf this was the correct LED, use its address in your program:")
    print(f'LEDController(address="{device.address}")')


async def main():
    while True:
        try:
            devices = await scan()
        except Exception as exc:
            print(f"Scan failed: {exc}")
            return
        answer = (await asyncio.to_thread(input, "\nDevice number to test, R to rescan, or Q to quit: ")).strip().lower()
        if answer in ("q", "quit"):
            return
        if answer == "r":
            continue
        try:
            index = int(answer) - 1
            if index < 0 or index >= len(devices):
                raise ValueError
        except ValueError:
            print("Invalid selection.")
            continue
        try:
            await run_led_connection_test(devices[index])
        except Exception as exc:
            print(f"Connection/test failed: {exc}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
