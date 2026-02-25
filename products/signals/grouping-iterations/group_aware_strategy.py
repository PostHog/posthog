"""
Group-aware grouping strategy.

Instead of showing the LLM a flat list of individual signal candidates,
this strategy groups search results by report_id and shows the LLM the
full context of each candidate report. The LLM decides whether the new
signal fits the report's OVERALL theme, not just one bridging signal.

This directly addresses weak-chaining where A matches B (shared keyword),
B matches C (different keyword), but A and C are unrelated.
"""

import json
import uuid
import logging
from dataclasses import dataclass, field
from typing import Literal

from current_strategy import MAX_QUERY_TOKENS, QueryGenerationResponse, _build_query_generation_system_prompt
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

MAX_SIGNALS_PER_REPORT = 8
MAX_CANDIDATE_REPORTS = 5


# --- Candidate report grouping ---


@dataclass
class CandidateReport:
    report_id: str
    title: str | None
    signals: list[StoredSignal]
    search_hits: list[SignalCandidate] = field(default_factory=list)
    queries_matched: set[int] = field(default_factory=set)
    best_distance: float = float("inf")


def _group_candidates_by_report(
    query_results: list[list[SignalCandidate]],
    store: InMemorySignalStore,
) -> dict[str, CandidateReport]:
    """Group search results by report_id and enrich with full report context."""
    report_data: dict[str, dict] = {}

    for query_idx, candidates in enumerate(query_results):
        for c in candidates:
            if c.report_id not in report_data:
                report_data[c.report_id] = {
                    "search_hits": {},
                    "queries_matched": set(),
                    "best_distance": float("inf"),
                }
            rd = report_data[c.report_id]
            rd["search_hits"][c.signal_id] = c
            rd["queries_matched"].add(query_idx)
            rd["best_distance"] = min(rd["best_distance"], c.distance)

    result: dict[str, CandidateReport] = {}
    for report_id, rd in report_data.items():
        all_signals = store.get_signals_for_report(report_id)
        title = store.get_report_title(report_id)
        result[report_id] = CandidateReport(
            report_id=report_id,
            title=title,
            signals=all_signals,
            search_hits=list(rd["search_hits"].values()),
            queries_matched=rd["queries_matched"],
            best_distance=rd["best_distance"],
        )

    sorted_reports = sorted(result.items(), key=lambda x: x[1].best_distance)
    return dict(sorted_reports[:MAX_CANDIDATE_REPORTS])


# --- Matching prompt ---


GROUP_AWARE_MATCHING_SYSTEM_PROMPT = """You are a signal grouping assistant. Your job is to determine if a new signal belongs to an existing report (group of related signals), or if it should start a new report.

A report should map to roughly ONE actionable work item — one Jira ticket or one pull request. Signals in a report should share a specific root cause, feature, or user journey.

CRITICAL — check for weak chaining:
- Before adding a signal to a report, consider whether the new signal is related to the OVERALL THEME of the report, not just to one individual signal within it.
- If the new signal shares a keyword with one signal in the report but has nothing in common with the others, it does NOT belong in that report.
- Example: A report about "feature flag SDK caching" should NOT absorb a signal about "GDPR consent persistence in Next.js" just because one existing signal mentions Next.js.

You will receive:
1. A new signal with its description and source information
2. Candidate REPORTS — each showing the report title, ALL signals currently in that report, and search confidence metrics

For each candidate report, you see:
- The report title
- ALL signals already in the report (not just search hits)
- How many of your search queries independently found signals in this report (higher = more confident)
- The best cosine distance (lower = more similar)

If the new signal belongs in one of the candidate reports, respond with:
{
  "reason": "<Brief, <100 char sentence explaining what connects the new signal to this report's theme>",
  "match_type": "existing",
  "report_id": "<the report_id of the matching report>",
  "parent_signal_id": "<signal_id of the most closely related signal in that report>"
}

If the new signal does not belong in any candidate report, respond with:
{
  "reason": "<Brief, <100 char sentence explaining why none of the reports are a fit>",
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
    candidate_reports: dict[str, CandidateReport],
    total_queries: int,
) -> str:
    prompt = f"""NEW SIGNAL:
- Source: {source_product} / {source_type}
- Description: {description}

CANDIDATE REPORTS:
"""
    for report in sorted(candidate_reports.values(), key=lambda r: r.best_distance):
        prompt += f"\n--- Report: {report.report_id} ---\n"
        prompt += f"Title: {report.title or '(untitled)'}\n"
        prompt += f"Search confidence: {len(report.queries_matched)}/{total_queries} queries matched\n"
        prompt += f"Best distance: {report.best_distance:.4f}\n"
        prompt += f"Signals in this report ({len(report.signals)} total):\n"

        displayed = report.signals[:MAX_SIGNALS_PER_REPORT]
        for sig in displayed:
            prompt += f"\n  - signal_id: {sig.signal_id}"
            prompt += f"\n    Source: {sig.source_product} / {sig.source_type}"
            prompt += f"\n    Description: {sig.content[:500]}\n"

        remaining = len(report.signals) - len(displayed)
        if remaining > 0:
            prompt += f"\n  ... and {remaining} more signals (omitted for brevity)\n"

    return prompt


# --- Response models ---


class GroupAwareMatchFound(BaseModel):
    reason: str
    match_type: Literal["existing"]
    report_id: str
    parent_signal_id: str


class GroupAwareNewGroup(BaseModel):
    reason: str
    match_type: Literal["new"]
    title: str
    summary: str


# --- Strategy implementation ---


class GroupAwareStrategy:
    """Group-aware grouping strategy that shows full report context to the LLM."""

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

        # Step 1: Generate search queries (reused from current_strategy)
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

        # Step 2: Embed and search (same as current)
        query_embeddings = embedding_cache.embed_batch(queries)
        query_results: list[list[SignalCandidate]] = []
        for q_emb in query_embeddings:
            candidates = store.search(q_emb, limit=10)
            query_results.append(candidates)

        # Step 3: Group search results by report
        candidate_reports = _group_candidates_by_report(query_results, store)

        if not candidate_reports:
            report_id = str(uuid.uuid4())
            return GroupingDecision(
                report_id=report_id,
                is_new=True,
                title=signal.content[:75],
                reason="No candidates found in search",
            )

        # Step 4: Group-aware LLM matching
        matching_prompt = _build_group_aware_matching_prompt(
            signal.content,
            signal.source_product,
            signal.source_type,
            candidate_reports,
            len(queries),
        )

        def validate_match(text: str) -> GroupingDecision:
            data = json.loads(text)
            match_type = data.get("match_type")
            if match_type == "existing":
                result = GroupAwareMatchFound.model_validate(data)
                if result.report_id not in candidate_reports:
                    raise ValueError(f"report_id {result.report_id} not in candidates")
                report = candidate_reports[result.report_id]
                report_signal_ids = {s.signal_id for s in report.signals}
                if result.parent_signal_id not in report_signal_ids:
                    raise ValueError(f"parent_signal_id {result.parent_signal_id} not in report {result.report_id}")
                return GroupingDecision(
                    report_id=result.report_id,
                    is_new=False,
                    title=None,
                    reason=result.reason,
                )
            elif match_type == "new":
                result = GroupAwareNewGroup.model_validate(data)
                return GroupingDecision(
                    report_id=str(uuid.uuid4()),
                    is_new=True,
                    title=result.title,
                    reason=result.reason,
                )
            else:
                raise ValueError(f"Invalid match_type: {match_type}")

        return await call_llm_standalone(
            system_prompt=GROUP_AWARE_MATCHING_SYSTEM_PROMPT,
            user_prompt=matching_prompt,
            validate=validate_match,
            temperature=0.2,
        )
