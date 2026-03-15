import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from products.signals.backend.temporal.types import (
    ExistingReportMatch,
    MatchResult,
    ReportContext,
    SignalCandidate,
    SignalData,
    SignalTypeExample,
)

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
    timestamp: datetime
    extra: dict = field(default_factory=dict)
    deleted: bool = False


class EmbeddingStore:
    """Replaces ClickHouse — stores signal content + embeddings for vector search.

    Generates real embeddings via OpenAI, stores them immediately (no fire-and-forget),
    and supports cosine search against stored signals.
    """

    CACHE_PATH = Path(__file__).parent / "cache" / "embeddings.json"

    def __init__(self, openai_client):
        self._signals: list[StoredSignal] = []
        self._embedding_cache: dict[str, list[float]] = self._load_disk_cache()
        self._client = openai_client

    def _load_disk_cache(self) -> dict[str, list[float]]:
        if self.CACHE_PATH.exists():
            with open(self.CACHE_PATH) as f:
                return json.load(f)
        return {}

    def _save_disk_cache(self) -> None:
        self.CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(self.CACHE_PATH, "w") as f:
            json.dump(self._embedding_cache, f)

    async def embed(self, content: str) -> list[float]:
        """Generate and cache an embedding. Returns cached result if available."""
        if content in self._embedding_cache:
            return self._embedding_cache[content]
        response = await self._client.embeddings.create(
            model="text-embedding-3-small",
            input=content,
        )
        embedding = response.data[0].embedding
        self._embedding_cache[content] = embedding
        self._save_disk_cache()
        return embedding

    def store(
        self,
        signal_id: str,
        content: str,
        embedding: list[float],
        report_id: str,
        source_product: str,
        source_type: str,
        source_id: str,
        weight: float,
        extra: dict | None = None,
        timestamp: datetime | None = None,
        deleted: bool = False,
    ) -> None:
        """Immediately store a signal with its embedding."""
        ts = timestamp or datetime.now(UTC)
        logger.info(
            "store: signal=%s report=%s product=%s deleted=%s content=%.80s",
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
                source_type=source_type,
                source_id=source_id,
                weight=weight,
                timestamp=ts,
                extra=extra or {},
                deleted=deleted,
            )
        )

    def search(self, query_embedding: list[float], limit: int = 10) -> list[SignalCandidate]:
        """Cosine search against stored signals. Returns SignalCandidate list."""
        searchable = [s for s in self._signals if not s.deleted and s.report_id and np.linalg.norm(s.embedding) > 0]
        if not searchable:
            return []

        q = np.array(query_embedding, dtype=np.float64)
        q_norm = np.linalg.norm(q)
        if q_norm == 0:
            return []

        scored: list[tuple[float, StoredSignal]] = []
        for sig in searchable:
            s = np.array(sig.embedding, dtype=np.float64)
            dist = 1.0 - float(np.dot(q, s) / (q_norm * np.linalg.norm(s)))
            scored.append((dist, sig))

        scored.sort(key=lambda x: x[0])
        return [
            SignalCandidate(
                signal_id=sig.signal_id,
                report_id=sig.report_id,
                content=sig.content,
                source_product=sig.source_product,
                source_type=sig.source_type,
                distance=dist,
            )
            for dist, sig in scored[:limit]
        ]

    def get_signals_for_report(self, report_id: str) -> list[SignalData]:
        """Fetch all non-deleted signals for a report."""
        return [
            SignalData(
                signal_id=sig.signal_id,
                content=sig.content,
                source_product=sig.source_product,
                source_type=sig.source_type,
                source_id=sig.source_id,
                weight=sig.weight,
                timestamp=sig.timestamp,
                extra=sig.extra,
            )
            for sig in self._signals
            if sig.report_id == report_id and not sig.deleted
        ]

    def get_type_examples(self) -> list[SignalTypeExample]:
        """Return one example signal per unique (source_product, source_type) pair."""
        seen: dict[tuple[str, str], StoredSignal] = {}
        for sig in self._signals:
            if sig.deleted:
                continue
            key = (sig.source_product, sig.source_type)
            if key not in seen:
                seen[key] = sig
        return [
            SignalTypeExample(
                source_product=sig.source_product,
                source_type=sig.source_type,
                content=sig.content,
                timestamp=sig.timestamp.isoformat(),
                extra=sig.extra,
            )
            for sig in seen.values()
        ]

    @property
    def signal_count(self) -> int:
        return len(self._signals)

    @property
    def active_signals(self) -> list[StoredSignal]:
        return [s for s in self._signals if not s.deleted]


@dataclass
class StoredReport:
    context: ReportContext
    true_signal_groups: list[int]
    true_group_index: int
    safety_choice: bool | None = None  # True = safe, False = unsafe, None = not yet judged


class ReportStore:
    """Replaces Postgres — stores report metadata for LLM context, plus ground-truth labels for eval."""

    def __init__(self):
        self._store: dict[str, StoredReport] = {}

    def all_reports(self) -> list[StoredReport]:
        return list(self._store.values())

    def get_contexts(self) -> dict[str, ReportContext]:
        return {k: v.context for k, v in self._store.items()}

    def get(self, report_id: str) -> StoredReport:
        return self._store[report_id]

    def find_report_by_group_index(self, group_index: int) -> StoredReport | None:
        """Find the report with the most members of the given ground-truth group."""
        best: StoredReport | None = None
        best_count = 0
        for report in self._store.values():
            count = report.true_signal_groups.count(group_index)
            if count > best_count:
                best_count = count
                best = report
        return best

    def insert(self, report_id: str, match_result: MatchResult, group_index: int) -> None:
        """Update report context after a match result, mirroring the workflow batch logic."""

        if isinstance(match_result, ExistingReportMatch):
            r = self._store[report_id]
            old_ctx = r.context
            r.context = ReportContext(
                report_id=report_id,
                title=old_ctx.title if old_ctx else "",
                signal_count=(old_ctx.signal_count if old_ctx else 0) + 1,
            )
            r.true_signal_groups.append(group_index)

            if r.true_signal_groups.count(group_index) > r.true_signal_groups.count(r.true_group_index):
                r.true_group_index = group_index

        else:
            self._store[report_id] = StoredReport(
                context=ReportContext(
                    report_id=report_id,
                    title=match_result.title,
                    signal_count=1,
                ),
                true_signal_groups=[group_index],
                true_group_index=group_index,
            )
