
import sys
sys.coinit_flags = 0  # Windows Bluetooth compatibility

import asyncio
from bleak import BleakClient

# Bluetooth light address
LIGHT_MAC_ADDRESS = "36:46:3F:52:DB:31"

# RGB colors
GREEN = (0, 255, 0)
WHITE = (255, 255, 255)


def color_command(rgb):
    return bytes([
        0x56,
        *rgb,
        0x00,
        0xF0,
        0xAA
    ])


async def main():
    print(f"Connecting to {LIGHT_MAC_ADDRESS}...")

    try:
        async with BleakClient(
            LIGHT_MAC_ADDRESS,
            timeout=15.0
        ) as client:

            print(f"Connected: {client.is_connected}")

            # Find writable Bluetooth characteristic
            characteristic = next(
                (
                    char
                    for service in client.services
                    for char in service.characteristics
                    if "write" in char.properties
                    or "write-without-response" in char.properties
                ),
                None
            )

            if characteristic is None:
                print("No writable BLE characteristic found.")
                return

            print(
                f"Using characteristic: {characteristic.uuid}"
            )

            use_response = (
                "write" in characteristic.properties
            )

            # Turn LEDs green
            print("Sending GREEN...")

            await client.write_gatt_char(
                characteristic,
                color_command(GREEN),
                response=use_response
            )

            # Hold green for 3 seconds
            await asyncio.sleep(3)

            # Return LEDs to white
            print("Sending WHITE...")

            await client.write_gatt_char(
                characteristic,
                color_command(WHITE),
                response=use_response
            )

            print("Test complete.")

    except Exception as exc:
        print(f"Bluetooth error: {exc!r}")


if __name__ == "__main__":
    asyncio.run(main())
