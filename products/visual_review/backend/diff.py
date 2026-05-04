"""
Image comparison using pixelhog (Rust-accelerated).

Single decode via pixelhog.Comparison; reuses the decoded buffers across
diff_count, ssim, diff_image, thumbnail, and clusters without paying for
re-decode.
"""

from dataclasses import dataclass

from blake3 import blake3
from pixelhog import Comparison

from .diff_metadata import ClusterSummary, DiffCluster

THUMB_WIDTH = 200
THUMB_HEIGHT = 140

# Clustering parameters tuned for screenshot diffs. See pixelhog PR6_REVIEW
# for the rationale: dilation merges glyph fragments into region-level
# clusters; min_pixels + min_side filter sub-character noise; max_clusters
# caps at the rough UI legibility ceiling for bbox overlays. `total` on the
# stored summary preserves the true count when the cap kicks in.
CLUSTER_MIN_PIXELS = 16
CLUSTER_MIN_SIDE = 4
CLUSTER_DILATION = 4
CLUSTER_MAX = 20


@dataclass
class CompareResult:
    diff_image: bytes | None
    diff_hash: str
    diff_percentage: float  # 0.0 to 100.0 — fraction of pixels that differ
    diff_pixel_count: int
    ssim_score: float  # 0.0 to 1.0 — 1.0 = identical, lower = more different
    width: int
    height: int
    thumbnail: bytes | None
    thumbnail_hash: str
    size_mismatch: bool  # baseline and current have different dimensions
    cluster_summary: ClusterSummary | None  # None when not computed (size mismatch / no thumbnail-only mode)


def compare_images(
    baseline_bytes: bytes,
    current_bytes: bytes,
    threshold: float = 0.1,
    with_thumbnail: bool = True,
    with_clusters: bool = True,
) -> CompareResult:
    """Compare two PNG images: pixelmatch + SSIM + optional thumbnail + clusters.

    One decode of each PNG; subsequent ops reuse the decoded RGBA buffers.
    Clusters are skipped when sizes mismatch — the padded region dominates
    the diff and the clusters reduce to "the padding rectangle", not useful.
    """
    cmp = Comparison(baseline_bytes, current_bytes)

    diff_pixel_count = cmp.diff_count(threshold=threshold)
    ssim_score = cmp.ssim()
    diff_image = cmp.diff_image(threshold=threshold, alpha=0.1)
    thumbnail = cmp.current_thumbnail(width=THUMB_WIDTH, height=THUMB_HEIGHT) if with_thumbnail else None

    width = cmp.width
    height = cmp.height
    total_pixels = width * height
    diff_percentage = (diff_pixel_count / total_pixels * 100) if total_pixels > 0 else 0.0

    diff_hash = blake3(diff_image).hexdigest() if diff_image else ""
    thumbnail_hash = blake3(thumbnail).hexdigest() if thumbnail else ""

    cluster_summary: ClusterSummary | None = None
    if with_clusters and not cmp.size_mismatch and diff_pixel_count > 0:
        clusters_result = cmp.clusters(
            threshold=threshold,
            min_pixels=CLUSTER_MIN_PIXELS,
            min_side=CLUSTER_MIN_SIDE,
            dilation=CLUSTER_DILATION,
            max_clusters=CLUSTER_MAX,
        )
        cluster_summary = ClusterSummary(
            items=[
                DiffCluster(
                    bbox=(c.bbox.x, c.bbox.y, c.bbox.width, c.bbox.height),
                    px=c.pixel_count,
                    centroid=c.centroid,
                )
                for c in clusters_result.clusters
            ],
            total=clusters_result.total_clusters,
            truncated=clusters_result.truncated,
        )

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
        size_mismatch=cmp.size_mismatch,
        cluster_summary=cluster_summary,
    )
