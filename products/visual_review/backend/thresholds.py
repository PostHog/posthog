"""Diff classification thresholds and per-story override resolution.

Two-tier classification:

1. **Pixel diff ratio** — fast path for obvious changes. Snapshots above this are
   immediately classified as CHANGED.
2. **SSIM perceptual threshold** — safety net for tall-page dilution. A real UI
   change at the bottom of a long screenshot affects few pixels but produces a
   measurable structural shift that SSIM catches.

Only when both are below threshold is the snapshot reclassified as UNCHANGED.

Both thresholds are global defaults, overridable per story via
`StoryThresholdOverride` so a story with known rendering movement can relax the
tier that keeps tripping.

Kept free of heavy imports (no pixelhog / diff engine) so the request path — the
snapshot mapper that surfaces effective thresholds to the UI — can import it
without pulling in the comparison machinery.
"""

from .identifiers import story_stem
from .models import StoryThresholdOverride

PIXEL_DIFF_THRESHOLD_PERCENT = 2.5
SSIM_DISSIMILARITY_THRESHOLD = 0.01  # 1% structural difference


def effective_thresholds(
    identifier: str, overrides: dict[str, StoryThresholdOverride]
) -> tuple[float, float, bool, bool]:
    """Resolve the thresholds that apply to a snapshot, honoring per-story overrides.

    Returns `(pixel_threshold, ssim_threshold, pixel_overridden, ssim_overridden)`.
    A null column on the override means "fall back to the global default" — each
    tier is independent, so a story can override one without touching the other.
    """
    override = overrides.get(story_stem(identifier))
    pixel_threshold = PIXEL_DIFF_THRESHOLD_PERCENT
    ssim_threshold = SSIM_DISSIMILARITY_THRESHOLD
    pixel_overridden = False
    ssim_overridden = False
    if override is not None and override.pixel_threshold_percent is not None:
        pixel_threshold = override.pixel_threshold_percent
        pixel_overridden = True
    if override is not None and override.ssim_dissimilarity_threshold is not None:
        ssim_threshold = override.ssim_dissimilarity_threshold
        ssim_overridden = True
    return pixel_threshold, ssim_threshold, pixel_overridden, ssim_overridden
