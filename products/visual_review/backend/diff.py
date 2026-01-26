"""
Image diff computation using Pillow.

Compares two images and generates a diff image highlighting differences.
"""

import hashlib
from dataclasses import dataclass
from io import BytesIO

from PIL import Image


@dataclass
class DiffResult:
    """Result of comparing two images."""

    diff_image: bytes  # PNG bytes of the diff visualization
    diff_hash: str  # SHA256 hash of the diff image
    diff_percentage: float  # 0.0 to 100.0
    diff_pixel_count: int
    width: int
    height: int


def compute_diff(baseline_bytes: bytes, current_bytes: bytes, threshold: int = 10) -> DiffResult:
    """
    Compare two PNG images and generate a diff visualization.

    Args:
        baseline_bytes: PNG bytes of the baseline image
        current_bytes: PNG bytes of the current image
        threshold: Per-channel difference threshold (0-255) to consider a pixel changed

    Returns:
        DiffResult with diff image and metrics
    """
    baseline = Image.open(BytesIO(baseline_bytes)).convert("RGBA")
    current = Image.open(BytesIO(current_bytes)).convert("RGBA")

    # Handle size differences - use larger dimensions
    width = max(baseline.width, current.width)
    height = max(baseline.height, current.height)

    # Pad images to same size if needed
    if baseline.size != (width, height):
        padded = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        padded.paste(baseline, (0, 0))
        baseline = padded

    if current.size != (width, height):
        padded = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        padded.paste(current, (0, 0))
        current = padded

    # Create diff image - use getpixel/putpixel for type safety
    diff_image = Image.new("RGBA", (width, height))

    diff_pixel_count = 0
    total_pixels = width * height

    for y in range(height):
        for x in range(width):
            bp: tuple[int, int, int, int] = baseline.getpixel((x, y))  # type: ignore[assignment]
            cp: tuple[int, int, int, int] = current.getpixel((x, y))  # type: ignore[assignment]

            # Check if pixels differ beyond threshold
            if _pixels_differ(bp, cp, threshold):
                diff_pixel_count += 1
                # Highlight difference: magenta overlay
                diff_image.putpixel((x, y), (255, 0, 255, 255))
            else:
                # Unchanged: show dimmed version of current
                r, g, b, a = cp
                diff_image.putpixel((x, y), (r // 3, g // 3, b // 3, a))

    # Calculate percentage
    diff_percentage = (diff_pixel_count / total_pixels * 100) if total_pixels > 0 else 0.0

    # Encode diff image to PNG
    output = BytesIO()
    diff_image.save(output, format="PNG", optimize=True)
    diff_bytes = output.getvalue()

    # Hash the diff image
    diff_hash = hashlib.sha256(diff_bytes).hexdigest()

    return DiffResult(
        diff_image=diff_bytes,
        diff_hash=diff_hash,
        diff_percentage=round(diff_percentage, 4),
        diff_pixel_count=diff_pixel_count,
        width=width,
        height=height,
    )


def _pixels_differ(p1: tuple[int, int, int, int], p2: tuple[int, int, int, int], threshold: int) -> bool:
    """Check if two RGBA pixels differ beyond threshold."""
    for i in range(4):
        if abs(p1[i] - p2[i]) > threshold:
            return True
    return False
