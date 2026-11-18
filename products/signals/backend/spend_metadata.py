import json
from dataclasses import replace
from datetime import UTC, datetime

from django.utils import timezone

from pydantic import JsonValue

from posthog.schema import EmbeddingModelName

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.dataclasses import frozen
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
from products.signals.backend.spend import (
    SignalMetadataChange,
    SignalSpendPublication,
    SignalSpendSummary,
    SignalSpendUpdate,
    signal_spend_summaries,
)


@frozen
class _SignalEmbedding:
    model: EmbeddingModelName
    content: str
    metadata: dict[str, JsonValue]
    timestamp: datetime
    embedding: list[float]
    inserted_at: datetime

    def with_updates(self, summary: SignalSpendSummary, changes: list[SignalMetadataChange]) -> "_SignalEmbedding":
        metadata: dict[str, JsonValue] = {
            **self.metadata,
            "total_spend": summary.total_spend,
            "spend_accounting_failed_stages": [*summary.failed_stages],
        }
        clear_content = False
        for change in changes:
            if change.expected_report_id is not None and metadata.get("report_id") != change.expected_report_id:
                continue
            if change.report_id is not None and not metadata.get("deleted"):
                metadata["report_id"] = change.report_id
            if change.deleted:
                metadata["deleted"] = True
            clear_content |= change.clear_content
        return replace(
            self,
            metadata=metadata,
            content="" if clear_content else self.content,
            embedding=[0.0] * len(self.embedding) if clear_content else self.embedding,
        )


def _read_embedding(team: Team, signal_id: str, model: EmbeddingModelName) -> _SignalEmbedding | None:
    result = execute_hogql_query(
        query_type="SignalsRefreshSpendMetadata",
        ch_user=ClickHouseUser.SIGNALS,
        query="""
            SELECT document_id, argMax(tuple(content, metadata, timestamp, embedding, inserted_at), inserted_at)
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
        return None
    content, metadata_json, timestamp, embedding, inserted_at = result.results[0][1]
    return _SignalEmbedding(
        model=model,
        content=content,
        metadata=json.loads(metadata_json),
        timestamp=timestamp.replace(tzinfo=UTC),
        embedding=embedding,
        inserted_at=inserted_at.replace(tzinfo=UTC),
    )


def publish_signal_spend_metadata(signal: SignalSpendUpdate) -> SignalSpendPublication:
    team = Team.objects.get(id=signal.team_id)
    summary = signal_spend_summaries(team_id=signal.team_id, signal_ids=[signal.signal_id]).get(signal.signal_id)
    if summary is None:
        if SignalSpend.objects.for_team(signal.team_id).filter(signal_id=signal.signal_id).exists():
            raise RuntimeError("Could not read signal spend")
        summary = SignalSpendSummary(total_spend=0, failed_stages=[])
    tag_queries(product=Product.SIGNALS, feature=Feature.QUERY)
    rows = []
    version = int(timezone.now().timestamp())
    for model in EmbeddingModelName:
        row = _read_embedding(team, signal.signal_id, model)
        if row is None:
            raise RuntimeError("Signal embedding is not yet visible in ClickHouse")
        # Kafka's second-resolution timestamp is the replacement version in ClickHouse.
        if row.with_updates(summary, signal.changes) != row and int(row.inserted_at.timestamp()) >= version:
            raise RuntimeError("Waiting for a strictly newer embedding replacement version")
        rows.append(row)
    versions = {}
    for row in rows:
        updated = row.with_updates(summary, signal.changes)
        if updated == row:
            versions[row.model.value] = int(row.inserted_at.timestamp())
            continue
        payload = {
            "team_id": signal.team_id,
            "product": SIGNAL_DOCUMENT_PRODUCT,
            "document_type": SIGNAL_DOCUMENT_TYPE,
            "rendering": SIGNAL_DOCUMENT_RENDERING,
            "document_id": signal.signal_id,
            "model_name": row.model.value,
            "timestamp": row.timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            "content": updated.content,
            "metadata": json.dumps(updated.metadata),
            "embedding": updated.embedding,
        }
        with producer_scope(topic=KAFKA_DOCUMENT_EMBEDDINGS_TOPIC, flush_timeout=5) as producer:
            delivery = producer.produce(
                topic=KAFKA_DOCUMENT_EMBEDDINGS_TOPIC,
                data=payload,
                key=f"signals:{signal.team_id}:{signal.signal_id}:{row.model.value}",
            )
        delivery.get(timeout=0)
        versions[row.model.value] = version
    return SignalSpendPublication(signal=signal, summary=summary, versions=versions)


def confirm_signal_spend_metadata(publication: SignalSpendPublication) -> bool:
    team = Team.objects.get(id=publication.signal.team_id)
    tag_queries(product=Product.SIGNALS, feature=Feature.QUERY)
    for model in EmbeddingModelName:
        row = _read_embedding(team, publication.signal.signal_id, model)
        if (
            row is None
            or row.with_updates(publication.summary, publication.signal.changes) != row
            or int(row.inserted_at.timestamp()) < publication.versions[model.value]
        ):
            return False
    return True
