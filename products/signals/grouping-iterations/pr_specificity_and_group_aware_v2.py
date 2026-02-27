"""
PR-specificity + group-aware matching strategy v2.

Same architecture as v1 (`pr_specificity_and_group_aware.py`), but with a softened
specificity prompt that shifts the default from "reject unless clearly related" to
"accept when same area, reject when unrelated systems."

Change from v1: only the SPECIFICITY_CHECK_SYSTEM_PROMPT is different.
See: products/signals/grouping-iterations/runs/group_aware_specificity_20260227_231106_analysis.md

v1 had ~16 rejections where ~5-8 would be appropriate. The three compounding
strictness signals in v1's prompt are replaced with explicit ACCEPT/REJECT criteria.
"""

import json
import uuid
import logging

from current_strategy import (
    MAX_QUERY_TOKENS,
    MatchFound,
    NewGroup,
    QueryGenerationResponse,
    _build_query_generation_system_prompt,
)
from harness import (
    EmbeddingCache,
    GroupingDecision,
    InMemorySignalStore,
    SignalCandidate,
    TestSignal,
    call_llm_standalone,
)
from pr_specificity_and_group_aware import GROUP_AWARE_MATCHING_SYSTEM_PROMPT, _build_group_aware_matching_prompt
from pr_specificity_strategy import SpecificityResult, _build_specificity_prompt

logger = logging.getLogger(__name__)


# --- Softened specificity prompt (only change from v1) ---
# Source: products/signals/grouping-iterations/runs/group_aware_specificity_20260227_231106_analysis.md

SPECIFICITY_CHECK_SYSTEM_PROMPT_V2 = """You are a senior engineer reviewing whether a group of signals belongs in a single pull request.

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

A good PR addresses ONE concern, even if that concern has multiple symptoms or touches multiple files.

ACCEPT when:
- The signals address the same component, feature, or system even if they describe different symptoms
- A single engineer working on that area would naturally fix both issues together
- The signals describe the same bug reported by different users
- The signals are a bug fix + closely related improvement in the same area (e.g. "fix NaN display" + "redesign metrics overview" for the same screen)

REJECT when:
- The signals address genuinely unrelated systems (e.g. .NET SDK + Next.js integration)
- You need words like "various", "multiple", or "improvements" because the signals have nothing in common besides a keyword
- The PR would touch completely separate codebases or repositories

Respond with valid JSON only:
{"pr_title": "...", "specific_enough": true/false, "reason": "..."}"""


# --- Strategy implementation ---


class PRSpecificityAndGroupAwareV2Strategy:
    """PR-specificity v2 + group-aware matching + softened specificity prompt."""

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

        # Step 3: Group-aware LLM matching
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

        matching_prompt = _build_group_aware_matching_prompt(
            signal.content, signal.source_product, signal.source_type, queries, query_results, store
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
            system_prompt=GROUP_AWARE_MATCHING_SYSTEM_PROMPT,
            user_prompt=matching_prompt,
            validate=validate_match,
            temperature=0.2,
        )

        # Step 4: PR-specificity verification with SOFTENED prompt
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
                system_prompt=SPECIFICITY_CHECK_SYSTEM_PROMPT_V2,  # <-- only change from v1
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

            # Step 5: Update group title with the synthesized PR title (feedback loop)
            store._report_titles[decision.report_id] = specificity.pr_title
            logger.info("    CONFIRMED: updated group title to: %s", specificity.pr_title)

        return decision
