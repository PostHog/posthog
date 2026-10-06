"""
Diff processing and classification for visual review.

Uses pixelhog.compare() for single-pass pixelmatch + SSIM + thumbnail.
Classifies snapshots as genuinely changed or rendering noise.

Called by the Celery task; all business logic lives here.
"""

from uuid import UUID

from django.db.models import Q

import structlog
from blake3 import blake3
from pixelhog import thumbnail as pixelhog_thumbnail

from .db import WRITER_DB
from .diff import THUMB_HEIGHT, THUMB_WIDTH, CompareResult, compare_images
from .diff_metadata import DiffMetadata
from .facade.contracts import PIXEL_DIFF_THRESHOLD_PERCENT, SHIFT_ABSORB_MAX_ROWS, SSIM_DISSIMILARITY_THRESHOLD
from .facade.enums import ChangeKind, ClassificationReason, SnapshotResult, ToleratedReason
from .models import Artifact, RunSnapshot, ToleratedHash

logger = structlog.get_logger(__name__)


def classify_compare_result(result: CompareResult) -> ChangeKind | None:
    """Classify a compare result into a ChangeKind, or None for unchanged.

    Pure function — no DB, no side effects — so tests can drive every
    classification path without spinning up a snapshot row. The same logic
    drives `_diff_snapshot` below; keeping it here means the production
    branch and the tests can't drift.

    When the pair aligned, the pixel tier reads the residual first and the
    area of the rows the shift added or removed after the cap, and
    `ssim_score` is already measured over the matched rows, so a page that
    only moved down is judged on what changed rather than on everything the
    shift dragged along. A shift taller than the absorb cap is its own kind, because moving
    a block is a change a reviewer can act on even when the content in it is
    identical. So is a thin element that moved somewhere else on the page:
    its rows show up as an insert whose pixels equal a delete's, which the
    counts alone would read as a tiny shift.

    Size mismatch is *not* a kind — pixelhog pads to the largest dims and
    we still get a real pixel/SSIM answer over that padded image. The fact
    that sizes differed is recorded separately on `DiffMetadata`.
    """
    shift = result.row_shift
    residual_percentage = shift.residual_percentage if shift else result.diff_percentage
    shifted_rows = shift.shifted_rows if shift else 0

    # Content that changed inside the matched rows is a pixel change no matter
    # what moved. A move past the cap is a layout change even when its band
    # alone covers a lot of the page, which is why the band's area is judged
    # only after that: it decides whether a small move on a small component
    # is a bar across it or noise.
    if residual_percentage >= PIXEL_DIFF_THRESHOLD_PERCENT:
        return ChangeKind.PIXEL
    if shifted_rows > SHIFT_ABSORB_MAX_ROWS or (shift is not None and shift.relocated_rows > 0):
        return ChangeKind.LAYOUT
    if result.aligned_diff_percentage >= PIXEL_DIFF_THRESHOLD_PERCENT:
        return ChangeKind.PIXEL
    if (1.0 - result.ssim_score) >= SSIM_DISSIMILARITY_THRESHOLD:
        return ChangeKind.STRUCTURAL
    return None


def _store_thumbnail(snapshot: RunSnapshot, result: CompareResult) -> None:
    """Store the thumbnail artifact and link it to the current artifact."""
    from .logic import artifact_store

    artifact = snapshot.current_artifact
    if artifact is None or artifact.thumbnail_id is not None:
        return
    if not result.thumbnail:
        return

    thumb_artifact = artifact_store.write_artifact_bytes(
        repo_id=snapshot.run.repo_id,
        content_hash=result.thumbnail_hash,
        content=result.thumbnail,
        width=THUMB_WIDTH,
        height=THUMB_HEIGHT,
        team_id=snapshot.team_id,
    )

    artifact.thumbnail = thumb_artifact
    artifact.save(update_fields=["thumbnail"])


def _write_diff_artifact(snapshot: RunSnapshot, result: CompareResult) -> Artifact:
    """Upload the diff image and return the artifact row pointing at it."""
    from .logic import artifact_store

    assert result.diff_image is not None
    return artifact_store.write_artifact_bytes(
        repo_id=snapshot.run.repo_id,
        content_hash=result.diff_hash,
        content=result.diff_image,
        width=result.width,
        height=result.height,
        team_id=snapshot.team_id,
    )


def _diff_metadata(result: CompareResult) -> DiffMetadata:
    """The metadata block both storage paths write."""
    return DiffMetadata(
        cluster_summary=result.cluster_summary,
        size_mismatch=result.size_mismatch,
        row_shift=result.row_shift,
    )


def _store_diff(
    snapshot: RunSnapshot,
    result: CompareResult,
    change_kind: ChangeKind,
) -> None:
    """Upload diff artifact and update snapshot metrics + classification."""
    from .logic import snapshot_diffs

    if not result.diff_image:
        return

    # The aligned metrics equal the naive ones when the pair could not be
    # aligned, so this stores the honest cost of the change either way.
    snapshot_diffs.update_snapshot_diff(
        snapshot_id=snapshot.id,
        diff_artifact=_write_diff_artifact(snapshot, result),
        diff_percentage=result.aligned_diff_percentage,
        diff_pixel_count=result.aligned_diff_pixel_count,
        ssim_score=result.ssim_score,
        change_kind=change_kind,
        diff_metadata=_diff_metadata(result),
        team_id=snapshot.team_id,
    )

    logger.info(
        "visual_review.diff_computed",
        snapshot_id=str(snapshot.id),
        identifier=snapshot.identifier,
        change_kind=change_kind.value,
        diff_percentage=result.aligned_diff_percentage,
        diff_pixel_count=result.aligned_diff_pixel_count,
        ssim_score=result.ssim_score,
        size_mismatch=result.size_mismatch,
        cluster_count=result.cluster_summary.total if result.cluster_summary else 0,
        inserted_rows=result.row_shift.inserted_rows if result.row_shift else 0,
        deleted_rows=result.row_shift.deleted_rows if result.row_shift else 0,
    )


def _store_absorbed(snapshot: RunSnapshot, result: CompareResult) -> None:
    """Reclassify a below-threshold snapshot as noise and record what it cost.

    The aligned metrics equal the naive ones when nothing aligned, so an
    absorbed shift is recorded at what it really cost (a residual of a
    fraction of a percent) instead of at the whole page below the shift.
    `FlakinessEntry.headroom` is measured against these numbers.

    A shift that actually moved rows also keeps its diff image and its
    metadata, so a reviewer can see the line that moved. A pair that aligned
    with nothing moved is plain noise and gets neither, because that would be
    an artifact upload per snapshot for a picture of nothing.
    """
    from .logic import snapshot_diffs

    shift = result.row_shift
    has_shift = shift is not None and shift.shifted_rows > 0

    # The diff image is a courtesy for the reviewer, not the decision. The task
    # runs the diff pass once, so a lost upload must not leave a noise row
    # sitting CHANGED with no kind and fail the gate for it.
    diff_artifact: Artifact | None = None
    if has_shift and result.diff_image:
        try:
            diff_artifact = _write_diff_artifact(snapshot, result)
        except Exception as e:
            logger.warning(
                "visual_review.absorbed_diff_upload_failed",
                snapshot_id=str(snapshot.id),
                identifier=snapshot.identifier,
                error=str(e),
            )
    snapshot_diffs.update_snapshot_diff(
        snapshot_id=snapshot.id,
        diff_artifact=diff_artifact,
        diff_percentage=result.aligned_diff_percentage,
        diff_pixel_count=result.aligned_diff_pixel_count,
        ssim_score=result.ssim_score,
        change_kind=None,
        diff_metadata=_diff_metadata(result) if has_shift else None,
        absorbed=True,
        team_id=snapshot.team_id,
    )

    logger.info(
        "visual_review.diff_below_threshold",
        snapshot_id=str(snapshot.id),
        identifier=snapshot.identifier,
        diff_percentage=result.aligned_diff_percentage,
        ssim_score=result.ssim_score,
        inserted_rows=shift.inserted_rows if shift else 0,
        deleted_rows=shift.deleted_rows if shift else 0,
        residual_percentage=shift.residual_percentage if shift else None,
    )


def _diff_snapshot(snapshot: RunSnapshot) -> bool:
    """Compare snapshot against baseline; classify and store diff metrics.

    Classification (in priority order):
    1. Pixel diff above threshold -> CHANGED, kind=pixel
    2. Rows inserted or deleted past the absorb cap -> CHANGED, kind=layout
    3. SSIM dissimilarity above threshold -> CHANGED, kind=structural
       (tall-page dilution safety net)
    4. All below -> UNCHANGED (noise), auto-populate tolerance cache.

    When the pair aligned, the thresholds run on the residual and on the SSIM
    of the matched rows, so a page that moved down by a row or two is absorbed
    instead of reading as a page-wide change.

    Size mismatch is recorded as `diff_metadata.size_mismatch` and surfaced
    separately in the UI — a snapshot can have a different viewport AND a
    real content change, so we don't conflate the two.

    `diff_percentage` and `ssim_score` are recorded faithfully; the categorical
    kind is what callers use to render. No overwriting one signal with another.
    """
    from .logic import artifact_store

    repo_id = snapshot.run.repo_id
    assert snapshot.baseline_artifact is not None
    assert snapshot.current_artifact is not None

    baseline_bytes = artifact_store.read_artifact_bytes(repo_id, snapshot.baseline_artifact.content_hash)
    current_bytes = artifact_store.read_artifact_bytes(repo_id, snapshot.current_artifact.content_hash)

    if not baseline_bytes or not current_bytes:
        logger.warning(
            "visual_review.diff_skipped_missing_artifact",
            snapshot_id=str(snapshot.id),
            identifier=snapshot.identifier,
            has_baseline=baseline_bytes is not None,
            has_current=current_bytes is not None,
        )
        return False

    result = compare_images(baseline_bytes, current_bytes)

    _store_thumbnail(snapshot, result)

    kind = classify_compare_result(result)
    if kind is not None:
        _store_diff(snapshot, result, kind)
        return True

    _store_absorbed(snapshot, result)

    # Auto-populate tolerance cache so future runs skip diffing for this hash.
    # Explicit team_id in the lookup (not just defaults) so the IDOR audit
    # rule sees the scope; ProductTeamManager also auto-filters by canonical
    # team — both belt and suspenders.
    ToleratedHash.objects.get_or_create(
        team_id=snapshot.team_id,
        repo_id=snapshot.run.repo_id,
        identifier=snapshot.identifier,
        baseline_hash=snapshot.baseline_hash,
        alternate_hash=snapshot.current_hash,
        defaults={
            "reason": ToleratedReason.AUTO_THRESHOLD,
            "source_run": snapshot.run,
            "diff_percentage": result.aligned_diff_percentage,
        },
    )
    return True


def _generate_thumbnail_for_new(snapshot: RunSnapshot) -> None:
    """Generate thumbnail for NEW snapshots (no baseline to compare against)."""
    from .logic import artifact_store

    artifact = snapshot.current_artifact
    if artifact is None or artifact.thumbnail_id is not None:
        return

    current_bytes = artifact_store.read_artifact_bytes(snapshot.run.repo_id, artifact.content_hash)
    if not current_bytes:
        return

    try:
        webp_bytes = pixelhog_thumbnail(current_bytes, width=THUMB_WIDTH, height=THUMB_HEIGHT)
    except Exception:
        logger.warning(
            "visual_review.thumbnail_generation_failed",
            snapshot_id=str(snapshot.id),
            identifier=snapshot.identifier,
        )
        return

    thumb_hash = blake3(webp_bytes).hexdigest()
    thumb_artifact = artifact_store.write_artifact_bytes(
        repo_id=snapshot.run.repo_id,
        content_hash=thumb_hash,
        content=webp_bytes,
        width=THUMB_WIDTH,
        height=THUMB_HEIGHT,
        team_id=snapshot.team_id,
    )

    artifact.thumbnail = thumb_artifact
    artifact.save(update_fields=["thumbnail"])


def count_processed_diffs(run_id: UUID) -> int:
    return (
        RunSnapshot.objects.using(WRITER_DB)
        .filter(run_id=run_id)
        .filter(
            ~Q(change_kind="")
            | Q(
                result=SnapshotResult.UNCHANGED,
                classification_reason=ClassificationReason.BELOW_THRESHOLD,
            )
        )
        .count()
    )


def process_diffs(run_id: UUID) -> int:
    """
    Process diffs for all changed snapshots in a run.

    Uses single-pass comparison (pixelmatch + SSIM + thumbnail) to classify
    each snapshot and generate thumbnails for the grid view.
    """
    snapshots = (
        RunSnapshot.objects.using(WRITER_DB)
        .filter(run_id=run_id)
        .filter(
            Q(
                result=SnapshotResult.NEW,
                current_artifact__isnull=False,
                current_artifact__thumbnail__isnull=True,
            )
            | Q(result=SnapshotResult.CHANGED, change_kind="", diff_artifact__isnull=True)
        )
        .select_related("run", "current_artifact", "baseline_artifact")
        .iterator(chunk_size=100)
    )
    diffed_count = 0

    for snapshot in snapshots:
        if snapshot.result == SnapshotResult.NEW and snapshot.current_artifact:
            _generate_thumbnail_for_new(snapshot)

        if snapshot.result != SnapshotResult.CHANGED:
            continue

        if not snapshot.current_artifact or not snapshot.baseline_artifact:
            continue

        try:
            if _diff_snapshot(snapshot):
                diffed_count += 1
        except Exception as e:
            logger.warning(
                "visual_review.snapshot_diff_failed",
                snapshot_id=str(snapshot.id),
                identifier=snapshot.identifier,
                error=str(e),
            )

    return diffed_count
