"""
Image comparison using pixelhog (Rust-accelerated).

Single-pass: pixelmatch diff, SSIM, and optional thumbnail in one decode.
"""

from dataclasses import dataclass

from blake3 import blake3
from pixelhog import compare as pixelhog_compare

THUMB_WIDTH = 200
THUMB_HEIGHT = 140


@dataclass
class CompareResult:
    diff_image: bytes | None
    diff_hash: str
    diff_percentage: float  # 0.0 to 100.0
    diff_pixel_count: int
    ssim_score: float
    width: int
    height: int
    thumbnail: bytes | None
    thumbnail_hash: str


def compare_images(
    baseline_bytes: bytes,
    current_bytes: bytes,
    threshold: float = 0.1,
    with_thumbnail: bool = True,
) -> CompareResult:
    """
    Compare two PNG images: pixelmatch diff, SSIM, and optional thumbnail.

    Single Rust decode pass via pixelhog.compare().
    """
    diff_pixel_count, ssim_score, width, height, diff_image, thumbnail = pixelhog_compare(
        baseline_bytes,
        current_bytes,
        threshold=threshold,
        alpha=0.1,
        return_diff=True,
        thumbnail_width=THUMB_WIDTH if with_thumbnail else None,
        thumbnail_height=THUMB_HEIGHT if with_thumbnail else None,
    )

    total_pixels = width * height
    diff_percentage = (diff_pixel_count / total_pixels * 100) if total_pixels > 0 else 0.0

    diff_hash = blake3(diff_image).hexdigest() if diff_image else ""
    thumbnail_hash = blake3(thumbnail).hexdigest() if thumbnail else ""

    return CompareResult(
        diff_image=diff_image,
        diff_hash=diff_hash,
        diff_percentage=round(diff_percentage, 4),
        diff_pixel_count=diff_pixel_count,
        ssim_score=ssim_score,
        width=width,
        height=height,
        thumbnail=thumbnail,
        thumbnail_hash=thumbnail_hash,
    )
