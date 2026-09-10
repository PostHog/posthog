import json
from datetime import datetime, timedelta
from decimal import Decimal
from typing import cast

from django.utils import timezone

import structlog

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.kafka_client.routing import get_producer
from posthog.kafka_client.topics import KAFKA_DOCUMENT_EMBEDDINGS_TOPIC
from posthog.models import Team

from products.signals.backend.signal_costs import COST_INGESTION_GRACE_SECONDS, CostStage, add_cost, costs_in_cents
from products.signals.backend.signal_metadata import (
    EMBEDDING_MODEL,
    SIGNAL_DOCUMENT_PRODUCT,
    SIGNAL_DOCUMENT_RENDERING,
    SIGNAL_DOCUMENT_TYPE,
    _deduped_signals_subquery,
)
from products.tasks.backend.facade.billing import (
    get_internal_llm_analytics_team,
    get_signal_task_runs,
    get_task_run_compute_costs,
)

logger = structlog.get_logger(__name__)


def update_signal_costs(team_id: int, signal_id: str) -> bool:
    """Replace the projection from source totals; return whether another read is needed."""
    team = Team.objects.get(id=team_id)
    with tags_context(product=Product.SIGNALS, feature=Feature.QUERY):
        signal_result = execute_hogql_query(
            query=f"""
                SELECT content, metadata, timestamp, embedding
                FROM ({_deduped_signals_subquery(include_embedding=True, extra_where="document_id = {signal_id}")})
                LIMIT 1
            """,
            team=team,
            placeholders={
                "model_name": ast.Constant(value=EMBEDDING_MODEL.value),
                "signal_id": ast.Constant(value=signal_id),
            },
            query_type="SignalCostMetadata",
        )
        if not signal_result.results:
            return True

        content, raw_metadata, timestamp, embedding = signal_result.results[0]
        metadata = json.loads(raw_metadata)
        if not metadata.get("costs_started_at"):
            return False
        generated_after = datetime.fromisoformat(metadata["costs_started_at"])
        runs = get_signal_task_runs(team_id=team_id, signal_id=signal_id)
        run_ids = [run.run_id for run in runs]
        implementation_ids = [str(run.run_id) for run in runs if run.ai_stage == "implementation"]
        token_result = execute_hogql_query(
            query="""
                SELECT
                    if(properties.ai_stage = 'implementation'
                        OR toString(properties.task_run_id) IN {implementation_ids},
                        'implementation', 'research') AS stage,
                    toString(properties.$ai_model) AS model,
                    sum(toFloat(properties.$ai_total_cost_usd)) AS spend,
                    countIf(properties.$ai_total_cost_usd IS NULL) AS unpriced
                FROM events
                WHERE event IN ('$ai_generation', '$ai_embedding')
                    AND timestamp >= {generated_after}
                    AND toString(properties.team_id) = {team_id}
                    AND (toString(properties.triggering_signal_id) = {signal_id}
                        OR toString(properties.task_run_id) IN {run_ids})
                GROUP BY stage, model
                LIMIT 1000
            """,
            placeholders={
                "generated_after": ast.Constant(value=generated_after - timedelta(minutes=5)),
                "team_id": ast.Constant(value=str(team_id)),
                "signal_id": ast.Constant(value=signal_id),
                "run_ids": ast.Constant(value=[str(run_id) for run_id in run_ids]),
                "implementation_ids": ast.Constant(value=implementation_ids),
            },
            team=get_internal_llm_analytics_team(),
            query_type="SignalTokenCost",
        )

    token_cost: dict[CostStage, Decimal] = {}
    compute_cost: dict[CostStage, Decimal] = {}
    pending = not token_result.results
    for stage, model, spend, unpriced in token_result.results or []:
        if unpriced:
            pending = True
            logger.warning("signals.unpriced_generations", team_id=team_id, signal_id=signal_id, model=model)
        if spend is not None:
            add_cost(token_cost, cast(CostStage, stage), model or "unknown", Decimal(str(spend)))

    compute_by_run = get_task_run_compute_costs(team_id=team_id, task_run_ids=run_ids)
    for run in runs:
        add_cost(compute_cost, run.ai_stage, "sandbox", compute_by_run.get(str(run.run_id), Decimal(0)))
        if run.completed_at is None or run.completed_at > timezone.now() - timedelta(
            seconds=COST_INGESTION_GRACE_SECONDS
        ):
            pending = True

    costs = {
        "token_cost": costs_in_cents(token_cost),
        "compute_cost": costs_in_cents(compute_cost),
        "costs_pending": pending,
    }
    if any(metadata.get(key) != value for key, value in costs.items()):
        metadata.update(costs)
        # Reuse the canonical signal's vector so accounting does not buy another embedding.
        producer = get_producer(topic=KAFKA_DOCUMENT_EMBEDDINGS_TOPIC)
        result = producer.produce(
            topic=KAFKA_DOCUMENT_EMBEDDINGS_TOPIC,
            data={
                "team_id": team_id,
                "product": SIGNAL_DOCUMENT_PRODUCT,
                "document_type": SIGNAL_DOCUMENT_TYPE,
                "rendering": SIGNAL_DOCUMENT_RENDERING,
                "document_id": signal_id,
                "model_name": EMBEDDING_MODEL.value,
                "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S.%f"),
                "content": content,
                "metadata": json.dumps(metadata),
                "embedding": embedding,
            },
        )
        producer.flush(timeout=10)
        result.get(timeout=1)
    return pending
