import uuid
from datetime import timedelta

from django.conf import settings

import tiktoken
import temporalio

from posthog.schema import SignalInput

from posthog.models import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.client import async_connect

from products.signals.backend.models import SignalSourceConfig
from products.signals.backend.report_generation.research import Priority
from products.signals.backend.temporal.buffer import BufferSignalsWorkflow
from products.signals.backend.temporal.emit_report import EmitReportWorkflow, EmitReportWorkflowInput
from products.signals.backend.temporal.emitter import SignalEmitterInput, SignalEmitterWorkflow
from products.signals.backend.temporal.types import BufferSignalsInput, EmitSignalInputs

MAX_SIGNAL_DESCRIPTION_TOKENS = 8000
_tiktoken_encoding = tiktoken.get_encoding("cl100k_base")


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
    Emit a signal for grouping and potential report generation, fire-and-forget.

    Active path:
        emit_signal() -> SignalEmitterWorkflow -> BufferSignalsWorkflow -> TeamSignalGroupingV2Workflow

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
            source_product="github",
            source_type="issue",
            source_id="posthog/posthog#12345",
            description="GitHub Issue #12345: Button doesn't work on Safari\nLabels: bug\n...",
            weight=0.8,
            extra={"html_url": "https://github.com/posthog/posthog/issues/12345", "number": 12345, ...},
        )
    """

    organization = await database_sync_to_async(lambda: team.organization)()
    if not organization.is_ai_data_processing_approved:
        return

    is_enabled = await database_sync_to_async(SignalSourceConfig.is_source_enabled, thread_sensitive=False)(
        team.id, source_product, source_type
    )
    if not is_enabled:
        return

    token_count = len(_tiktoken_encoding.encode(description))
    if token_count > MAX_SIGNAL_DESCRIPTION_TOKENS:
        raise ValueError(
            f"Signal description exceeds {MAX_SIGNAL_DESCRIPTION_TOKENS} tokens ({token_count} tokens). "
            f"Truncate the description before calling emit_signal."
        )

    # Raise if signal doesn't match any known schema
    SignalInput.model_validate(
        {
            "source_product": source_product,
            "source_type": source_type,
            "source_id": source_id,
            "description": description,
            "weight": weight,
            "extra": extra or {},
        }
    )

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

    # Ensure the buffer workflow is running (idempotent)
    try:
        await client.start_workflow(
            BufferSignalsWorkflow.run,
            BufferSignalsInput(team_id=team.id),
            id=BufferSignalsWorkflow.workflow_id_for(team.id),
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
            run_timeout=timedelta(hours=1),
        )
    except temporalio.exceptions.WorkflowAlreadyStartedError:
        pass

    # Fire-and-forget: the emitter workflow will submit the signal to the buffer
    # via update, blocking if the buffer is full (backpressure).
    await client.start_workflow(
        SignalEmitterWorkflow.run,
        SignalEmitterInput(team_id=team.id, signal=signal_input),
        id=SignalEmitterWorkflow.workflow_id_for(team.id),
        task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
        run_timeout=timedelta(minutes=10),
    )


async def emit_report(
    team: Team,
    title: str,
    summary: str,
    priority: Priority,
    priority_explanation: str,
) -> str:
    """
    Emit a fully-formed report for enrichment and potential auto-start, fire-and-forget.

    Creates a SignalReport and starts an EmitReportWorkflow that:
    1. Selects a repository from the team's GitHub integrations
    2. Runs an enrichment agent to gather commit hashes, code paths, and data context
    3. Persists artefacts and resolves suggested reviewers
    4. Checks auto-start conditions for an implementation task
    5. Always marks reports as immediately actionable

    No signals are attached to the report.

    Args:
        team: The team object (org must have is_ai_data_processing_approved)
        title: PR-style report title
        summary: Axios-style report summary
        priority: Priority level (P0-P4)
        priority_explanation: Justification for priority level

    Returns:
        The report ID (UUID string). The workflow runs asynchronously.

    Example:
        report_id = await emit_report(
            team=team,
            title="fix(dashboard): Timezone mismatch in date filter",
            summary="**What's happening:** ...",
            priority=Priority.P2,
            priority_explanation="Affects all users filtering by date in non-UTC timezones.",
        )
    """

    organization = await database_sync_to_async(lambda: team.organization)()
    if not organization.is_ai_data_processing_approved:
        raise ValueError("Organization has not approved AI data processing")

    report_id = str(uuid.uuid4())

    client = await async_connect()

    workflow_input = EmitReportWorkflowInput(
        team_id=team.id,
        report_id=report_id,
        title=title,
        summary=summary,
        priority=priority.value,
        priority_explanation=priority_explanation,
    )

    await client.start_workflow(
        EmitReportWorkflow.run,
        workflow_input,
        id=EmitReportWorkflow.workflow_id_for(team.id, report_id),
        task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
        run_timeout=timedelta(hours=2),
    )

    return report_id
