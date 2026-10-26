
import cv2
import numpy as np
import time

# Capture card configuration
CAPTURE_CARD_INDEX = 1

# Top-left detection region
CROP_WIDTH = 120
CROP_HEIGHT = 40

# HSV range for green (exclude yellow)
LOWER_GREEN = np.array([40, 40, 40])
UPPER_GREEN = np.array([85, 255, 255])

# Expected rectangle dimensions
MIN_WIDTH = 70
MAX_WIDTH = 250
MIN_HEIGHT = 15
MAX_HEIGHT = 90

# Rectangle verification
MIN_BORDER_COVERAGE = 0.60
EDGE_THICKNESS = 3


def calculate_border_coverage(mask, x, y, w, h):
    """Measure how much of the rectangle border is green."""

    region = mask[y:y+h, x:x+w]

    border = np.zeros((h, w), dtype=np.uint8)

    cv2.rectangle(
        border,
        (0, 0),
        (w - 1, h - 1),
        255,
        EDGE_THICKNESS
    )

    border_pixels = cv2.countNonZero(border)

    if border_pixels == 0:
        return 0.0

    green_border = cv2.countNonZero(
        cv2.bitwise_and(region, border)
    )

    return green_border / border_pixels


def run_capture(on_detect=None):
    cap = cv2.VideoCapture(
        CAPTURE_CARD_INDEX,
        cv2.CAP_DSHOW
    )

    if not cap.isOpened():
        print("ERROR: Capture card not found.")
        return

    print("Green rectangle detection started.")
    print("Press Q to exit.")

    was_detected = False
    last_debug = 0

    try:
        while True:
            ret, frame = cap.read()

            if not ret:
                print("ERROR: Failed to capture frame.")
                break

            # Crop top-left corner
            cropped = frame[
                :CROP_HEIGHT,
                :CROP_WIDTH
            ].copy()

            # Convert to HSV
            hsv = cv2.cvtColor(
                cropped,
                cv2.COLOR_BGR2HSV
            )

            # Create green mask
            mask = cv2.inRange(
                hsv,
                LOWER_GREEN,
                UPPER_GREEN
            )

            # Close small gaps in green border
            kernel = np.ones((3, 3), np.uint8)

            mask = cv2.morphologyEx(
                mask,
                cv2.MORPH_CLOSE,
                kernel
            )

            # Find contours
            contours, _ = cv2.findContours(
                mask,
                cv2.RETR_EXTERNAL,
                cv2.CHAIN_APPROX_SIMPLE
            )

            detected = False
            best_coverage = 0.0
            best_box = None
            best_corners = 0

            for contour in contours:
                x, y, w, h = cv2.boundingRect(contour)

                # Filter by expected dimensions
                if not (MIN_WIDTH <= w <= MAX_WIDTH):
                    continue

                if not (MIN_HEIGHT <= h <= MAX_HEIGHT):
                    continue

                # Approximate contour shape
                perimeter = cv2.arcLength(
                    contour,
                    True
                )

                approx = cv2.approxPolyDP(
                    contour,
                    0.03 * perimeter,
                    True
                )

                corners = len(approx)

                # Calculate border coverage
                coverage = calculate_border_coverage(
                    mask, x, y, w, h
                )

                # Keep best candidate
                if coverage > best_coverage:
                    best_coverage = coverage
                    best_box = (x, y, w, h)
                    best_corners = corners

            # Check detection threshold
            if (
                best_box is not None
                and best_coverage >= MIN_BORDER_COVERAGE
            ):
                detected = True

                x, y, w, h = best_box

                # Trigger LED on new detection
                if not was_detected:
                    print(
                        "GREEN BOX DETECTED! "
                        f"Coverage: {best_coverage:.2f} | "
                        f"Corners: {best_corners}"
                    )

                    if on_detect:
                        on_detect()

                # Draw detection rectangle
                cv2.rectangle(
                    cropped,
                    (x, y),
                    (x + w, y + h),
                    (0, 255, 0),
                    2
                )

            was_detected = detected

            # Debug output every second
            now = time.monotonic()

            if now - last_debug >= 1:
                print(
                    f"Contours: {len(contours)} | "
                    f"Coverage: {best_coverage:.2f} | "
                    f"Corners: {best_corners} | "
                    f"Detected: {detected} | "
                    f"Box: {best_box}"
                )

                last_debug = now

            # Display detection status
            status = "DETECTED" if detected else "SEARCHING"

            cv2.putText(
                cropped,
                f"{status} {best_coverage:.2f}",
                (5, 110),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (0, 255, 0) if detected else (0, 0, 255),
                1
            )

            cv2.imshow("Capture Debug", cropped)
            cv2.imshow("Green Mask", mask)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    finally:
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    run_capture()
