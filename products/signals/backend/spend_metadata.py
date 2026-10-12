import json
from datetime import UTC

from posthog.schema import EmbeddingModelName

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.kafka_client.routing import producer_scope
from posthog.kafka_client.topics import KAFKA_DOCUMENT_EMBEDDINGS_TOPIC
from posthog.models import Team

from products.signals.backend.models import SignalSpend
from products.signals.backend.signal_metadata import (
    SIGNAL_DOCUMENT_PRODUCT,
    SIGNAL_DOCUMENT_RENDERING,
    SIGNAL_DOCUMENT_TYPE,
    _signals_query_context,
)
from products.signals.backend.spend import SignalSpendSummary, signal_spend_summaries


def refresh_signal_spend_metadata(*, team_id: int, signal_id: str) -> bool:
    """Return true only once every embedding model's stored metadata matches the receipts."""
    team = Team.objects.get(id=team_id)
    summary = signal_spend_summaries(team_id=team_id, signal_ids=[signal_id]).get(signal_id)
    if summary is None:
        if SignalSpend.objects.for_team(team_id).filter(signal_id=signal_id).exists():
            raise RuntimeError("Could not read signal spend")
        summary = SignalSpendSummary(total_spend=0, failed_stages=[])
    tag_queries(product=Product.SIGNALS, feature=Feature.QUERY)
    confirmed = True
    for model in EmbeddingModelName:
        result = execute_hogql_query(
            query_type="SignalsRefreshSpendMetadata",
            query="""
                SELECT document_id, argMax(tuple(content, metadata, timestamp, embedding), inserted_at)
                FROM document_embeddings
                WHERE model_name = {model_name}
                  AND product = 'signals' AND document_type = 'signal' AND rendering = 'plain'
                  AND document_id = {signal_id}
                GROUP BY document_id
            """,
            team=team,
            context=_signals_query_context(team),
            placeholders={"model_name": ast.Constant(value=model.value), "signal_id": ast.Constant(value=signal_id)},
        )
        if not result.results:
            confirmed = False
            continue
        content, metadata_json, timestamp, embedding = result.results[0][1]
        metadata = json.loads(metadata_json)
        if (
            metadata.get("total_spend") == summary.total_spend
            and metadata.get("spend_accounting_failed_stages") == summary.failed_stages
        ):
            continue
        confirmed = False
        metadata.update(total_spend=summary.total_spend, spend_accounting_failed_stages=summary.failed_stages)
        # Preserve the vector and partition timestamp: accounting must not generate new embeddings.
        payload = {
            "team_id": team_id,
            "product": SIGNAL_DOCUMENT_PRODUCT,
            "document_type": SIGNAL_DOCUMENT_TYPE,
            "rendering": SIGNAL_DOCUMENT_RENDERING,
            "document_id": signal_id,
            "model_name": model.value,
            "timestamp": timestamp.replace(tzinfo=UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            "content": content,
            "metadata": json.dumps(metadata),
            "embedding": embedding,
        }
        with producer_scope(topic=KAFKA_DOCUMENT_EMBEDDINGS_TOPIC, flush_timeout=5) as producer:
            delivery = producer.produce(topic=KAFKA_DOCUMENT_EMBEDDINGS_TOPIC, data=payload)
        delivery.get(timeout=0)
    return confirmed
