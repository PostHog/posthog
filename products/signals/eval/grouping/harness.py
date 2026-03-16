"""
In-memory grouping harness for iterating on signal grouping strategies.

Provides:
- EmbeddingCache: OpenAI embeddings with disk caching
- InMemorySignalStore: replaces ClickHouse for cosine search
- GroupingStrategy protocol: interface for pluggable strategies
- run_harness(): sequential signal processing loop
- call_llm_standalone(): Anthropic LLM calls without PostHog dependencies
"""

import os
import json
import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, TypeVar

import numpy as np
import openai
import anthropic
from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(usecwd=True))

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parent / "cache"
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMS = 1536
LLM_MODEL = "claude-sonnet-4-5"
LLM_MAX_RETRIES = 3
LLM_MAX_RESPONSE_TOKENS = 4096


# --- Test signal data types ---


@dataclass
class TestSignal:
    signal_id: str
    content: str
    source_product: str
    source_type: str
    source_id: str
    weight: float
    timestamp: str
    original_report_id: str
    extra: dict = field(default_factory=dict)


@dataclass
class GroupingDecision:
    report_id: str
    is_new: bool
    title: str | None
    reason: str


@dataclass
class GroupInfo:
    report_id: str
    title: str | None
    signal_ids: list[str] = field(default_factory=list)


@dataclass
class GroupingResult:
    groups: dict[str, GroupInfo]  # report_id -> GroupInfo
    decisions: list[tuple[TestSignal, GroupingDecision]]  # (signal, decision) pairs
    signals: list[TestSignal]  # original signals in processing order


def load_test_signals(path: Path | None = None) -> list[TestSignal]:
    """Load test signals from the prepared JSON file."""
    if path is None:
        path = Path(__file__).resolve().parent / "data" / "test_signals.json"
    with open(path) as f:
        data = json.load(f)
    return [TestSignal(**s) for s in data]


# --- Embedding cache ---


class EmbeddingCache:
    """Generate and cache OpenAI embeddings to disk."""

    def __init__(self, cache_path: Path | None = None):
        self._cache_path = cache_path or (CACHE_DIR / "embeddings.json")
        self._cache: dict[str, list[float]] = {}
        self._client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        self._load()

    def _load(self):
        if self._cache_path.exists():
            try:
                with open(self._cache_path) as f:
                    self._cache = json.load(f)
                logger.info("Loaded %d cached embeddings", len(self._cache))
            except (json.JSONDecodeError, ValueError):
                logger.warning("Cache file corrupted (likely from concurrent writes), starting fresh")
                self._cache = {}

    def _save(self):
        os.makedirs(self._cache_path.parent, exist_ok=True)
        with open(self._cache_path, "w") as f:
            json.dump(self._cache, f)

    @staticmethod
    def _key(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()

    def get(self, text: str) -> list[float] | None:
        return self._cache.get(self._key(text))

    def embed(self, text: str) -> list[float]:
        """Get embedding for text, using cache or generating via API."""
        key = self._key(text)
        if key in self._cache:
            return self._cache[key]

        response = self._client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=text,
        )
        embedding = response.data[0].embedding
        self._cache[key] = embedding
        self._save()
        return embedding

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts, using cache where possible."""
        results: list[list[float] | None] = [None] * len(texts)
        uncached: list[tuple[int, str]] = []

        for i, text in enumerate(texts):
            cached = self.get(text)
            if cached is not None:
                results[i] = cached
            else:
                uncached.append((i, text))

        if uncached:
            batch_texts = [t for _, t in uncached]
            response = self._client.embeddings.create(
                model=EMBEDDING_MODEL,
                input=batch_texts,
            )
            for batch_idx, (orig_idx, text) in enumerate(uncached):
                embedding = response.data[batch_idx].embedding
                self._cache[self._key(text)] = embedding
                results[orig_idx] = embedding
            self._save()

        return results  # type: ignore


# --- In-memory signal store (replaces ClickHouse) ---


@dataclass
class StoredSignal:
    signal_id: str
    content: str
    embedding: np.ndarray
    report_id: str
    source_product: str
    source_type: str
    source_id: str
    weight: float
    timestamp: str


# Reuse the SignalCandidate type from the existing codebase
@dataclass
class SignalCandidate:
    signal_id: str
    report_id: str
    content: str
    source_product: str
    source_type: str
    distance: float


@dataclass
class SignalTypeExample:
    source_product: str
    source_type: str
    content: str
    timestamp: str
    extra: dict = field(default_factory=dict)


class InMemorySignalStore:
    """In-memory store for signals with cosine distance search."""

    def __init__(self):
        self._signals: list[StoredSignal] = []
        self._report_titles: dict[str, str | None] = {}

    def add_signal(
        self,
        signal_id: str,
        content: str,
        embedding: list[float],
        report_id: str,
        source_product: str,
        source_type: str,
        source_id: str = "",
        weight: float = 1.0,
        timestamp: str = "",
        title: str | None = None,
    ):
        self._signals.append(
            StoredSignal(
                signal_id=signal_id,
                content=content,
                embedding=np.array(embedding, dtype=np.float64),
                report_id=report_id,
                source_product=source_product,
                source_type=source_type,
                source_id=source_id,
                weight=weight,
                timestamp=timestamp,
            )
        )
        if title and report_id not in self._report_titles:
            self._report_titles[report_id] = title

    def search(self, query_embedding: list[float], limit: int = 10) -> list[SignalCandidate]:
        """Find nearest neighbors by cosine distance."""
        if not self._signals:
            return []

        q = np.array(query_embedding, dtype=np.float64)
        q_norm = np.linalg.norm(q)
        if q_norm == 0:
            return []

        distances: list[tuple[float, StoredSignal]] = []
        for sig in self._signals:
            sig_norm = np.linalg.norm(sig.embedding)
            if sig_norm == 0:
                continue
            cosine_dist = 1.0 - float(np.dot(q, sig.embedding) / (q_norm * sig_norm))
            distances.append((cosine_dist, sig))

        distances.sort(key=lambda x: x[0])

        return [
            SignalCandidate(
                signal_id=sig.signal_id,
                report_id=sig.report_id,
                content=sig.content,
                source_product=sig.source_product,
                source_type=sig.source_type,
                distance=dist,
            )
            for dist, sig in distances[:limit]
        ]

    def get_type_examples(self) -> list[SignalTypeExample]:
        """Get one example per unique (source_product, source_type) pair."""
        seen: dict[tuple[str, str], StoredSignal] = {}
        for sig in self._signals:
            key = (sig.source_product, sig.source_type)
            if key not in seen or sig.timestamp > seen[key].timestamp:
                seen[key] = sig

        return [
            SignalTypeExample(
                source_product=sig.source_product,
                source_type=sig.source_type,
                content=sig.content,
                timestamp=sig.timestamp,
            )
            for sig in seen.values()
        ]

    def get_report_ids(self) -> set[str]:
        return {sig.report_id for sig in self._signals}

    def get_signals_for_report(self, report_id: str) -> list[StoredSignal]:
        return [sig for sig in self._signals if sig.report_id == report_id]

    def get_report_title(self, report_id: str) -> str | None:
        return self._report_titles.get(report_id)

    @property
    def signal_count(self) -> int:
        return len(self._signals)


# --- Standalone LLM call (bypasses PostHog analytics) ---
# Source: products/signals/backend/temporal/llm.py (call_llm, _extract_text_content, _strip_markdown_json_fences)


T = TypeVar("T")


def _extract_text_content(response) -> str:
    for block in reversed(response.content):
        if block.type == "text":
            return block.text
    raise ValueError("No text content in response")


def _strip_markdown_json_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```json") and stripped.endswith("```"):
        return stripped[len("```json") : -len("```")].strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        return stripped[len("```") : -len("```")].strip()
    return text


async def call_llm_standalone(
    *,
    system_prompt: str,
    user_prompt: str,
    validate: Callable[[str], T],
    temperature: float = 0.2,
    retries: int = LLM_MAX_RETRIES,
    model: str = LLM_MODEL,
    max_tokens: int = LLM_MAX_RESPONSE_TOKENS,
) -> T:
    """
    Standalone LLM call matching the production call_llm() pattern.

    Same retry/validate/prefill logic as products.signals.backend.temporal.llm.call_llm
    but uses a plain Anthropic client (no PostHog analytics wrapper).
    """
    client = anthropic.AsyncAnthropic(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        timeout=100.0,
    )

    messages: list[anthropic.types.MessageParam] = [
        {"role": "user", "content": user_prompt},
        {"role": "assistant", "content": "{"},
    ]

    last_exception: Exception | None = None
    for attempt in range(retries):
        response = await client.messages.create(
            model=model,
            system=system_prompt,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        text_content = _extract_text_content(response)
        text_content = _strip_markdown_json_fences(text_content)
        text_content = "{" + text_content

        try:
            return validate(text_content)
        except Exception as e:
            logger.warning("LLM validation failed (attempt %d/%d): %s", attempt + 1, retries, e)
            messages.append({"role": "assistant", "content": response.content})
            messages.append(
                {
                    "role": "user",
                    "content": f"Your previous response failed validation. Error: {e}\n\nPlease try again with a valid JSON response.",
                }
            )
            messages.append({"role": "assistant", "content": "{"})
            last_exception = e

    raise last_exception or ValueError(f"LLM call failed after {retries} attempts")


# --- Grouping strategy protocol ---


class GroupingStrategy(Protocol):
    async def assign_signal(
        self,
        signal: TestSignal,
        signal_embedding: list[float],
        store: InMemorySignalStore,
        embedding_cache: EmbeddingCache,
    ) -> GroupingDecision: ...


# --- Harness runner ---


async def run_harness(
    strategy: GroupingStrategy,
    signals: list[TestSignal],
    embedding_cache: EmbeddingCache,
) -> GroupingResult:
    """Process signals sequentially through a grouping strategy."""
    store = InMemorySignalStore()
    groups: dict[str, GroupInfo] = {}
    decisions: list[tuple[TestSignal, GroupingDecision]] = []

    logger.info("Processing %d signals", len(signals))

    # Pre-embed all signal content for efficiency
    logger.info("Generating embeddings...")
    all_embeddings = embedding_cache.embed_batch([s.content for s in signals])
    logger.info("%d embeddings ready", len(all_embeddings))

    for i, (signal, embedding) in enumerate(zip(signals, all_embeddings)):
        content_preview = signal.content[:80].replace("\n", " ")
        logger.info("[%d/%d] %s...", i + 1, len(signals), content_preview)

        decision = await strategy.assign_signal(signal, embedding, store, embedding_cache)

        # Update store
        store.add_signal(
            signal_id=signal.signal_id,
            content=signal.content,
            embedding=embedding,
            report_id=decision.report_id,
            source_product=signal.source_product,
            source_type=signal.source_type,
            source_id=signal.source_id,
            weight=signal.weight,
            timestamp=signal.timestamp,
            title=decision.title,
        )

        # Update groups
        if decision.report_id not in groups:
            groups[decision.report_id] = GroupInfo(
                report_id=decision.report_id,
                title=decision.title,
            )
        groups[decision.report_id].signal_ids.append(signal.signal_id)
        if decision.title and not groups[decision.report_id].title:
            groups[decision.report_id].title = decision.title

        decisions.append((signal, decision))

        action = "NEW GROUP" if decision.is_new else f"MATCHED -> {decision.report_id[:12]}..."
        logger.info("  -> %s | %s", action, decision.reason[:60])

    return GroupingResult(groups=groups, decisions=decisions, signals=signals)


def format_grouping_result(result: GroupingResult) -> str:
    """Format a readable summary of grouping results."""
    lines: list[str] = []
    lines.append(f"GROUPING RESULTS: {len(result.groups)} groups from {len(result.signals)} signals")
    lines.append("")

    signal_lookup = {s.signal_id: s for s in result.signals}

    for group in sorted(result.groups.values(), key=lambda g: -len(g.signal_ids)):
        lines.append(f"Group: {group.report_id[:12]}... ({len(group.signal_ids)} signals)")
        if group.title:
            lines.append(f"  Title: {group.title}")

        orig_reports: dict[str, int] = {}
        for sid in group.signal_ids:
            sig = signal_lookup.get(sid)
            if sig:
                orig_reports.setdefault(sig.original_report_id[:12], 0)
                orig_reports[sig.original_report_id[:12]] += 1

        lines.append(f"  Original reports: {dict(orig_reports)}")

        for sid in group.signal_ids:
            sig = signal_lookup.get(sid)
            if sig:
                preview = sig.content[:100].replace("\n", " ")
                lines.append(f"    - [{sig.source_product}/{sig.source_type}] {preview}")
        lines.append("")

    return "\n".join(lines)
