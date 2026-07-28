"""Facade for the exports product — the surface other products may import.

Currently exposes synchronous PNG rendering so composed endpoints (e.g. a task run
delivering a chart to Slack) can render server-side without shuttling bytes through
API clients.
"""

from datetime import timedelta

from django.conf import settings

import structlog
from asgiref.sync import async_to_sync
from temporalio.common import WorkflowIDReusePolicy

from posthog.models import Team, User
from posthog.rbac.user_access_control import UserAccessControl
from posthog.storage import object_storage
from posthog.temporal.common.client import async_connect
from posthog.temporal.exports.workflows import ExportAssetWorkflow, ExportAssetWorkflowInputs

from products.exports.backend.models.exported_asset import ExportedAsset
from products.product_analytics.backend.models.insight import Insight

logger = structlog.get_logger(__name__)

# Caps the whole workflow including retries; callers block on this, so it must stay
# well under the web tier's request timeout.
RENDER_TIMEOUT = timedelta(seconds=90)


def render_png_export(
    *,
    team: Team,
    created_by: User | None,
    export_context: dict | None = None,
    insight_id: int | None = None,
) -> tuple[ExportedAsset, bytes | None]:
    """Render a PNG export synchronously and return the asset together with its content bytes.

    Blocks until the export workflow finishes (typically a few seconds). On failure the
    returned bytes are None and ``asset.exception`` carries the error.
    """
    if (export_context is None) == (insight_id is None):
        raise ValueError("Provide exactly one of export_context or insight_id")
    if insight_id is not None:
        insight = Insight.objects.filter(id=insight_id, team_id=team.id, deleted=False).first()
        # Object-level access matters here: created_by may not be allowed to view the insight.
        if insight is None or (
            created_by is not None
            and not UserAccessControl(user=created_by, team=team).check_access_level_for_object(insight, "viewer")
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
                distinct_id=str(created_by.distinct_id) if created_by else str(team.id),
            ),
            id=f"export-asset-{asset.id}",
            task_queue=settings.ANALYTICS_PLATFORM_TASK_QUEUE,
            id_reuse_policy=WorkflowIDReusePolicy.TERMINATE_IF_RUNNING,
            execution_timeout=RENDER_TIMEOUT,
        )

    try:
        async_to_sync(_run)()
    except Exception as e:
        # export_asset_direct records the failure on the asset before re-raising, so callers
        # read asset.exception; swallowing here mirrors the exports API's create path.
        logger.info("render_png_export_failed", asset_id=asset.id, error=str(e))

    asset.refresh_from_db()
    if asset.exception:
        return asset, None
    content = asset.content
    if content is None and asset.content_location:
        content = object_storage.read_bytes(asset.content_location)
    return asset, bytes(content) if content is not None else None
