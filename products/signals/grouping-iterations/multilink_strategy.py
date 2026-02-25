"""
Multi-link verification strategy.

Uses the current signal-to-signal matching for discovery, then verifies
matches by generating "verification queries" from the new signal's perspective
and checking whether they independently find OTHER members of the target group
(not just the bridge signal that was matched).

This directly tests transitivity: if signal C matched signal B in group G,
can C also find signals A, D, E in group G from different angles? If not,
C is only connected through the bridge (B) and the match is weak.

Flow:
1. Generate queries, embed, cosine search, LLM match — same as current_strategy
2. If matched to a group with 2+ signals → multi-link verification:
   - Generate 2-3 "verification queries" via LLM (given new signal + group context)
   - Embed and search each verification query
   - Check: do any queries find group members OTHER than the bridge signal?
   - Yes (1+ queries find non-bridge members) → confirm match
   - No → weak bridge, create new group
3. If matched to a 1-signal group → skip verification (cold-start tolerance)
"""

import json
import uuid
import logging

from current_strategy import (
    MATCHING_SYSTEM_PROMPT,
    MAX_QUERY_TOKENS,
    MatchFound,
    NewGroup,
    QueryGenerationResponse,
    _build_matching_prompt,
    _build_query_generation_system_prompt,
)
from harness import (
    EmbeddingCache,
    GroupingDecision,
    InMemorySignalStore,
    SignalCandidate,
    StoredSignal,
    TestSignal,
    call_llm_standalone,
)
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

MAX_SIGNALS_IN_CONTEXT = 8
VERIFICATION_SEARCH_LIMIT = 15


# --- Verification query generation ---


class VerificationQueriesResponse(BaseModel):
    queries: list[str] = Field(min_length=1, max_length=3)


VERIFICATION_QUERY_SYSTEM_PROMPT = """You are a signal grouping verification assistant. A matching system has proposed adding a new signal to an existing group. Your job is to generate search queries that test whether this connection is genuine or just a surface-level keyword bridge.

You will receive:
1. The new signal being added
2. The group it's being matched to (title + existing signals)
3. The bridge signal — the specific signal in the group that the new signal matched

Generate 2-3 search queries that explore DIFFERENT aspects of how the new signal relates to the GROUP'S overall theme (not just the bridge signal). Each query should approach the connection from a different angle:

1. The specific technical component or feature area the group addresses
2. The type of problem or user need the group represents
3. The business impact or user journey the group affects

IMPORTANT: Your queries should be designed to find OTHER signals in the group, NOT the bridge signal. If the new signal is only connected to the group through one thin keyword bridge, your queries should fail to find other group members — that's the desired outcome.

Keep queries concise (max {max_query_tokens} tokens each). Respond with a JSON object containing a "queries" array with 2-3 query strings. Return ONLY valid JSON, no other text."""


def _build_verification_query_prompt(
    new_signal: TestSignal,
    bridge_signal: StoredSignal,
    group_title: str | None,
    group_signals: list[StoredSignal],
) -> str:
    prompt = f"""NEW SIGNAL:
- Source: {new_signal.source_product} / {new_signal.source_type}
- Description: {new_signal.content}

MATCHED GROUP:
- Title: {group_title or "(untitled)"}
- Signals in group ({len(group_signals)} total):
"""
    for i, sig in enumerate(group_signals[:MAX_SIGNALS_IN_CONTEXT]):
        is_bridge = " [BRIDGE SIGNAL]" if sig.signal_id == bridge_signal.signal_id else ""
        prompt += f"""
  Signal {i + 1}{is_bridge}:
  - Source: {sig.source_product} / {sig.source_type}
  - Description: {sig.content[:500]}
"""
    remaining = len(group_signals) - MAX_SIGNALS_IN_CONTEXT
    if remaining > 0:
        prompt += f"\n  ... and {remaining} more signals\n"

    prompt += f"""
BRIDGE SIGNAL (the one that matched):
- signal_id: {bridge_signal.signal_id}
- Description: {bridge_signal.content[:500]}

Generate 2-3 queries that would find the OTHER signals in this group (not the bridge signal) if the new signal genuinely belongs here."""
    return prompt


# --- Strategy implementation ---


class MultiLinkStrategy:
    """Current strategy + multi-link verification for reports with 2+ signals."""

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

        # Step 1: Generate search queries (same as current)
        type_examples = store.get_type_examples()
        system_prompt = _build_query_generation_system_prompt(type_examples)
        user_prompt = f"""NEW SIGNAL:
- Source: {signal.source_product} / {signal.source_type}
- Description: {signal.content}"""

        def validate_queries(text: str) -> list[str]:
            data = json.loads(text)
            result = QueryGenerationResponse.model_validate(data)
            return [q[: MAX_QUERY_TOKENS * 4] for q in result.queries]

        queries = await call_llm_standalone(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            validate=validate_queries,
            temperature=0.7,
        )
        logger.info("    Queries: %s", queries)

        # Step 2: Embed and search
        query_embeddings = embedding_cache.embed_batch(queries)
        query_results: list[list[SignalCandidate]] = []
        for q_emb in query_embeddings:
            candidates = store.search(q_emb, limit=10)
            query_results.append(candidates)

        # Step 3: LLM matching (same as current — signal-to-signal)
        all_candidates: dict[str, SignalCandidate] = {}
        for candidates in query_results:
            for c in candidates:
                all_candidates[c.signal_id] = c

        if not all_candidates:
            report_id = str(uuid.uuid4())
            return GroupingDecision(
                report_id=report_id,
                is_new=True,
                title=signal.content[:75],
                reason="No candidates found in search",
            )

        matching_prompt = _build_matching_prompt(
            signal.content, signal.source_product, signal.source_type, queries, query_results
        )

        matched_signal_id: str = ""

        def validate_match(text: str) -> GroupingDecision:
            nonlocal matched_signal_id
            data = json.loads(text)
            match_type = data.get("match_type")
            if match_type == "existing":
                result = MatchFound.model_validate(data)
                matched = all_candidates.get(result.signal_id)
                if matched is None:
                    raise ValueError(f"signal_id {result.signal_id} not found in candidates")
                if result.query_index < 0 or result.query_index >= len(queries):
                    raise ValueError(f"query_index {result.query_index} out of range")
                matched_signal_id = result.signal_id
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

        decision = await call_llm_standalone(
            system_prompt=MATCHING_SYSTEM_PROMPT,
            user_prompt=matching_prompt,
            validate=validate_match,
            temperature=0.2,
        )

        # Step 4: Multi-link verification (only for existing matches to 2+ signal groups)
        if not decision.is_new:
            group_signals = store.get_signals_for_report(decision.report_id)
            if len(group_signals) >= 2:
                logger.info(
                    "    Multi-link verification: group has %d signals, checking transitive links...",
                    len(group_signals),
                )

                bridge_signal = next(
                    (s for s in group_signals if s.signal_id == matched_signal_id),
                    group_signals[0],
                )
                group_title = store.get_report_title(decision.report_id)

                # Generate verification queries
                verification_prompt = _build_verification_query_prompt(
                    new_signal=signal,
                    bridge_signal=bridge_signal,
                    group_title=group_title,
                    group_signals=group_signals,
                )

                def validate_verification_queries(text: str) -> list[str]:
                    data = json.loads(text)
                    result = VerificationQueriesResponse.model_validate(data)
                    return [q[: MAX_QUERY_TOKENS * 4] for q in result.queries]

                verification_queries = await call_llm_standalone(
                    system_prompt=VERIFICATION_QUERY_SYSTEM_PROMPT.format(max_query_tokens=MAX_QUERY_TOKENS),
                    user_prompt=verification_prompt,
                    validate=validate_verification_queries,
                    temperature=0.7,
                )
                logger.info("    Verification queries: %s", verification_queries)

                # Embed and search verification queries
                v_embeddings = embedding_cache.embed_batch(verification_queries)

                group_signal_ids = {s.signal_id for s in group_signals}
                non_bridge_ids = group_signal_ids - {matched_signal_id}

                links_found = 0
                for v_idx, v_emb in enumerate(v_embeddings):
                    v_results = store.search(v_emb, limit=VERIFICATION_SEARCH_LIMIT)
                    found_non_bridge = [r for r in v_results if r.signal_id in non_bridge_ids]
                    if found_non_bridge:
                        links_found += 1
                        best = found_non_bridge[0]
                        logger.info(
                            "    Verification query %d: found non-bridge member %s (dist=%.4f)",
                            v_idx,
                            best.signal_id[:12],
                            best.distance,
                        )
                    else:
                        logger.info("    Verification query %d: no non-bridge group members found", v_idx)

                logger.info(
                    "    Multi-link result: %d/%d queries found non-bridge members",
                    links_found,
                    len(verification_queries),
                )

                if links_found == 0:
                    logger.info("    REJECTED: no transitive links, creating new group")
                    return GroupingDecision(
                        report_id=str(uuid.uuid4()),
                        is_new=True,
                        title=signal.content[:75],
                        reason=f"Multi-link rejected: 0/{len(verification_queries)} verification queries found non-bridge group members",
                    )
                else:
                    logger.info("    CONFIRMED: %d transitive links found", links_found)
            else:
                logger.info("    Skipping verification: group has only %d signal(s)", len(group_signals))

        return decision
