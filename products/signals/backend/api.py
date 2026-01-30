import os

from django.conf import settings

import temporalio.exceptions

from posthog.temporal.common.client import async_connect

from products.signals.backend.temporal.types import EmitSignalInputs
from products.signals.backend.temporal.workflow import EmitSignalWorkflow

EMIT_SIGNALS_ENABLED = os.getenv("EMIT_SIGNALS_ENABLED", "false").lower() == "true"


async def emit_signal(
    team_id: int,
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
        team_id: The team ID
        source_product: Product emitting the signal (e.g., "experiments", "web_analytics")
        source_type: Type of signal (e.g., "significance_reached", "traffic_anomaly")
        source_id: Unique identifier within the source (e.g., experiment UUID)
        description: Human-readable description that will be embedded
        weight: Importance/confidence of signal (0.0-1.0). Weight of 1.0 triggers research.
        extra: Optional product-specific metadata

    Example:
        await emit_signal(
            team_id=team.id,
            source_product="experiments",
            source_type="significance_reached",
            source_id=str(experiment.id),
            description="Experiment 'Homepage CTA' reached statistical significance...",
            weight=0.8,
            extra={"variant": "B", "p_value": 0.003},
        )
    """
    if not EMIT_SIGNALS_ENABLED:
        return

    client = await async_connect()

    inputs = EmitSignalInputs(
        team_id=team_id,
        source_product=source_product,
        source_type=source_type,
        source_id=source_id,
        description=description,
        weight=weight,
        extra=extra or {},
    )

    workflow_id = EmitSignalWorkflow.workflow_id_for(team_id, source_product, source_type, source_id)

    try:
        await client.start_workflow(
            EmitSignalWorkflow.run,
            inputs,
            id=workflow_id,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
        )
    except temporalio.exceptions.WorkflowAlreadyStartedError:
        pass
