"""
SSIM (Structural Similarity Index) computation for visual review.

Safety net for tall-page dilution: pixelmatch counts differing pixels as a
percentage of total image area, so a real UI change at the bottom of a long
screenshot can fall below the pixel threshold. SSIM evaluates structural
similarity in local windows, catching changes that affect few pixels but
produce a measurable perceptual shift.

Only called when pixelmatch classifies a snapshot as below-threshold.

Zero external dependencies beyond numpy and Pillow (both already required
by pixelmatch).
"""

from io import BytesIO

import numpy as np
from PIL import Image

# Standard SSIM constants (Wang et al., 2004)
_C1 = (0.01 * 255) ** 2
_C2 = (0.03 * 255) ** 2
_WIN_SIZE = 11


def _box_filter(arr: np.ndarray, size: int) -> np.ndarray:
    """2D box (mean) filter using cumulative sums. O(n) per axis regardless of window size."""
    # Pad to handle borders (reflect to match scipy.ndimage.uniform_filter default)
    pad = size // 2
    padded = np.pad(arr, pad, mode="reflect")

    # Cumsum along rows, then columns
    cs = np.cumsum(padded, axis=0)
    cs = cs[size:] - cs[:-size]
    cs = np.cumsum(cs, axis=1)
    cs = cs[:, size:] - cs[:, :-size]

    return cs / (size * size)


def _compute_ssim_map(baseline: np.ndarray, current: np.ndarray) -> np.ndarray:
    """Compute per-pixel SSIM map using 11x11 uniform windows."""
    baseline_f = baseline.astype(np.float64)
    current_f = current.astype(np.float64)

    mu1 = _box_filter(baseline_f, _WIN_SIZE)
    mu2 = _box_filter(current_f, _WIN_SIZE)

    mu1_sq = mu1 * mu1
    mu2_sq = mu2 * mu2
    mu1_mu2 = mu1 * mu2

    sigma1_sq = _box_filter(baseline_f * baseline_f, _WIN_SIZE) - mu1_sq
    sigma2_sq = _box_filter(current_f * current_f, _WIN_SIZE) - mu2_sq
    sigma12 = _box_filter(baseline_f * current_f, _WIN_SIZE) - mu1_mu2

    numerator = (2 * mu1_mu2 + _C1) * (2 * sigma12 + _C2)
    denominator = (mu1_sq + mu2_sq + _C1) * (sigma1_sq + sigma2_sq + _C2)

    return numerator / denominator


def _pad_grayscale(img: np.ndarray, height: int, width: int) -> np.ndarray:
    if img.shape == (height, width):
        return img
    result = np.zeros((height, width), dtype=img.dtype)
    result[: img.shape[0], : img.shape[1]] = img
    return result


def compute_ssim(baseline_bytes: bytes, current_bytes: bytes) -> float:
    """
    Compute mean SSIM between two PNG images.

    Converts to grayscale and computes windowed structural similarity
    (Wang et al., 2004) with 11x11 uniform windows, matching the standard
    used by jest-image-snapshot.

    Returns a score from 0.0 (completely different) to 1.0 (identical).
    """
    baseline = np.array(Image.open(BytesIO(baseline_bytes)).convert("L"))
    current = np.array(Image.open(BytesIO(current_bytes)).convert("L"))

    height = max(baseline.shape[0], current.shape[0])
    width = max(baseline.shape[1], current.shape[1])

    baseline = _pad_grayscale(baseline, height, width)
    current = _pad_grayscale(current, height, width)

    # Images smaller than the window can't be evaluated — fall back to
    # a simple global comparison so the caller still gets a usable score.
    if height < _WIN_SIZE or width < _WIN_SIZE:
        baseline_f = baseline.astype(np.float64)
        current_f = current.astype(np.float64)
        mu1, mu2 = baseline_f.mean(), current_f.mean()
        sigma1_sq, sigma2_sq = baseline_f.var(), current_f.var()
        sigma12 = ((baseline_f - mu1) * (current_f - mu2)).mean()
        numerator = (2 * mu1 * mu2 + _C1) * (2 * sigma12 + _C2)
        denominator = (mu1**2 + mu2**2 + _C1) * (sigma1_sq + sigma2_sq + _C2)
        return float(numerator / denominator)

    ssim_map = _compute_ssim_map(baseline, current)

    return float(ssim_map.mean())
