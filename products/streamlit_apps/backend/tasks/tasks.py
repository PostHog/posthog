from __future__ import annotations

import uuid
from typing import Literal

import structlog
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded

from posthog.models.scoping import with_team_scope
from posthog.scoping_audit import skip_team_scope_audit

logger = structlog.get_logger(__name__)

# soft_time_limit fires first so we can mark the sandbox as ERROR before celery kills us.
_TASK_TIME_LIMIT = 600
_TASK_SOFT_TIME_LIMIT = 540

_OAUTH_CLEANUP_BATCH_SIZE = 10_000
_DELETED_ZIP_RETENTION_DAYS = 7
_IDLE_TIMEOUT_MINUTES = 30
_VERSION_RETENTION_DAYS = 30


def _mark_sandbox_error(app_id: str, message: str) -> None:
    """Best-effort mark the sandbox as ERROR from a background task."""
    try:
        from products.streamlit_apps.backend.models import StreamlitAppSandbox

        sandbox = StreamlitAppSandbox.objects.filter(app_id=uuid.UUID(app_id)).first()
        if sandbox is None:
            return
        sandbox.status = StreamlitAppSandbox.Status.ERROR
        sandbox.last_error = message[:1000]
        sandbox.save(update_fields=["status", "last_error"])
    except Exception:
        logger.exception("streamlit_task_mark_error_failed", app_id=app_id)


@shared_task(
    ignore_result=True,
    time_limit=_TASK_TIME_LIMIT,
    soft_time_limit=_TASK_SOFT_TIME_LIMIT,
    max_retries=0,
)
@with_team_scope()
def run_streamlit_app_lifecycle(app_id: str, action: Literal["start", "restart"], team_id: int) -> None:
    """Celery entry point for both start and restart."""
    from posthog.storage import object_storage

    from products.streamlit_apps.backend.logic.app_runtime import AppRuntimeConcurrencyError, AppRuntimeService
    from products.streamlit_apps.backend.models import StreamlitApp

    try:
        app = StreamlitApp.objects.get(id=app_id, deleted=False)
    except StreamlitApp.DoesNotExist:
        logger.warning("streamlit_app_lifecycle_not_found", app_id=app_id, action=action)
        return

    if action == "start" and not app.active_version:
        logger.warning("streamlit_app_lifecycle_no_version", app_id=app_id)
        return

    try:
        zip_content = None
        if app.active_version:
            zip_content = object_storage.read_bytes(app.active_version.zip_file)

        runtime = AppRuntimeService()
        if action == "start":
            runtime.start_app(app, zip_content=zip_content)
        else:
            runtime.restart_app(app, zip_content=zip_content)
    except AppRuntimeConcurrencyError:
        # Benign — another worker is handling it. Don't stamp ERROR.
        logger.info("streamlit_app_lifecycle_concurrent_noop", app_id=app_id, action=action)
        return
    except SoftTimeLimitExceeded:
        logger.exception("streamlit_app_lifecycle_timeout", app_id=app_id, action=action)
        _mark_sandbox_error(app_id, f"{action.title()} exceeded time limit.")
        raise
    except Exception as exc:
        logger.exception("streamlit_app_lifecycle_failed", app_id=app_id, action=action)
        _mark_sandbox_error(app_id, f"{action.title()} failed: {exc}")
        raise


@shared_task(ignore_result=True, max_retries=0)
@with_team_scope()
def reset_streamlit_app_restart_count_if_stable(app_id: str, team_id: int) -> None:
    """Reset restart_count to 0 only if the sandbox is still RUNNING and stable.

    Deferred via countdown so a brief RUNNING bounce in a crash loop can't
    wipe the counter and bypass MAX_RESTART_COUNT.
    """
    from datetime import timedelta

    from django.utils import timezone

    from products.streamlit_apps.backend.logic.app_runtime import RESTART_COUNT_STABILITY_SECONDS
    from products.streamlit_apps.backend.models import StreamlitApp, StreamlitAppSandbox

    try:
        app = StreamlitApp.objects.get(id=app_id, deleted=False)
    except StreamlitApp.DoesNotExist:
        return

    sandbox = StreamlitAppSandbox.objects.filter(app=app).first()
    if sandbox is None or sandbox.status != StreamlitAppSandbox.Status.RUNNING or sandbox.started_at is None:
        return

    if timezone.now() - sandbox.started_at < timedelta(seconds=RESTART_COUNT_STABILITY_SECONDS):
        return

    StreamlitApp.objects.filter(id=app_id).update(restart_count=0)


@shared_task(ignore_result=True)
@skip_team_scope_audit  # genuinely cross-team housekeeping
def cleanup_expired_streamlit_oauth_tokens() -> int:
    """Delete expired OAuthAccessToken rows for the Streamlit app, in batches."""
    from django.utils import timezone

    from posthog.models.oauth import OAuthAccessToken

    from products.streamlit_apps.backend.logic.oauth import get_streamlit_oauth_app

    oauth_app = get_streamlit_oauth_app()

    total_to_delete = OAuthAccessToken.objects.filter(
        application=oauth_app,
        expires__lt=timezone.now(),
    ).count()

    if total_to_delete == 0:
        return 0

    num_batches = -(-total_to_delete // _OAUTH_CLEANUP_BATCH_SIZE)
    total_deleted = 0

    for _ in range(num_batches):
        ids = list(
            OAuthAccessToken.objects.filter(
                application=oauth_app,
                expires__lt=timezone.now(),
            ).values_list("id", flat=True)[:_OAUTH_CLEANUP_BATCH_SIZE]
        )
        if not ids:
            break
        deleted, _ = OAuthAccessToken.objects.filter(id__in=ids).delete()
        total_deleted += deleted

    if total_deleted:
        logger.info("streamlit_oauth_tokens_cleaned_up", deleted=total_deleted)
    return total_deleted


@shared_task(ignore_result=True)
@skip_team_scope_audit  # genuinely cross-team housekeeping
def cleanup_deleted_streamlit_app_zips() -> int:
    """Hard-delete zip objects and version rows for soft-deleted apps past the retention window."""
    from datetime import timedelta

    from django.utils import timezone

    from posthog.storage import object_storage

    from products.streamlit_apps.backend.models import StreamlitAppVersion

    cutoff = timezone.now() - timedelta(days=_DELETED_ZIP_RETENTION_DAYS)
    stale_versions = StreamlitAppVersion.objects.filter(
        app__deleted=True,
        app__deleted_at__lt=cutoff,
    ).only("id", "zip_file")

    deleted = 0
    for version in stale_versions.iterator(chunk_size=200):
        try:
            object_storage.delete(version.zip_file)
        except Exception:
            logger.warning("streamlit_zip_cleanup_storage_delete_failed", version_id=str(version.id), exc_info=True)
            # Leave the row so we retry next run.
            continue
        StreamlitAppVersion.objects.filter(id=version.id).delete()
        deleted += 1

    if deleted:
        logger.info("streamlit_deleted_app_zips_cleaned_up", deleted=deleted)
    return deleted


@shared_task(ignore_result=True)
@skip_team_scope_audit  # genuinely cross-team housekeeping
def stop_idle_streamlit_sandboxes() -> int:
    """Stop sandboxes whose last_activity_at (or started_at, if no traffic yet)
    is older than _IDLE_TIMEOUT_MINUTES. Saves Modal compute on apps left open
    in a forgotten browser tab."""
    from datetime import timedelta

    from django.utils import timezone

    from products.streamlit_apps.backend.logic.app_runtime import AppRuntimeService
    from products.streamlit_apps.backend.models import StreamlitApp, StreamlitAppSandbox

    cutoff = timezone.now() - timedelta(minutes=_IDLE_TIMEOUT_MINUTES)
    # Apps with no traffic since boot are still idle — fall back to started_at
    # via Coalesce so we don't leave never-used sandboxes running forever.
    from django.db.models.functions import Coalesce

    idle_sandboxes = (
        StreamlitAppSandbox.objects.filter(status=StreamlitAppSandbox.Status.RUNNING)
        .annotate(_idle_marker=Coalesce("last_activity_at", "started_at"))
        .filter(_idle_marker__lt=cutoff)
        .select_related("app")
    )

    runtime = AppRuntimeService()
    stopped = 0
    for sandbox in idle_sandboxes.iterator(chunk_size=100):
        app: StreamlitApp = sandbox.app
        try:
            runtime.stop_app(app)
            stopped += 1
            logger.info(
                "streamlit_idle_sandbox_stopped",
                app_id=str(app.id),
                idle_since=sandbox.last_activity_at or sandbox.started_at,
            )
        except Exception:
            logger.warning("streamlit_idle_sandbox_stop_failed", app_id=str(app.id), exc_info=True)

    return stopped


@shared_task(ignore_result=True)
@skip_team_scope_audit  # genuinely cross-team housekeeping
def auto_restart_crashed_streamlit_sandboxes() -> int:
    """Restart sandboxes that died on their own (Modal TTL timeout), respecting
    the MAX_RESTART_COUNT cap. Only acts on the exact `last_error` set by
    `_sync_sandbox_status` — user-initiated stops, idle stops, and startup
    failures leave a different string and are not restarted."""
    from products.streamlit_apps.backend.logic.app_runtime import MAX_RESTART_COUNT, TTL_TIMEOUT_LAST_ERROR
    from products.streamlit_apps.backend.models import StreamlitAppSandbox

    crashed = StreamlitAppSandbox.objects.filter(
        status=StreamlitAppSandbox.Status.STOPPED,
        last_error=TTL_TIMEOUT_LAST_ERROR,
        app__deleted=False,
        app__restart_count__lt=MAX_RESTART_COUNT,
    ).select_related("app")

    restarted = 0
    for sandbox in crashed.iterator(chunk_size=100):
        app_id = str(sandbox.app_id)
        try:
            # Hand off to the existing lifecycle task so we don't block on
            # Modal cold-starts here and the cap/lock logic stays in one place.
            run_streamlit_app_lifecycle.delay(app_id, "restart", team_id=sandbox.app.team_id)
            restarted += 1
            logger.info("streamlit_crashed_sandbox_restart_dispatched", app_id=app_id)
        except Exception:
            logger.warning("streamlit_crashed_sandbox_restart_failed", app_id=app_id, exc_info=True)

    return restarted


@shared_task(ignore_result=True)
@skip_team_scope_audit  # genuinely cross-team housekeeping
def prune_old_streamlit_app_versions() -> int:
    """Hard-delete non-active versions older than _VERSION_RETENTION_DAYS for
    apps that are NOT soft-deleted (those are handled by
    cleanup_deleted_streamlit_app_zips). Drops the zip from object storage;
    snapshot cleanup is intentionally deferred — see TODO below."""
    from datetime import timedelta

    from django.db.models import F
    from django.utils import timezone

    from posthog.storage import object_storage

    from products.streamlit_apps.backend.models import StreamlitAppVersion

    cutoff = timezone.now() - timedelta(days=_VERSION_RETENTION_DAYS)
    stale = (
        StreamlitAppVersion.objects.filter(
            created_at__lt=cutoff,
            app__deleted=False,
        )
        .exclude(id=F("app__active_version_id"))
        .only("id", "zip_file", "snapshot_id")
    )

    deleted = 0
    for version in stale.iterator(chunk_size=200):
        try:
            object_storage.delete(version.zip_file)
        except Exception:
            logger.warning(
                "streamlit_version_prune_zip_delete_failed",
                version_id=str(version.id),
                exc_info=True,
            )
            # Leave the row so we retry on the next run.
            continue

        # TODO: delete Modal snapshot at version.snapshot_id once
        # ModalSandbox exposes a snapshot delete API. Skipping silently is
        # the correct trade-off today — snapshots are cheap and Modal cleans
        # them up on a longer horizon.
        StreamlitAppVersion.objects.filter(id=version.id).delete()
        deleted += 1

    if deleted:
        logger.info("streamlit_old_versions_pruned", deleted=deleted)
    return deleted
