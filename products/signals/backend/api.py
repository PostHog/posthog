import json
from datetime import datetime, timedelta

from django.conf import settings

from posthog.schema import EmbeddingModelName, SignalInput

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.api.embedding_worker import emit_embedding_request
from posthog.models import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.client import async_connect

from products.signals.backend.temporal.grouping import TeamSignalGroupingWorkflow
from products.signals.backend.temporal.types import EmitSignalInputs, TeamSignalGroupingInput

EMBEDDING_MODEL = EmbeddingModelName.TEXT_EMBEDDING_3_SMALL_1536


def soft_delete_report_signals(report_id: str, team_id: int, team: Team) -> None:
    """
    Soft-delete all ClickHouse signals for a report by re-emitting them with metadata.deleted=True.

    Preserves the original timestamp so each row lands in the same ReplacingMergeTree partition
    and replaces the original. Intentionally fetches ALL signals (including already-deleted ones)
    so no signals are missed on repeated calls.
    """
    query = """
        SELECT
            document_id,
            content,
            metadata,
            toString(timestamp) as timestamp
        FROM (
            SELECT
                document_id,
                argMax(content, inserted_at) as content,
                argMax(metadata, inserted_at) as metadata,
                argMax(timestamp, inserted_at) as timestamp
            FROM document_embeddings
            WHERE model_name = {model_name}
              AND product = 'signals'
              AND document_type = 'signal'
            GROUP BY document_id
        )
        WHERE JSONExtractString(metadata, 'report_id') = {report_id}
        ORDER BY timestamp ASC
        LIMIT 5000
    """

    result = execute_hogql_query(
        query_type="SignalsSoftDeleteForReport",
        query=query,
        team=team,
        placeholders={
            "model_name": ast.Constant(value=EMBEDDING_MODEL.value),
            "report_id": ast.Constant(value=report_id),
        },
    )

    for row in result.results or []:
        document_id, content, metadata_str, timestamp_str = row
        metadata = json.loads(metadata_str)
        metadata["deleted"] = True

        emit_embedding_request(
            content=content,
            team_id=team_id,
            product="signals",
            document_type="signal",
            rendering="plain",
            document_id=document_id,
            models=[m.value for m in EmbeddingModelName],
            timestamp=datetime.fromisoformat(timestamp_str),
            metadata=metadata,
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
    Emit a signal for clustering and potential summarization, fire-and-forget.

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
            source_product="github",
            source_type="issue",
            source_id="posthog/posthog#12345",
            description="GitHub Issue #12345: Button doesn't work on Safari\nLabels: bug\n...",
            weight=0.8,
            extra={"html_url": "https://github.com/posthog/posthog/issues/12345", "number": 12345, ...},
        )
    """
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
