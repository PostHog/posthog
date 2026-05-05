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

# Distance in pixels under which clusters that are aligned on one axis
# (e.g. stacked rows of a list) get merged. Pixelhog's CCL produces tight
# per-shape clusters; for screenshot diffs "shapes that are visually
# adjacent and aligned" usually mean "the same list/section that shifted
# as a whole". Without this, a 7-row list-shift surfaces as 7 individual
# bboxes with heavy visual overlap.
CLUSTER_MERGE_PERPENDICULAR_GAP_PX = 60
# Minimum overlap on the merge axis (as a fraction of the smaller bbox's
# extent) before two bboxes are considered aligned. 0.5 = at least half
# the smaller dimension must overlap.
CLUSTER_MERGE_MIN_OVERLAP_RATIO = 0.5

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
    When sizes differ, pixelhog pads to the largest dimensions and runs
    every metric against the padded buffers — including clusters. The
    padded region surfaces as a cluster of its own, which is the right
    answer ("here's the new content area") rather than something to hide.
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
    if with_clusters and diff_pixel_count > 0:
        clusters_result = cmp.clusters(
            threshold=threshold,
            min_pixels=CLUSTER_MIN_PIXELS,
            min_side=CLUSTER_MIN_SIDE,
            dilation=CLUSTER_DILATION,
            max_clusters=CLUSTER_MAX,
        )
        merged = _merge_aligned_clusters(
            [
                DiffCluster(
                    bbox=(c.bbox.x, c.bbox.y, c.bbox.width, c.bbox.height),
                    px=c.pixel_count,
                    centroid=c.centroid,
                )
                for c in clusters_result.clusters
            ]
        )
        cluster_summary = ClusterSummary(
            items=merged,
            total=len(merged),
            # Pixelhog's `truncated` reflects the pre-merge count cap.
            # Once we've merged, that flag's bookkeeping no longer
            # corresponds to what's in `items`, so drop it.
            truncated=False,
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


def _bboxes_should_merge(
    a: DiffCluster,
    b: DiffCluster,
    max_perpendicular_gap: int = CLUSTER_MERGE_PERPENDICULAR_GAP_PX,
    min_overlap_ratio: float = CLUSTER_MERGE_MIN_OVERLAP_RATIO,
) -> bool:
    """Two bboxes should merge if they're already overlapping, or if they're
    aligned on one axis (≥ `min_overlap_ratio` overlap on that axis) and
    within `max_perpendicular_gap` pixels on the other.

    The alignment check is what catches the "list shifted" case: rows that
    share a horizontal extent and stack vertically. Without it, plain
    Manhattan-distance merging would also collapse unrelated regions on
    opposite sides of the screen that happened to be a few pixels apart.
    """
    ax, ay, aw, ah = a.bbox
    bx, by, bw, bh = b.bbox
    ax2, ay2 = ax + aw, ay + ah
    bx2, by2 = bx + bw, by + bh

    x_overlap = max(0, min(ax2, bx2) - max(ax, bx))
    y_overlap = max(0, min(ay2, by2) - max(ay, by))

    if x_overlap > 0 and y_overlap > 0:
        return True

    # Same column: aligned horizontally, stacked vertically.
    x_min = min(aw, bw)
    if x_min > 0 and x_overlap / x_min >= min_overlap_ratio:
        y_gap = max(ay, by) - min(ay2, by2)
        if y_gap <= max_perpendicular_gap:
            return True

    # Same row: aligned vertically, side by side horizontally.
    y_min = min(ah, bh)
    if y_min > 0 and y_overlap / y_min >= min_overlap_ratio:
        x_gap = max(ax, bx) - min(ax2, bx2)
        if x_gap <= max_perpendicular_gap:
            return True

    return False


def _merge_two_clusters(a: DiffCluster, b: DiffCluster) -> DiffCluster:
    ax, ay, aw, ah = a.bbox
    bx, by, bw, bh = b.bbox
    nx = min(ax, bx)
    ny = min(ay, by)
    nx2 = max(ax + aw, bx + bw)
    ny2 = max(ay + ah, by + bh)
    total = a.px + b.px
    if total > 0:
        cx = (a.centroid[0] * a.px + b.centroid[0] * b.px) / total
        cy = (a.centroid[1] * a.px + b.centroid[1] * b.px) / total
    else:
        cx = (a.centroid[0] + b.centroid[0]) / 2
        cy = (a.centroid[1] + b.centroid[1]) / 2
    return DiffCluster(bbox=(nx, ny, nx2 - nx, ny2 - ny), px=total, centroid=(cx, cy))


def _merge_aligned_clusters(clusters: list[DiffCluster]) -> list[DiffCluster]:
    """Iteratively merge any two clusters whose bboxes are aligned and close.

    O(N^2) per pass, runs until no more merges. N is bounded by
    `CLUSTER_MAX` (currently 20) so the cost is negligible.
    """
    items = list(clusters)
    while True:
        merged_any = False
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                if _bboxes_should_merge(items[i], items[j]):
                    items[i] = _merge_two_clusters(items[i], items[j])
                    items.pop(j)
                    merged_any = True
                    break
            if merged_any:
                break
        if not merged_any:
            break
    # Re-rank by pixel count so the largest regions stay first — the
    # frontend caps at top-N and we want the most informative ones.
    items.sort(key=lambda c: -c.px)
    return items
