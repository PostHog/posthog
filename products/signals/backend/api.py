from datetime import timedelta

from django.conf import settings

from posthog.models import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.client import async_connect

from products.signals.backend.temporal.grouping import TeamSignalGroupingWorkflow
from products.signals.backend.temporal.types import EmitSignalInputs, TeamSignalGroupingInput


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
    Emit a signal for clustering and potential summarization. Fire-and-forget.

    Uses signal-with-start to atomically create the per-team entity workflow
    if it doesn't exist, or send a signal to the running instance. This serializes
    all signal grouping for a team, eliminating race conditions.

    Args:
        team: The team object
        source_product: Product emitting the signal (e.g., "experiments", "web_analytics")
        source_type: Type of signal (e.g., "significance_reached", "traffic_anomaly")
        source_id: Unique identifier within the source (e.g., experiment UUID)
        description: Human-readable description that will be embedded
        weight: Importance/confidence of signal (0.0-1.0). Weight of 1.0 triggers summary.
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
    organization = await database_sync_to_async(lambda: team.organization)()
    if not organization.is_ai_data_processing_approved:
        return

    client = await async_connect()

    signal_input = EmitSignalInputs(
        team_id=team.id,
        source_product=source_product,
        source_type=source_type,
        source_id=source_id,
        description=description,
        weight=weight,
        extra=extra or {},
    )

    workflow_id = TeamSignalGroupingWorkflow.workflow_id_for(team.id)

    await client.start_workflow(
        TeamSignalGroupingWorkflow.run,
        TeamSignalGroupingInput(team_id=team.id),
        id=workflow_id,
        task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
        # run_timeout resets on each continue_as_new; execution_timeout would span all
        # continuations and eventually kill a healthy long-running entity workflow.
        run_timeout=timedelta(hours=1),
        start_signal="submit_signal",
        start_signal_args=[signal_input],
    )
