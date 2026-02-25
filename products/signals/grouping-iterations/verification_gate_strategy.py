"""
Verification gate strategy.

Uses the current signal-to-signal matching for discovery, then adds a second
LLM call to verify matches against the full report context. This splits
discovery (good at finding connections) from filtering (good at catching
weak chains) into separate steps.

Flow:
1. Generate queries, embed, cosine search, LLM match — same as current_strategy
2. If matched to a report with 2+ signals → verification gate:
   - Show the new signal + ALL signals in the target report + report title
   - LLM decides: does this signal genuinely fit the report's overall theme?
   - Yes → confirm match
   - No → create new group
3. If matched to a 1-signal report → skip verification (cold-start tolerance)
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

MAX_SIGNALS_IN_VERIFICATION = 10


# --- Verification gate ---


VERIFICATION_SYSTEM_PROMPT = """You are a signal grouping quality checker. The matching system has proposed adding a new signal to an existing report (a group of related signals). Your job is to verify whether the signal genuinely fits the report's overall theme.

A report should map to roughly ONE actionable work item — one Jira ticket or one pull request. All signals in a report should share a specific root cause, feature, or user journey.

Watch out for WEAK CHAINING:
- The new signal may share a keyword or surface-level similarity with ONE signal in the report, but be unrelated to the report's overall theme.
- Example: A report about "feature flag SDK caching issues" should NOT absorb a signal about "GDPR consent persistence in Next.js" just because one existing signal mentions Next.js.
- Ask yourself: "Would I file ALL of these signals under the same Jira ticket?" If not, reject.

You will receive:
1. The report title and ALL signals currently in the report
2. The new signal proposed for addition
3. The matching system's stated reason for the match

Respond with valid JSON only:
- If the signal fits the report's theme: {"fits": true, "reason": "<brief explanation>"}
- If it does NOT fit: {"fits": false, "reason": "<brief explanation of why it doesn't belong>"}"""


class VerificationResult(BaseModel):
    fits: bool
    reason: str


def _build_verification_prompt(
    new_signal_description: str,
    new_signal_source_product: str,
    new_signal_source_type: str,
    match_reason: str,
    report_title: str | None,
    report_signals: list[StoredSignal],
) -> str:
    prompt = f"""REPORT:
Title: {report_title or "(untitled)"}
Signals in this report ({len(report_signals)} total):
"""
    for i, sig in enumerate(report_signals[:MAX_SIGNALS_IN_VERIFICATION]):
        prompt += f"""
  Signal {i + 1}:
  - Source: {sig.source_product} / {sig.source_type}
  - Description: {sig.content[:500]}
"""
    remaining = len(report_signals) - MAX_SIGNALS_IN_VERIFICATION
    if remaining > 0:
        prompt += f"\n  ... and {remaining} more signals\n"

    prompt += f"""
PROPOSED NEW SIGNAL:
- Source: {new_signal_source_product} / {new_signal_source_type}
- Description: {new_signal_description}

MATCHING SYSTEM'S REASON: {match_reason}

Does this new signal genuinely belong in this report? Would you file all these signals under the same Jira ticket?"""
    return prompt


# --- Strategy implementation ---


class VerificationGateStrategy:
    """Current strategy + verification gate for reports with 2+ signals."""

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

        match_reason: str = ""

        def validate_match(text: str) -> GroupingDecision:
            nonlocal match_reason
            data = json.loads(text)
            match_type = data.get("match_type")
            if match_type == "existing":
                result = MatchFound.model_validate(data)
                matched = all_candidates.get(result.signal_id)
                if matched is None:
                    raise ValueError(f"signal_id {result.signal_id} not found in candidates")
                if result.query_index < 0 or result.query_index >= len(queries):
                    raise ValueError(f"query_index {result.query_index} out of range")
                match_reason = result.reason
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

        # Step 4: Verification gate (only for existing matches to 2+ signal reports)
        if not decision.is_new:
            report_signals = store.get_signals_for_report(decision.report_id)
            if len(report_signals) >= 2:
                logger.info("    Verification gate: report has %d signals, verifying...", len(report_signals))

                report_title = store.get_report_title(decision.report_id)
                verification_prompt = _build_verification_prompt(
                    new_signal_description=signal.content,
                    new_signal_source_product=signal.source_product,
                    new_signal_source_type=signal.source_type,
                    match_reason=match_reason,
                    report_title=report_title,
                    report_signals=report_signals,
                )

                def validate_verification(text: str) -> VerificationResult:
                    data = json.loads(text)
                    return VerificationResult.model_validate(data)

                verification = await call_llm_standalone(
                    system_prompt=VERIFICATION_SYSTEM_PROMPT,
                    user_prompt=verification_prompt,
                    validate=validate_verification,
                    temperature=0.2,
                )

                if not verification.fits:
                    logger.info("    Verification REJECTED: %s", verification.reason)
                    return GroupingDecision(
                        report_id=str(uuid.uuid4()),
                        is_new=True,
                        title=signal.content[:75],
                        reason=f"Verification rejected: {verification.reason}",
                    )
                else:
                    logger.info("    Verification confirmed: %s", verification.reason)
            else:
                logger.info("    Skipping verification: report has only %d signal(s)", len(report_signals))

        return decision
