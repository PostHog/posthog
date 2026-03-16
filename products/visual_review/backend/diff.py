"""
Image diff computation using pixelmatch.

Compares two images pixel-by-pixel with anti-aliasing detection,
generates a diff visualization, and reports diff metrics.
"""

from dataclasses import dataclass
from io import BytesIO

from blake3 import blake3
from PIL import Image
from pixelmatch.contrib.PIL import pixelmatch


@dataclass
class DiffResult:
    """Result of comparing two images."""

    diff_image: bytes  # PNG bytes of the diff visualization
    diff_hash: str  # BLAKE3 hash of the diff image
    diff_percentage: float  # 0.0 to 100.0
    diff_pixel_count: int
    width: int
    height: int


def _pad_to_size(img: Image.Image, width: int, height: int) -> Image.Image:
    if img.size == (width, height):
        return img
    padded = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    padded.paste(img, (0, 0))
    return padded


def compute_diff(baseline_bytes: bytes, current_bytes: bytes, threshold: float = 0.1) -> DiffResult:
    """
    Compare two PNG images and generate a diff visualization.

    Uses pixelmatch for accurate comparison with anti-aliasing detection.

    Args:
        baseline_bytes: PNG bytes of the baseline image
        current_bytes: PNG bytes of the current image
        threshold: pixelmatch color distance threshold (0-1), default 0.1

    Returns:
        DiffResult with diff image and metrics
    """
    baseline = Image.open(BytesIO(baseline_bytes)).convert("RGBA")
    current = Image.open(BytesIO(current_bytes)).convert("RGBA")

    width = max(baseline.width, current.width)
    height = max(baseline.height, current.height)

    baseline = _pad_to_size(baseline, width, height)
    current = _pad_to_size(current, width, height)

    diff_output = Image.new("RGBA", (width, height))

    diff_pixel_count = pixelmatch(
        baseline,
        current,
        output=diff_output,
        threshold=threshold,
        alpha=0.1,
    )

    total_pixels = width * height
    diff_percentage = (diff_pixel_count / total_pixels * 100) if total_pixels > 0 else 0.0

    output = BytesIO()
    diff_output.save(output, format="PNG", optimize=True)
    diff_bytes = output.getvalue()

    diff_hash = blake3(diff_bytes).hexdigest()

    return DiffResult(
        diff_image=diff_bytes,
        diff_hash=diff_hash,
        diff_percentage=round(diff_percentage, 4),
        diff_pixel_count=diff_pixel_count,
        width=width,
        height=height,
    )
