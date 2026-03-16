"""
PR-specificity verification strategy.

Uses the current signal-to-signal matching for discovery, then verifies
matches by asking the LLM to write a single PR title that covers ALL signals
in the target group plus the new one. If the PR title is too broad to be
shipped by one engineer in one pull request, the match is rejected.

This directly tests group coherence: weak-chained groups can't produce a
specific PR title — "Fix various PostHog AI issues" is obviously too broad.

Flow:
1. Generate queries, embed, cosine search, LLM match — same as current_strategy
2. If matched to any existing group → PR-specificity check:
   - One LLM call: "write a PR title covering all signals + new one; is it specific enough?"
   - If specific_enough: true → confirm match
   - If specific_enough: false → reject, create new group
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
from pydantic import BaseModel

logger = logging.getLogger(__name__)

MAX_SIGNALS_IN_CONTEXT = 8


# --- PR-specificity check ---


class SpecificityResult(BaseModel):
    pr_title: str
    specific_enough: bool
    reason: str


SPECIFICITY_CHECK_SYSTEM_PROMPT = """You are a senior engineer reviewing whether a group of signals belongs in a single pull request.

You will receive:
1. A group of existing signals (the current report)
2. A new signal being proposed for addition

Your job:
1. Write a single PR title (max 70 chars) that covers ALL signals in the group INCLUDING the new one.
2. Judge: is this PR title specific enough that one engineer could ship it in a single pull request?

A SPECIFIC PR title targets one feature, one bug, one component, or one tightly-scoped change:
- "Fix date picker timezone handling in insights" — SPECIFIC (one component, one bug type)
- "Add K8s liveness probe and fix feature flag caching" — SPECIFIC (one infra concern, tightly related)
- "Fix funnel conversion calculation for time-based bins" — SPECIFIC (one feature, one issue)

A VAGUE PR title is a catch-all that no single engineer would take on:
- "Fix various PostHog AI issues" — VAGUE (multiple unrelated areas)
- "Multiple workflow and integration improvements" — VAGUE (different systems)
- "Address feature flag and authentication concerns" — VAGUE (unrelated domains)

IMPORTANT: Err on the side of REJECTING. A good PR addresses ONE concern, even if that concern has multiple symptoms.

Red flags that the group is too broad:
- You need words like "various", "multiple", "and" (connecting unrelated things), or "improvements"
- The signals share a keyword (e.g. "workflows", "flags", "Next.js") but address different problems
- You'd assign the signals to different engineers based on expertise
- The PR touches multiple unrelated systems or components

Respond with valid JSON only:
{"pr_title": "...", "specific_enough": true/false, "reason": "..."}"""


def _build_specificity_prompt(
    new_signal: TestSignal,
    group_title: str | None,
    group_signals: list[StoredSignal],
) -> str:
    prompt = f"""EXISTING GROUP:
- Title: {group_title or "(untitled)"}
- Signals ({len(group_signals)} total):
"""
    for i, sig in enumerate(group_signals[:MAX_SIGNALS_IN_CONTEXT]):
        prompt += f"""
  Signal {i + 1}:
  - Source: {sig.source_product} / {sig.source_type}
  - Description: {sig.content[:500]}
"""
    remaining = len(group_signals) - MAX_SIGNALS_IN_CONTEXT
    if remaining > 0:
        prompt += f"\n  ... and {remaining} more signals\n"

    prompt += f"""
NEW SIGNAL PROPOSED FOR ADDITION:
- Source: {new_signal.source_product} / {new_signal.source_type}
- Description: {new_signal.content}

Write a PR title covering ALL the above signals (existing + new), then judge if it's specific enough for one pull request."""
    return prompt


# --- Strategy implementation ---


class PRSpecificityStrategy:
    """Current strategy + PR-specificity verification for reports with 2+ signals."""

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

        def validate_match(text: str) -> GroupingDecision:
            data = json.loads(text)
            match_type = data.get("match_type")
            if match_type == "existing":
                result = MatchFound.model_validate(data)
                matched = all_candidates.get(result.signal_id)
                if matched is None:
                    raise ValueError(f"signal_id {result.signal_id} not found in candidates")
                if result.query_index < 0 or result.query_index >= len(queries):
                    raise ValueError(f"query_index {result.query_index} out of range")
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

        # Step 4: PR-specificity verification (all existing matches, no cold-start skip)
        if not decision.is_new:
            group_signals = store.get_signals_for_report(decision.report_id)
            logger.info(
                "    PR-specificity check: group has %d signals, verifying scope...",
                len(group_signals),
            )

            group_title = store.get_report_title(decision.report_id)
            specificity_prompt = _build_specificity_prompt(
                new_signal=signal,
                group_title=group_title,
                group_signals=group_signals,
            )

            def validate_specificity(text: str) -> SpecificityResult:
                data = json.loads(text)
                return SpecificityResult.model_validate(data)

            specificity = await call_llm_standalone(
                system_prompt=SPECIFICITY_CHECK_SYSTEM_PROMPT,
                user_prompt=specificity_prompt,
                validate=validate_specificity,
                temperature=0.2,
            )

            logger.info(
                '    PR title: "%s" | specific_enough: %s | reason: %s',
                specificity.pr_title,
                specificity.specific_enough,
                specificity.reason,
            )

            if not specificity.specific_enough:
                logger.info("    REJECTED: PR title too broad, creating new group")
                return GroupingDecision(
                    report_id=str(uuid.uuid4()),
                    is_new=True,
                    title=signal.content[:75],
                    reason=f'PR-specificity rejected: "{specificity.pr_title}" — {specificity.reason}',
                )
            else:
                logger.info("    CONFIRMED: PR title is specific enough")

        return decision
