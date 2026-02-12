from datetime import timedelta

from django.conf import settings

import posthoganalytics
import temporalio.exceptions
from asgiref.sync import sync_to_async
from temporalio.common import WorkflowIDReusePolicy

from posthog.models import Team
from posthog.temporal.common.client import async_connect

from products.signals.backend.temporal.types import EmitSignalInputs
from products.signals.backend.temporal.workflow import EmitSignalWorkflow


async def product_autonomy_enabled(team: Team) -> bool:
    organization = await sync_to_async(lambda: team.organization)()
    if not organization.is_ai_data_processing_approved:
        return False

    return posthoganalytics.feature_enabled(
        "product-autonomy",
        str(team.uuid),
        groups={
            "organization": str(team.organization_id),
            "project": str(team.id),
        },
        group_properties={
            "organization": {
                "id": str(team.organization_id),
            },
            "project": {
                "id": str(team.id),
            },
        },
        send_feature_flag_events=False,
    )


async def emit_signal(
    team: Team,
    source_product: str,
    source_type: str,
    source_id: str,
    description: str,
    weight: float = 0.5,
    extra: dict | None = None,
) -> None:
    """
    Emit a signal for clustering and potential research. Fire-and-forget.

    Args:
        team: The team object
        source_product: Product emitting the signal (e.g., "experiments", "web_analytics")
        source_type: Type of signal (e.g., "significance_reached", "traffic_anomaly")
        source_id: Unique identifier within the source (e.g., experiment UUID)
        description: Human-readable description that will be embedded
        weight: Importance/confidence of signal (0.0-1.0). Weight of 1.0 triggers research.
        extra: Optional product-specific metadata

    Example:
        await emit_signal(
            team=team,
            source_product="experiments",
            source_type="significance_reached",
            source_id=str(experiment.id),
            description="Experiment 'Homepage CTA' reached statistical significance...",
            weight=0.8,
            extra={"variant": "B", "p_value": 0.003},
        )
    """
    if not await product_autonomy_enabled(team):
        return

    client = await async_connect()

    inputs = EmitSignalInputs(
        team_id=team.id,
        source_product=source_product,
        source_type=source_type,
        source_id=source_id,
        description=description,
        weight=weight,
        extra=extra or {},
    )

    workflow_id = EmitSignalWorkflow.workflow_id_for(team.id, source_product, source_type, source_id)

    try:
        await client.start_workflow(
            EmitSignalWorkflow.run,
            inputs,
            id=workflow_id,
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
            execution_timeout=timedelta(minutes=30),
        )
    except temporalio.exceptions.WorkflowAlreadyStartedError:
        pass
