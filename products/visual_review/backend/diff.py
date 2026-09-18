"""
Image comparison using pixelhog (Rust-accelerated).

Single decode via pixelhog.Comparison; reuses the decoded buffers across
diff_count, ssim, diff_image, thumbnail, and clusters without paying for
re-decode.
"""

import io
from typing import Any

from blake3 import blake3
from PIL import Image
from pixelhog import ClustersResult, Comparison, RowAlignment

from posthog.dataclasses import frozen

from .diff_metadata import ClusterSummary, DiffCluster, RowShift, ShiftBand
from .facade.contracts import SHIFT_ABSORB_MAX_ROWS

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

# Row alignment costs up to rows x edit budget, and the upload pixel cap alone
# still admits a one pixel wide image with tens of millions of rows. Real pages
# top out well under this, so past it the pair keeps the naive diff.
ALIGN_MAX_ROWS = 32_768
# The relocation check decodes each image a second time, one after the other,
# and only for a shift within the absorb cap. Past this many pixels that is
# too much memory next to pixelhog's own buffers, so the check is skipped and
# a shift with both inserts and deletes is treated as moved content, which
# sends it to a reviewer instead of absorbing it.
RELOCATION_CHECK_MAX_PIXELS = 16_000_000


@frozen
class CompareResult:
    diff_image: bytes | None
    diff_hash: str
    diff_percentage: float  # 0.0 to 100.0 — fraction of pixels that differ
    diff_pixel_count: int
    # 0.0 to 1.0 — 1.0 = identical, lower = more different. Measured over the
    # matched rows when the pair aligned, so it is the effective score the
    # classifier reads either way.
    ssim_score: float
    # Dimensions of `diff_image`, which is the padded size for a naive diff and
    # the current image's own size for an aligned one. The percentages above
    # are always measured over the padded size.
    width: int
    height: int
    thumbnail: bytes | None
    thumbnail_hash: str
    size_mismatch: bool  # baseline and current have different dimensions
    cluster_summary: ClusterSummary | None  # None when not computed (size mismatch / no thumbnail-only mode)
    # What still differs once row alignment paired the rows that exist in
    # both images: the residual plus the rows the shift added or removed, so
    # a band of new rows is a change the size of its own area. Falls back to
    # the naive numbers above when `row_shift` is None, so a caller that
    # always stores these keeps the unaligned behavior for free.
    aligned_diff_pixel_count: int
    aligned_diff_percentage: float
    # None when there was nothing to align, or when pixelhog could not align
    # the pair because the two images differ by more than its budget.
    row_shift: RowShift | None


def _relocated_rows(baseline_bytes: bytes, current_bytes: bytes, alignment: RowAlignment, total_pixels: int) -> int:
    """Inserted rows whose pixels equal a deleted row's: content that moved, not padding that appeared.

    An element that moved stood out somewhere in the interior: the band
    differs from the rows above and below it, in the current image where it
    landed or in the baseline where it left. Padding that grew blends into a
    neighbor, and padding that a page shift exposed at one edge while it
    cropped the other has no interior side, so neither counts. The images
    are decoded again for this, one at a time, and only for a shift small
    enough that the answer can still absorb it.
    """
    deleted = [seg for seg in alignment.segments if seg.kind == "delete"]
    inserted = [seg for seg in alignment.segments if seg.kind == "insert"]
    if not deleted or not inserted:
        return 0
    if max(alignment.inserted_rows, alignment.deleted_rows) > SHIFT_ABSORB_MAX_ROWS:
        return 0
    if total_pixels > RELOCATION_CHECK_MAX_PIXELS:
        return sum(seg.len for seg in inserted)

    def row(image: Image.Image, y: int) -> bytes:
        return image.crop((0, y, image.width, y + 1)).tobytes()

    def stands_out(image: Image.Image, start: int, end: int, band: list[bytes]) -> bool:
        if start == 0 or end >= image.height:
            return False
        return row(image, start - 1) != band[0] and row(image, end) != band[-1]

    baseline = Image.open(io.BytesIO(baseline_bytes)).convert("RGBA")
    # Row pixels -> whether that deleted band stood out where it was.
    deleted_rows: dict[bytes, bool] = {}
    for seg in deleted:
        start, end = seg.baseline_start, seg.baseline_start + seg.len
        band = [row(baseline, y) for y in range(start, end)]
        stood_out = stands_out(baseline, start, end, band)
        for pixels in band:
            deleted_rows[pixels] = deleted_rows.get(pixels, False) or stood_out
    del baseline

    current = Image.open(io.BytesIO(current_bytes)).convert("RGBA")
    relocated = 0
    for seg in inserted:
        start, end = seg.current_start, seg.current_start + seg.len
        band = [row(current, y) for y in range(start, end)]
        if any(pixels not in deleted_rows for pixels in band):
            continue
        if stands_out(current, start, end, band) or any(deleted_rows[pixels] for pixels in band):
            relocated += seg.len
    return relocated


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

    Row alignment runs on top of that. When it succeeds, the diff image, the
    clusters and the SSIM describe the residual instead of the whole page
    below a shift, and the shift itself is reported separately as a row
    count. The naive pixel numbers stay on the result so a caller can still
    see what the shift would have cost without alignment.
    """
    cmp = Comparison(baseline_bytes, current_bytes)

    diff_pixel_count = cmp.diff_count(threshold=threshold)
    thumbnail = cmp.current_thumbnail(width=THUMB_WIDTH, height=THUMB_HEIGHT) if with_thumbnail else None

    width = cmp.width
    height = cmp.height
    total_pixels = width * height
    diff_percentage = (diff_pixel_count / total_pixels * 100) if total_pixels > 0 else 0.0

    # Nothing to align when no pixel differs, which is also true of a pair
    # that only differs in how its PNG was encoded.
    alignment: RowAlignment | None = None
    if 0 < diff_pixel_count and height <= ALIGN_MAX_ROWS:
        alignment = cmp.row_alignment(threshold=threshold)
    aligned = alignment is not None and alignment.aligned

    row_shift: RowShift | None = None
    aligned_diff_pixel_count = diff_pixel_count
    aligned_diff_percentage = diff_percentage
    # Dimensions of the diff image the result carries, which is what the diff
    # artifact row records and what the frontend scales its overlays by.
    diff_width, diff_height = width, height
    if alignment is not None and aligned:
        # The rows a shift added or removed have no counterpart, so the residual
        # does not see them. They still are a change the size of their area:
        # two rows on a tall page is nothing, two rows on a small component is
        # a bar across it. A same-height move shows as both an insert and a
        # delete of the same rows, so the larger side is the area, not the sum.
        band_pixel_count = max(alignment.inserted_rows, alignment.deleted_rows) * width
        aligned_diff_pixel_count = alignment.residual_count + band_pixel_count
        aligned_diff_percentage = (aligned_diff_pixel_count / total_pixels * 100) if total_pixels > 0 else 0.0
        residual_percentage = (alignment.residual_count / total_pixels * 100) if total_pixels > 0 else 0.0
        ssim_score = cmp.aligned_ssim(alignment)
        row_shift = RowShift(
            inserted_rows=alignment.inserted_rows,
            deleted_rows=alignment.deleted_rows,
            changed_rows=alignment.changed_rows,
            residual_pixel_count=alignment.residual_count,
            relocated_rows=_relocated_rows(baseline_bytes, current_bytes, alignment, total_pixels),
            residual_percentage=round(residual_percentage, 4),
            raw_diff_percentage=round(diff_percentage, 4),
            bands=[ShiftBand(y=b.y, rows=b.rows, kind=b.kind) for b in alignment.bands],
        )
        diff_image = cmp.aligned_diff_image(alignment, threshold=threshold, alpha=0.1)
        # The aligned diff image is drawn in current-image coordinates, so when
        # the baseline was the taller of the two it is shorter than the padded
        # buffers every metric above was measured against. The percentages stay
        # over the padded total; only the image dimensions follow the image.
        diff_width, diff_height = cmp.current_size
    else:
        ssim_score = cmp.ssim()
        diff_image = cmp.diff_image(threshold=threshold, alpha=0.1)

    diff_hash = blake3(diff_image).hexdigest() if diff_image else ""
    thumbnail_hash = blake3(thumbnail).hexdigest() if thumbnail else ""

    # Typed loosely on purpose: the tunables are int and float together, so a
    # narrower value type makes the ** expansion fail against pixelhog's
    # per-parameter types.
    cluster_kwargs: dict[str, Any] = {
        "threshold": threshold,
        "min_pixels": CLUSTER_MIN_PIXELS,
        "min_side": CLUSTER_MIN_SIDE,
        "dilation": CLUSTER_DILATION,
        "max_clusters": CLUSTER_MAX,
        "merge_gap": CLUSTER_MERGE_GAP_PX,
        "merge_overlap": CLUSTER_MERGE_OVERLAP_RATIO,
    }
    cluster_summary: ClusterSummary | None = None
    has_pixels_to_cluster = aligned_diff_pixel_count > 0 if aligned else diff_pixel_count > 0
    if with_clusters and has_pixels_to_cluster:
        clusters_result = (
            cmp.aligned_clusters(alignment, **cluster_kwargs)
            if alignment is not None and aligned
            else cmp.clusters(**cluster_kwargs)
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
        row_shift=row_shift,
    )
