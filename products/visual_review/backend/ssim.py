"""
SSIM (Structural Similarity Index) computation for visual review.

Safety net for tall-page dilution: pixelmatch counts differing pixels as a
percentage of total image area, so a real UI change at the bottom of a long
screenshot can fall below the pixel threshold. SSIM evaluates structural
similarity in local windows, catching changes that affect few pixels but
produce a measurable perceptual shift.

Only called when the pixel-based diff classifies a snapshot as below-threshold.

Uses pixelhog (Rust) for fast 11x11 windowed SSIM with reflect padding.
"""

from pixelhog import ssim


def compute_ssim(baseline_bytes: bytes, current_bytes: bytes) -> float:
    """
    Compute mean SSIM between two PNG images.

    Uses 11x11 uniform windows with reflect padding, matching the standard
    used by jest-image-snapshot. Smaller images are padded to the larger
    dimensions internally.

    Returns a score from 0.0 (completely different) to 1.0 (identical).
    """
    return ssim(baseline_bytes, current_bytes)
