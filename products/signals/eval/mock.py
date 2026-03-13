import os
import json
import logging
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock, patch

import numpy as np
from asgiref.sync import sync_to_async

from posthog.models import Organization, Project, Team

logger = logging.getLogger(__name__)


@dataclass
class StoredSignal:
    signal_id: str
    content: str
    embedding: list[float]
    report_id: str
    source_product: str
    source_type: str
    source_id: str
    weight: float
    timestamp: str
    extra: dict = field(default_factory=dict)
    deleted: bool = False


class InMemoryClickHouse:
    """Replaces ClickHouse for signal storage and cosine search."""

    def __init__(self):
        self._signals: list[StoredSignal] = []
        self._embedding_cache: dict[str, list[float]] = {}  # content -> embedding

    def cache_embedding(self, content: str, embedding: list[float]) -> None:
        self._embedding_cache[content] = embedding

    def store_signal(
        self,
        signal_id: str,
        content: str,
        embedding: list[float],
        metadata: dict,
        timestamp: str = "",
    ) -> None:
        report_id = metadata.get("report_id", "")
        source_product = metadata.get("source_product", "")
        deleted = metadata.get("deleted", False)
        logger.info(
            "CH store: signal=%s report=%s product=%s deleted=%s content=%.80s",
            signal_id[:12],
            report_id[:12],
            source_product,
            deleted,
            content.replace("\n", " "),
        )
        self._signals.append(
            StoredSignal(
                signal_id=signal_id,
                content=content,
                embedding=embedding,
                report_id=report_id,
                source_product=source_product,
                source_type=metadata.get("source_type", ""),
                source_id=metadata.get("source_id", ""),
                weight=metadata.get("weight", 0.0),
                extra=metadata.get("extra", {}),
                timestamp=timestamp,
                deleted=deleted,
            )
        )

    def cosine_search(self, query_embedding: list[float], limit: int = 10) -> list[list]:
        """Return rows matching the SignalsRunEmbeddingQuery format."""
        searchable = [s for s in self._signals if not s.deleted and s.report_id and np.linalg.norm(s.embedding) > 0]
        logger.info("CH search: %d stored, %d searchable", len(self._signals), len(searchable))

        if not searchable:
            return []

        q = np.array(query_embedding, dtype=np.float64)
        q_norm = np.linalg.norm(q)
        if q_norm == 0:
            return []

        scored = []
        for sig in searchable:
            s = np.array(sig.embedding, dtype=np.float64)
            dist = 1.0 - float(np.dot(q, s) / (q_norm * np.linalg.norm(s)))
            scored.append((dist, sig))

        scored.sort(key=lambda x: x[0])
        results = scored[:limit]
        for dist, sig in results:
            logger.info(
                "  candidate: signal=%s report=%s dist=%.4f content=%.60s",
                sig.signal_id[:12],
                sig.report_id[:12],
                dist,
                sig.content.replace("\n", " "),
            )
        return [
            [sig.signal_id, sig.content, sig.report_id, sig.source_product, sig.source_type, dist]
            for dist, sig in results
        ]

    def get_signals_for_report(self, report_id: str) -> list[list]:
        """Return rows matching the SignalsFetchForReport format."""
        results = []
        for sig in self._signals:
            if sig.report_id == report_id and not sig.deleted:
                metadata = json.dumps(
                    {
                        "source_product": sig.source_product,
                        "source_type": sig.source_type,
                        "source_id": sig.source_id,
                        "weight": sig.weight,
                        "report_id": sig.report_id,
                        "extra": sig.extra,
                    }
                )
                results.append([sig.signal_id, sig.content, metadata, sig.timestamp])
        logger.info("CH fetch_for_report: report=%s found=%d signals", report_id[:12], len(results))
        return results

    def get_type_examples(self) -> list[list]:
        """Return rows matching the SignalsFetchTypeExamples format."""
        seen: dict[tuple[str, str], StoredSignal] = {}
        for sig in self._signals:
            if sig.deleted:
                continue
            key = (sig.source_product, sig.source_type)
            if key not in seen:
                seen[key] = sig
        logger.info("CH type_examples: %d types from %d signals", len(seen), len(self._signals))
        return [
            [sig.source_product, sig.source_type, sig.content, json.dumps({"extra": sig.extra}), sig.timestamp]
            for sig in seen.values()
        ]

    def count_signals(self, signal_ids: list[str]) -> int:
        """Return count for SignalsWaitForClickHouse."""
        stored_ids = {sig.signal_id for sig in self._signals if not sig.deleted}
        count = len(stored_ids & set(signal_ids))
        logger.info("CH wait: %d/%d signals found", count, len(signal_ids))
        return count


def _fake_database_sync_to_async(fn=None, *, thread_sensitive=True, executor=None):
    """Mock database_sync_to_async that wraps sync functions via sync_to_async."""
    if fn is None:
        return lambda f: sync_to_async(f, thread_sensitive=thread_sensitive)
    return sync_to_async(fn, thread_sensitive=thread_sensitive)


@pytest.fixture
def mock_temporal():
    """Mock Temporal infrastructure so _process_signal_batch runs as plain async code."""

    async def mock_execute_activity(fn, *args, **kwargs):
        return await fn(*args)

    async def fake_start_workflow(workflow_fn, workflow_input, *, start_signal_args=None, **kwargs):
        from products.signals.backend.temporal.grouping import _process_signal_batch

        if start_signal_args:
            signal_input = start_signal_args[0]
            await _process_signal_batch([signal_input])

    fake_client = AsyncMock()
    fake_client.start_workflow = fake_start_workflow

    async def fake_async_connect():
        return fake_client

    async def _fake_aget(*args, **kwargs):
        return SimpleNamespace(id=0, pk=0)

    with (
        patch("temporalio.workflow.execute_activity", mock_execute_activity),
        patch("temporalio.workflow.start_child_workflow", new_callable=AsyncMock),
        patch("temporalio.workflow.logger", logger),
        patch("temporalio.activity.heartbeat", lambda *a, **kw: None),
        patch("products.signals.backend.api.async_connect", fake_async_connect),
        patch("products.signals.backend.api.database_sync_to_async", _fake_database_sync_to_async),
        patch("products.signals.backend.temporal.grouping.database_sync_to_async", _fake_database_sync_to_async),
        patch("products.signals.backend.temporal.summary.database_sync_to_async", _fake_database_sync_to_async),
        # Activities look up team just to pass it to mocked functions — skip the DB hit
        patch.object(Team.objects, "aget", _fake_aget),
    ):
        yield


@pytest.fixture
def mock_clickhouse():
    store = InMemoryClickHouse()

    async def fake_hogql(*, query_type, query, team, placeholders=None, **kwargs):
        placeholders = placeholders or {}
        if query_type == "SignalsRunEmbeddingQuery":
            embedding = placeholders["embedding"].value
            limit = placeholders.get("limit", SimpleNamespace(value=10)).value
            return SimpleNamespace(results=store.cosine_search(embedding, limit))
        elif query_type == "SignalsFetchTypeExamples":
            return SimpleNamespace(results=store.get_type_examples())
        elif query_type == "SignalsFetchForReport":
            report_id = placeholders["report_id"].value
            return SimpleNamespace(results=store.get_signals_for_report(report_id))
        elif query_type == "SignalsWaitForClickHouse":
            signal_ids = placeholders["signal_ids"].value
            return SimpleNamespace(results=[[store.count_signals(signal_ids)]])
        return SimpleNamespace(results=[])

    def fake_emit_embedding(*, content, team_id, document_id, metadata, timestamp=None, **kwargs):
        embedding = store._embedding_cache.get(content, [])
        store.store_signal(
            signal_id=document_id,
            content=content,
            embedding=embedding,
            metadata=metadata,
            timestamp=str(timestamp) if timestamp else "",
        )

    async def _generate_embedding(team, content, **kwargs):
        import openai

        client = openai.AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
        response = await client.embeddings.create(
            model="text-embedding-3-small",
            input=content,
        )
        embedding = response.data[0].embedding
        store.cache_embedding(content, embedding)
        return SimpleNamespace(embedding=embedding)

    with (
        patch(
            "products.signals.backend.temporal.grouping.execute_hogql_query_with_retry",
            side_effect=fake_hogql,
        ),
        patch(
            "products.signals.backend.temporal.summary.execute_hogql_query_with_retry",
            side_effect=fake_hogql,
        ),
        patch(
            "products.signals.backend.temporal.grouping.emit_embedding_request",
            side_effect=fake_emit_embedding,
        ),
        patch(
            "products.signals.backend.api.SignalInput.model_validate",
        ),
        patch(
            "products.signals.backend.temporal.grouping.async_generate_embedding",
            side_effect=_generate_embedding,
        ),
    ):
        yield store


@pytest.fixture
def team(db):
    org = Organization.objects.create(name="eval", is_ai_data_processing_approved=True)
    project = Project.objects.create(id=Team.objects.increment_id_sequence(), organization=org)
    return Team.objects.create(id=project.id, project=project, organization=org)
