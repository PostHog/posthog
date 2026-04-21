"""
Image diff computation using pixelhog (Rust-accelerated pixelmatch).

Compares two images pixel-by-pixel with anti-aliasing detection,
generates a diff visualization, and reports diff metrics.
"""

from dataclasses import dataclass

from blake3 import blake3
from pixelhog import diff as pixelhog_diff


@dataclass
class DiffResult:
    """Result of comparing two images."""

    diff_image: bytes  # PNG bytes of the diff visualization
    diff_hash: str  # BLAKE3 hash of the diff image
    diff_percentage: float  # 0.0 to 100.0
    diff_pixel_count: int
    width: int
    height: int


def compute_diff(baseline_bytes: bytes, current_bytes: bytes, threshold: float = 0.1) -> DiffResult:
    """
    Compare two PNG images and generate a diff visualization.

    Uses pixelhog for accurate comparison with anti-aliasing detection.
    Smaller images are padded to the larger dimensions internally.

    Args:
        baseline_bytes: PNG bytes of the baseline image
        current_bytes: PNG bytes of the current image
        threshold: color distance threshold (0-1), default 0.1

    Returns:
        DiffResult with diff image and metrics
    """
    diff_png, diff_pixel_count, width, height = pixelhog_diff(
        baseline_bytes,
        current_bytes,
        threshold=threshold,
        alpha=0.1,
    )

    total_pixels = width * height
    diff_percentage = (diff_pixel_count / total_pixels * 100) if total_pixels > 0 else 0.0

    diff_hash = blake3(diff_png).hexdigest()

    return DiffResult(
        diff_image=diff_png,
        diff_hash=diff_hash,
        diff_percentage=round(diff_percentage, 4),
        diff_pixel_count=diff_pixel_count,
        width=width,
        height=height,
    )
