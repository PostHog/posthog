"""
Image comparison using pixelhog (Rust-accelerated).

Single decode via pixelhog.Comparison; reuses the decoded buffers across
diff_count, ssim, diff_image, thumbnail, and clusters without paying for
re-decode.
"""

from dataclasses import dataclass

from blake3 import blake3
from pixelhog import ClustersResult, Comparison, RowAlignment

from .diff_metadata import ClusterSummary, DiffCluster, RowShift, ShiftBand

# Aligned-bbox merge tunables passed through to pixelhog's clusters().
# Catches the "list shifted vertically" pattern where every row of a
# list becomes its own cluster despite being a single semantic change.
# Validated against ~20k real master snapshot diffs: 62% collapse to a
# single regional cluster, mean drops 8.33 -> 1.79 clusters.
CLUSTER_MERGE_GAP_PX = 60
CLUSTER_MERGE_OVERLAP_RATIO = 0.5

THUMB_WIDTH = 200
THUMB_HEIGHT = 140

# Clustering parameters tuned for screenshot diffs. See pixelhog PR6_REVIEW
# for the rationale: dilation merges glyph fragments into region-level
# clusters; min_pixels + min_side filter sub-character noise; max_clusters
# caps at the rough UI legibility ceiling for bbox overlays. `total` on the
# stored summary preserves the true count when the cap kicks in.
#
# Dilation tuning: 8 closes ~16px gaps, which is the common spacing
# between text rows in a UI list (line height ~20px + ~13px gap). At
# dilation=4 a list-shift diff exploded into one cluster per text row
# plus one per separator; bumping to 8 collapses those into a single
# regional cluster covering the list area, which is what humans
# actually mean when they say "the list shifted".
CLUSTER_MIN_PIXELS = 16
CLUSTER_MIN_SIDE = 4
CLUSTER_DILATION = 8
CLUSTER_MAX = 20


@dataclass
class CompareResult:
    diff_image: bytes | None
    diff_hash: str
    diff_percentage: float  # 0.0 to 100.0 — fraction of pixels that differ
    diff_pixel_count: int
    ssim_score: float  # 0.0 to 1.0 — 1.0 = identical, lower = more different
    # Dimensions of `diff_image`, which is the padded size for a naive diff and
    # the current image's own size for an aligned one. The percentages above
    # are always measured over the padded size.
    width: int
    height: int
    thumbnail: bytes | None
    thumbnail_hash: str
    size_mismatch: bool  # baseline and current have different dimensions
    cluster_summary: ClusterSummary | None  # None when not computed (size mismatch / no thumbnail-only mode)
    # Metrics measured after row alignment paired the rows that exist in both
    # images. They fall back to the naive numbers above when `row_shift` is
    # None, so a caller that always stores the aligned numbers keeps the
    # unaligned behavior for free.
    aligned_diff_pixel_count: int
    aligned_diff_percentage: float
    aligned_ssim_score: float
    # None when pixelhog could not align the pair, which is what happens once
    # the two images differ by more than the alignment budget.
    row_shift: RowShift | None


def _to_cluster_summary(clusters_result: ClustersResult) -> ClusterSummary:
    return ClusterSummary(
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


def _inserted_band_pixels(alignment: RowAlignment, width: int) -> int:
    """Count the pixels of the rows the current image gained.

    `residual_count` covers only rows present in both images, so an inserted
    band contributes nothing to it. A band is new content, so it has to be
    counted somewhere; charging it a full row of pixels keeps a tall inserted
    block above the pixel threshold instead of hiding it.
    """
    return sum(band.rows * width for band in alignment.bands if band.kind == "inserted")


def compare_images(
    baseline_bytes: bytes,
    current_bytes: bytes,
    threshold: float = 0.1,
    with_thumbnail: bool = True,
    with_clusters: bool = True,
) -> CompareResult:
    """Compare two PNG images: pixelmatch + SSIM + optional thumbnail + clusters.

    One decode of each PNG; subsequent ops reuse the decoded RGBA buffers.
    When sizes differ, pixelhog pads to the largest dimensions and runs
    every metric against the padded buffers — including clusters. The
    padded region surfaces as a cluster of its own, which is the right
    answer ("here's the new content area") rather than something to hide.

    Row alignment runs on top of that. When it succeeds, the diff image and
    the clusters describe the residual instead of the whole page below a
    shift, and the aligned metrics measure what actually changed. The naive
    metrics stay on the result so a caller can still see what the shift cost
    without alignment.
    """
    cmp = Comparison(baseline_bytes, current_bytes)

    diff_pixel_count = cmp.diff_count(threshold=threshold)
    ssim_score = cmp.ssim()
    thumbnail = cmp.current_thumbnail(width=THUMB_WIDTH, height=THUMB_HEIGHT) if with_thumbnail else None

    width = cmp.width
    height = cmp.height
    total_pixels = width * height
    diff_percentage = (diff_pixel_count / total_pixels * 100) if total_pixels > 0 else 0.0

    alignment = cmp.row_alignment(threshold=threshold)
    row_shift: RowShift | None = None
    aligned_diff_pixel_count = diff_pixel_count
    aligned_diff_percentage = diff_percentage
    aligned_ssim_score = ssim_score
    # Dimensions of the diff image the result carries, which is what the diff
    # artifact row records and what the frontend scales its overlays by.
    diff_width, diff_height = width, height
    if alignment.aligned:
        aligned_diff_pixel_count = alignment.residual_count + _inserted_band_pixels(alignment, width)
        aligned_diff_percentage = (aligned_diff_pixel_count / total_pixels * 100) if total_pixels > 0 else 0.0
        aligned_ssim_score = cmp.aligned_ssim(alignment)
        residual_percentage = (alignment.residual_count / total_pixels * 100) if total_pixels > 0 else 0.0
        row_shift = RowShift(
            inserted_rows=alignment.inserted_rows,
            deleted_rows=alignment.deleted_rows,
            changed_rows=alignment.changed_rows,
            residual_pixel_count=alignment.residual_count,
            residual_percentage=round(residual_percentage, 4),
            raw_diff_percentage=round(diff_percentage, 4),
            raw_ssim_score=ssim_score,
            bands=[ShiftBand(y=b.y, rows=b.rows, kind=b.kind) for b in alignment.bands],
        )
        diff_image = cmp.aligned_diff_image(alignment, threshold=threshold, alpha=0.1)
        # The aligned diff image is drawn in current-image coordinates, so when
        # the baseline was the taller of the two it is shorter than the padded
        # buffers every metric above was measured against. The percentages stay
        # over the padded total; only the image dimensions follow the image.
        diff_width, diff_height = cmp.current_size
    else:
        diff_image = cmp.diff_image(threshold=threshold, alpha=0.1)

    diff_hash = blake3(diff_image).hexdigest() if diff_image else ""
    thumbnail_hash = blake3(thumbnail).hexdigest() if thumbnail else ""

    cluster_summary: ClusterSummary | None = None
    if with_clusters and diff_pixel_count > 0:
        if row_shift is not None:
            clusters_result = cmp.aligned_clusters(
                alignment,
                threshold=threshold,
                min_pixels=CLUSTER_MIN_PIXELS,
                min_side=CLUSTER_MIN_SIDE,
                dilation=CLUSTER_DILATION,
                max_clusters=CLUSTER_MAX,
                merge_gap=CLUSTER_MERGE_GAP_PX,
                merge_overlap=CLUSTER_MERGE_OVERLAP_RATIO,
            )
        else:
            clusters_result = cmp.clusters(
                threshold=threshold,
                min_pixels=CLUSTER_MIN_PIXELS,
                min_side=CLUSTER_MIN_SIDE,
                dilation=CLUSTER_DILATION,
                max_clusters=CLUSTER_MAX,
                merge_gap=CLUSTER_MERGE_GAP_PX,
                merge_overlap=CLUSTER_MERGE_OVERLAP_RATIO,
            )
        cluster_summary = _to_cluster_summary(clusters_result)

    return CompareResult(
        diff_image=diff_image,
        diff_hash=diff_hash,
        diff_percentage=round(diff_percentage, 4),
        diff_pixel_count=diff_pixel_count,
        ssim_score=ssim_score,
        width=diff_width,
        height=diff_height,
        thumbnail=thumbnail,
        thumbnail_hash=thumbnail_hash,
        size_mismatch=cmp.size_mismatch,
        cluster_summary=cluster_summary,
        aligned_diff_pixel_count=aligned_diff_pixel_count,
        aligned_diff_percentage=round(aligned_diff_percentage, 4),
        aligned_ssim_score=aligned_ssim_score,
        row_shift=row_shift,
    )
