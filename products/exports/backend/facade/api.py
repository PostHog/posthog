"""Public Python interface for creating and retrieving one-off exports."""

from datetime import timedelta

from django.conf import settings
from django.http.response import HttpResponseBase

import structlog
from asgiref.sync import async_to_sync
from temporalio.common import WorkflowIDReusePolicy

from posthog.models import Team, User
from posthog.rbac.user_access_control import UserAccessControl
from posthog.storage import object_storage
from posthog.temporal.common.client import async_connect
from posthog.temporal.exports.workflows import ExportAssetWorkflow, ExportAssetWorkflowInputs

from products.exports.backend.models.exported_asset import (
    DATASET_EXPORT_KIND as DATASET_EXPORT_KIND,
    ExportedAsset,
    get_content_response,
    save_content_from_file as _save_content_from_file,
)
from products.exports.backend.tasks.failure_handler import (
    InvalidExportContext as InvalidExportContext,
    RetryableExportError as RetryableExportError,
)
from products.product_analytics.backend.models.insight import Insight

logger = structlog.get_logger(__name__)

JSONL_EXPORT_FORMAT = ExportedAsset.ExportFormat.JSONL

# Caps the whole workflow including retries; callers block on this, so it must stay
# well under the web tier's request timeout.
RENDER_TIMEOUT = timedelta(seconds=90)
EXPORT_WORKFLOW_TIMEOUT = timedelta(minutes=35)


def create_export_asset_async(
    *,
    team: Team,
    created_by: User,
    export_format: str,
    export_context: dict[str, object],
) -> ExportedAsset:
    if export_format not in ExportedAsset.get_supported_format_values():
        raise ValueError(f"Unsupported export format: {export_format}")

    asset = ExportedAsset.objects.create(
        team=team,
        created_by=created_by,
        export_format=export_format,
        export_context=export_context,
    )

    async def _start() -> None:
        client = await async_connect()
        await client.start_workflow(
            ExportAssetWorkflow.run,
            ExportAssetWorkflowInputs(
                exported_asset_id=asset.id,
                team_id=team.id,
                distinct_id=str(created_by.distinct_id),
            ),
            id=f"export-asset-{asset.id}",
            task_queue=settings.ANALYTICS_PLATFORM_TASK_QUEUE,
            id_reuse_policy=WorkflowIDReusePolicy.TERMINATE_IF_RUNNING,
            execution_timeout=EXPORT_WORKFLOW_TIMEOUT,
        )

    try:
        async_to_sync(_start)()
    except Exception as error:
        logger.info("export_workflow_failed_gracefully", asset_id=asset.id, error=str(error))
        asset.refresh_from_db()
        if not asset.exception:
            asset.exception = "The export could not be started. Try again."
            asset.exception_type = type(error).__name__
            asset.save(update_fields=["exception", "exception_type"])
    asset.refresh_from_db()
    return asset


def get_export_asset(*, team_id: int, asset_id: int) -> ExportedAsset | None:
    return ExportedAsset.objects.filter(team_id=team_id, id=asset_id).first()


def get_export_asset_content_response(*, asset: ExportedAsset, download: bool) -> HttpResponseBase:
    return get_content_response(asset, download=download)


def save_export_asset_content_from_file(
    *,
    asset: ExportedAsset,
    file_path: str,
    max_database_bytes: int | None = None,
) -> None:
    _save_content_from_file(asset, file_path, max_database_bytes=max_database_bytes)


def _validate_adhoc_export_context(export_context: dict) -> None:
    """The ad-hoc render pipeline (viewport sizing, the exporter page's Query dispatch)
    assumes an InsightVizNode-wrapped source; anything else renders a JSON dump instead
    of a chart, so reject it here with a real error instead."""
    source = export_context.get("source")
    if not isinstance(source, dict) or source.get("kind") != "InsightVizNode":
        raise ValueError("export_context.source must be an InsightVizNode-wrapped query")


def render_png_export(
    *,
    team: Team,
    created_by: User,
    export_context: dict | None = None,
    insight_id: int | None = None,
) -> tuple[ExportedAsset, bytes | None]:
    """Render a PNG export synchronously and return the asset together with its content bytes.

    Blocks until the export workflow finishes (typically a few seconds). On failure the
    returned bytes are None and ``asset.exception`` carries the error.
    """
    if created_by is None:
        # Access control below resolves against created_by; a principal-less render would
        # silently skip it, so service callers must attribute the render to a real user.
        raise ValueError("created_by is required")
    if (export_context is None) == (insight_id is None):
        raise ValueError("Provide exactly one of export_context or insight_id")
    if export_context is not None:
        _validate_adhoc_export_context(export_context)
    if insight_id is not None:
        insight = Insight.objects.filter(id=insight_id, team_id=team.id, deleted=False).first()
        # Object-level access matters here: created_by may not be allowed to view the insight.
        if insight is None or not UserAccessControl(user=created_by, team=team).check_access_level_for_object(
            insight, "viewer"
        ):
            raise ValueError("Insight not found")

    asset = ExportedAsset.objects.create(
        team=team,
        created_by=created_by,
        export_format=ExportedAsset.ExportFormat.PNG,
        export_context=export_context,
        insight_id=insight_id,
    )

    async def _run() -> None:
        client = await async_connect()
        await client.execute_workflow(
            ExportAssetWorkflow.run,
            ExportAssetWorkflowInputs(
                exported_asset_id=asset.id,
                team_id=team.id,
                distinct_id=str(created_by.distinct_id),
            ),
            id=f"export-asset-{asset.id}",
            task_queue=settings.ANALYTICS_PLATFORM_TASK_QUEUE,
            id_reuse_policy=WorkflowIDReusePolicy.TERMINATE_IF_RUNNING,
            execution_timeout=RENDER_TIMEOUT,
        )

    try:
        async_to_sync(_run)()
    except Exception as e:
        # export_asset_direct records activity failures on the asset, but a dispatch
        # failure (Temporal unreachable, workflow never started) would leave
        # asset.exception empty — record it so the documented failure contract
        # ("bytes are None and asset.exception carries the error") always holds.
        logger.info("render_png_export_failed", asset_id=asset.id, error=str(e))
        asset.refresh_from_db()
        if not asset.exception:
            asset.exception = str(e) or "Export dispatch failed"
            asset.save(update_fields=["exception"])

    asset.refresh_from_db()
    if asset.exception:
        return asset, None
    content = asset.content
    if not content and asset.content_location:
        content = object_storage.read_bytes(asset.content_location)
    if not content:
        # A workflow that reports success but stores nothing would otherwise return no bytes
        # and no exception, leaving callers unable to tell it apart from a successful render.
        asset.exception = "Export produced no content"
        asset.save(update_fields=["exception"])
        return asset, None
    return asset, bytes(content)
