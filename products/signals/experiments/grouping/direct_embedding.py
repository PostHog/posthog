"""
Direct embedding strategy with dimension truncation.

Changes vs current_strategy:
1. Skips LLM query generation — searches with the signal's own embedding
2. Truncates embeddings to N dimensions (Matryoshka-style) before cosine search
3. Keeps the same LLM matching step for the final decision

Rationale (from embedding analysis):
- LLM-generated queries rank their source signal #1 86% of the time,
  but same-report signals only rank top-5 27% of the time.
  Queries are too specific to their source, not the group theme.
- Truncation to 128-256d preserves 97-99% of separability (Cohen's d)
  while widening the distance spread, making thresholds easier to set.
"""

import json
import uuid
import logging

import numpy as np
from current_strategy import MATCHING_SYSTEM_PROMPT, MatchFound, NewGroup, _build_matching_prompt
from harness import (
    EmbeddingCache,
    GroupingDecision,
    InMemorySignalStore,
    SignalCandidate,
    StoredSignal,
    TestSignal,
    call_llm_standalone,
)

logger = logging.getLogger(__name__)

TRUNCATION_DIMS = 128


def _truncate_and_normalize(embedding: list[float], dims: int) -> list[float]:
    """Truncate to first N dims and L2-normalize."""
    arr = np.array(embedding[:dims], dtype=np.float64)
    norm = np.linalg.norm(arr)
    if norm > 0:
        arr = arr / norm
    return arr.tolist()


def _search_truncated(
    store: InMemorySignalStore,
    query_embedding: list[float],
    dims: int,
    limit: int = 10,
) -> list[SignalCandidate]:
    """Search the store with truncated embeddings."""
    if store.signal_count == 0:
        return []

    q = np.array(query_embedding[:dims], dtype=np.float64)
    q_norm = np.linalg.norm(q)
    if q_norm == 0:
        return []
    q = q / q_norm

    distances: list[tuple[float, StoredSignal]] = []
    for sig in store._signals:
        sig_trunc = np.array(sig.embedding[:dims], dtype=np.float64)
        sig_norm = np.linalg.norm(sig_trunc)
        if sig_norm == 0:
            continue
        sig_trunc = sig_trunc / sig_norm
        cosine_dist = 1.0 - float(np.dot(q, sig_trunc))
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


class DirectEmbeddingStrategy:
    """Search with the signal's own embedding, truncated to N dimensions."""

    def __init__(self, dims: int = TRUNCATION_DIMS):
        self.dims = dims

    async def assign_signal(
        self,
        signal: TestSignal,
        signal_embedding: list[float],
        store: InMemorySignalStore,
        embedding_cache: EmbeddingCache,
    ) -> GroupingDecision:
        if store.signal_count == 0:
            report_id = str(uuid.uuid4())
            return GroupingDecision(
                report_id=report_id,
                is_new=True,
                title=signal.content[:75],
                reason="First signal, creating new group",
            )

        # Step 1: Search with signal's own embedding (truncated)
        candidates = _search_truncated(store, signal_embedding, self.dims, limit=10)
        logger.info("    Direct search (%dd): %d candidates", self.dims, len(candidates))

        if not candidates:
            report_id = str(uuid.uuid4())
            return GroupingDecision(
                report_id=report_id,
                is_new=True,
                title=signal.content[:75],
                reason="No candidates found in search",
            )

        # Step 2: LLM matching decision (same as current)
        # Present as a single "query" — the signal description itself
        all_candidates: dict[str, SignalCandidate] = {c.signal_id: c for c in candidates}
        queries = [signal.content[:200]]  # use signal content as the "query" for the prompt
        query_results = [candidates]

        matching_prompt = _build_matching_prompt(
            signal.content, signal.source_product, signal.source_type, queries, query_results
        )

        def validate_match(text: str) -> GroupingDecision:
            data = json.loads(text)
            match_type = data.get("match_type")
            if match_type == "existing":
                result = MatchFound.model_validate(data)
                matched = all_candidates.get(result.signal_id)
                if matched is None:
                    raise ValueError(f"signal_id {result.signal_id} not found in candidates")
                return GroupingDecision(
                    report_id=matched.report_id,
                    is_new=False,
                    title=None,
                    reason=result.reason,
                )
            elif match_type == "new":
                result = NewGroup.model_validate(data)
                return GroupingDecision(
                    report_id=str(uuid.uuid4()),
                    is_new=True,
                    title=result.title,
                    reason=result.reason,
                )
            else:
                raise ValueError(f"Invalid match_type: {match_type}")

        return await call_llm_standalone(
            system_prompt=MATCHING_SYSTEM_PROMPT,
            user_prompt=matching_prompt,
            validate=validate_match,
            temperature=0.2,
        )
