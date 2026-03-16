"""
PR-specificity + group-aware matching strategy.

Builds on PR-specificity v2 with two enhancements to the matching step:

1. Group-title context: each search result candidate is annotated with the title
   and size of its group, so the matching LLM sees what it's joining, not just
   the individual signal it's matching against.

2. Multi-query agreement: a summary shows which groups were found by multiple
   independent search queries. If 2/3 queries independently find signals in the
   same group, that's stronger evidence than 1/3.

Additionally, when the PR-specificity gate confirms a match, the synthesized PR
title becomes the group's updated title — creating a feedback loop where confirmed
matches produce better titles for future matching.

Flow:
1. Generate queries, embed, cosine search — same as current_strategy
2. LLM matching with group-aware prompt (group titles + multi-query counts)
3. If matched to existing group → PR-specificity check (same as v2)
4. If confirmed → update group title with synthesized PR title
"""

import json
import uuid
import logging
from collections import defaultdict

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
from pr_specificity_strategy import SPECIFICITY_CHECK_SYSTEM_PROMPT, SpecificityResult, _build_specificity_prompt

logger = logging.getLogger(__name__)


# --- Group-aware matching ---
# Modified from: products/signals/backend/temporal/grouping.py (MATCHING_SYSTEM_PROMPT)

GROUP_AWARE_MATCHING_SYSTEM_PROMPT = """You are a signal grouping assistant. Your job is to determine if a new signal is related to an existing group of signals,
or if it should start a new group.

Signals come from diverse sources: exceptions, experiments, insight alerts, session behaviour analysis, and more.
Your task is to identify signals that are RELATED - they may be different signal types but connected by the same underlying cause, feature, or user journey.

IMPORTANT: Signals should be grouped if they are meaningfully related, not just superficially similar:
- An experiment reaching significance AND an error spike on the same feature SHOULD match (related by feature)
- A session behaviour anomaly AND an insight alert about the same user flow SHOULD match (related by user journey)
- Two "experiment reached significance" signals from DIFFERENT, unrelated experiments should NOT match
- Two signals about the SAME experiment (e.g., significance + follow-up analysis) SHOULD match

You will receive:
1. A new signal with its description and source information
2. Discovery strength: how many independent search queries found signals in each existing group (higher = stronger evidence)
3. Results from multiple search queries, each with candidate signals annotated with their group title and group size

IMPORTANT — use group context when deciding:
- Each candidate belongs to a group. The group title tells you the group's overall theme.
- Match the new signal to a GROUP's theme, not just to an individual candidate signal.
- A candidate that shares a keyword with the new signal but belongs to an unrelated group should NOT be matched.
- Groups found by multiple independent queries are more likely genuinely related.

If a candidate signal from ANY query is related to the new signal AND its group theme aligns, respond with:
{
  "reason": "<Brief, less than 100 character sentence explaining what connects the signal to the group>",
  "match_type": "existing",
  "signal_id": "<the signal_id of the matching candidate>",
  "query_index": <0-based index of the query that surfaced this candidate>
}

If no candidate is related (or all queries returned no results), respond with:
{
  "reason": "<Brief, less than 100 character sentence explaining why none of the candidates are related>",
  "match_type": "new",
  "title": "<short title for a new report>",
  "summary": "<1-2 sentence summary of what this signal group is about>"
}

IMPORTANT: The "reason" field MUST be the first key in your JSON response. Write your reasoning BEFORE making the match decision.

You must respond with valid JSON only, no other text."""


def _build_group_aware_matching_prompt(
    description: str,
    source_product: str,
    source_type: str,
    queries: list[str],
    query_results: list[list[SignalCandidate]],
    store: InMemorySignalStore,
) -> str:
    """Build matching prompt with group titles and multi-query agreement summary."""
    # Precompute group info to avoid repeated lookups
    report_ids_seen: set[str] = set()
    for candidates in query_results:
        for c in candidates:
            report_ids_seen.add(c.report_id)

    group_titles: dict[str, str] = {}
    group_sizes: dict[str, int] = {}
    for report_id in report_ids_seen:
        group_titles[report_id] = store.get_report_title(report_id) or "(untitled)"
        group_sizes[report_id] = len(store.get_signals_for_report(report_id))

    # Compute multi-query hits per report
    report_query_hits: dict[str, set[int]] = defaultdict(set)
    for query_idx, candidates in enumerate(query_results):
        for c in candidates:
            report_query_hits[c.report_id].add(query_idx)

    prompt = f"""NEW SIGNAL:
- Source: {source_product} / {source_type}
- Description: {description}

DISCOVERY STRENGTH (groups found by multiple independent queries are more likely related):
"""
    for report_id, query_indices in sorted(report_query_hits.items(), key=lambda x: -len(x[1])):
        title = group_titles[report_id]
        size = group_sizes[report_id]
        prompt += f'- "{title}" ({size} signal{"s" if size != 1 else ""}): found by {len(query_indices)}/{len(queries)} queries\n'

    prompt += "\nSEARCH RESULTS:\n"
    for query_idx, (query, candidates) in enumerate(zip(queries, query_results)):
        prompt += f'\n--- Query {query_idx}: "{query}" ---\n'
        if not candidates:
            prompt += "(no results)\n"
        else:
            for c in candidates:
                title = group_titles[c.report_id]
                size = group_sizes[c.report_id]
                prompt += f"""- signal_id: {c.signal_id}
  distance: {c.distance:.4f}
  Source: {c.source_product} / {c.source_type}
  Group: "{title}" ({size} signal{"s" if size != 1 else ""})
  Description: {c.content}
"""
    return prompt


# --- Strategy implementation ---


class PRSpecificityAndGroupAwareStrategy:
    """PR-specificity v2 + group-aware matching context + title feedback loop."""

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

            # Step 5: Update group title with the synthesized PR title (feedback loop)
            store._report_titles[decision.report_id] = specificity.pr_title
            logger.info("    CONFIRMED: updated group title to: %s", specificity.pr_title)

        return decision
