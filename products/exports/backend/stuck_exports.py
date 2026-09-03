from datetime import timedelta

from django.utils.timezone import now

import structlog

from posthog.ph_client import ph_scoped_capture
from posthog.settings import HOGQL_INCREASED_MAX_EXECUTION_TIME
from posthog.temporal.session_replay.rasterize_recording.types import RASTERIZE_WORKFLOW_TIMEOUT

from products.exports.backend.analytics import capture_export_event
from products.exports.backend.facade.api import EXPORT_WORKFLOW_TIMEOUT
from products.exports.backend.models.exported_asset import ExportedAsset
from products.exports.backend.tasks.failure_handler import FAILURE_TYPE_TIMEOUT_GENERATION

logger = structlog.get_logger(__name__)

STUCK_EXPORT_MESSAGE = "Export failed without throwing an exception. Please try to rerun this export and contact support if it fails to complete multiple times."

# Slack on top of a pipeline's envelope before we call an export stuck, so a render finishing right
# at its deadline isn't reported as a failure.
_STUCK_EXPORT_GRACE = timedelta(seconds=30)

# Bounds one sweep so a large backlog can't hold a worker; the next run picks up the rest.
_SWEEP_BATCH_SIZE = 500


def stuck_export_threshold(instance: ExportedAsset) -> timedelta:
    """How long an export may sit without content before nothing can still be working on it.

    Matched to whichever pipeline renders the format: video renders get the rasterize workflow's
    envelope, dataset exports the export workflow's, and everything else the HogQL query timeout it
    inherits from the Celery exporter.
    """
    if instance.is_rasterized_export:
        return RASTERIZE_WORKFLOW_TIMEOUT
    if instance.is_dataset_export:
        return EXPORT_WORKFLOW_TIMEOUT
    return timedelta(seconds=HOGQL_INCREASED_MAX_EXECUTION_TIME)


def is_stuck_export(instance: ExportedAsset) -> bool:
    """No content, no recorded exception, and past the point its pipeline could still be rendering.

    Nothing will ever mark these failed on their own — whatever was rendering them died without
    writing a reason back to the row.
    """
    if instance.has_content or instance.exception:
        return False
    return instance.created_at < now() - stuck_export_threshold(instance) - _STUCK_EXPORT_GRACE


def fail_stuck_video_exports() -> int:
    """Record a terminal failure on video exports whose workflow died without reporting one.

    The workflow's own failure path cannot cover every case. When its execution timeout fires the
    body never runs, and a dispatch failure or a lost worker leaves no execution to run it at all.
    Those rows otherwise stay indistinguishable from a render still in progress, for as long as they
    exist.
    """
    cutoff = now() - RASTERIZE_WORKFLOW_TIMEOUT - _STUCK_EXPORT_GRACE
    # Cross-team by design: a beat task with no request context, sweeping every team's exports.
    stuck = (
        ExportedAsset.objects.filter(
            export_format__in=list(ExportedAsset.RASTERIZED_FORMATS),
            content__isnull=True,
            content_location__isnull=True,
            exception__isnull=True,
            created_at__lt=cutoff,
        )
        # System assets (replay_vision scanners) reuse one contentless row per session across scans,
        # so an old created_at doesn't prove nothing is rendering it — the sweep would fail a row
        # mid-render and its first-writer check would then suppress the renderer's real outcome.
        # Those rows have their own expiry; a scanner re-render also retries them naturally.
        .exclude(is_system=True)
        .select_related("team__organization", "created_by")
        # Oldest first, so a backlog larger than one batch drains in bounded order instead of
        # re-sampling arbitrary rows each run.
        .order_by("created_at")[:_SWEEP_BATCH_SIZE]
    )

    failed = 0
    with ph_scoped_capture() as capture:
        for asset in stuck:
            asset.exception = STUCK_EXPORT_MESSAGE
            # Distinct from the renderer's own TIMEOUT: this one never reported anything at all, which
            # points at the workflow or the worker rather than at the render.
            asset.exception_type = "WORKFLOW_TIMEOUT"
            asset.failure_type = FAILURE_TYPE_TIMEOUT_GENERATION
            asset.save(update_fields=["exception", "exception_type", "failure_type"])

            capture_export_event(
                asset,
                "export failed",
                capture,
                error=STUCK_EXPORT_MESSAGE,
                error_code="WORKFLOW_TIMEOUT",
                failure_type=FAILURE_TYPE_TIMEOUT_GENERATION,
                is_user_error=False,
            )
            failed += 1

    if failed:
        logger.info("stuck_video_exports_failed", count=failed)
    return failed
