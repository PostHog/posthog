from __future__ import annotations

from typing import Literal

import structlog
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded

logger = structlog.get_logger(__name__)

# soft_time_limit fires first so we can mark the sandbox as ERROR before celery kills us.
_TASK_TIME_LIMIT = 600
_TASK_SOFT_TIME_LIMIT = 540

_OAUTH_CLEANUP_BATCH_SIZE = 10_000
_DELETED_ZIP_RETENTION_DAYS = 7


def _mark_sandbox_error(app_id: str, message: str) -> None:
    """Best-effort mark the sandbox as ERROR from a background task."""
    try:
        from products.streamlit_apps.backend.models import StreamlitAppSandbox

        sandbox = StreamlitAppSandbox.objects.filter(app_id=app_id).first()
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
def run_streamlit_app_lifecycle(app_id: str, action: Literal["start", "restart"]) -> None:
    """Celery entry point for both start and restart."""
    from posthog.storage import object_storage

    from products.streamlit_apps.backend.models import StreamlitApp
    from products.streamlit_apps.backend.services.app_runtime import AppRuntimeConcurrencyError, AppRuntimeService

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
def reset_streamlit_app_restart_count_if_stable(app_id: str) -> None:
    """Reset restart_count to 0 only if the sandbox is still RUNNING and stable.

    Deferred via countdown so a brief RUNNING bounce in a crash loop can't
    wipe the counter and bypass MAX_RESTART_COUNT.
    """
    from datetime import timedelta

    from django.utils import timezone

    from products.streamlit_apps.backend.models import StreamlitApp, StreamlitAppSandbox
    from products.streamlit_apps.backend.services.app_runtime import RESTART_COUNT_STABILITY_SECONDS

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
def cleanup_expired_streamlit_oauth_tokens() -> int:
    """Delete expired OAuthAccessToken rows for the Streamlit app, in 10k batches."""
    from django.utils import timezone

    from posthog.models.oauth import OAuthAccessToken

    from products.streamlit_apps.backend.services.oauth import get_streamlit_oauth_app

    oauth_app = get_streamlit_oauth_app()
    total_deleted = 0
    while True:
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
        if len(ids) < _OAUTH_CLEANUP_BATCH_SIZE:
            break

    if total_deleted:
        logger.info("streamlit_oauth_tokens_cleaned_up", deleted=total_deleted)
    return total_deleted


@shared_task(ignore_result=True)
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
