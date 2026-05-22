import uuid
import asyncio
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

import structlog
from temporalio import workflow
from temporalio.common import RetryPolicy

from products.signals.backend.temporal.grouping import (
    AssignAndEmitSignalInput,
    AssignAndEmitSignalOutput,
    MatchSignalToReportInput,
    VerifyMatchSpecificityInput,
    VerifyMatchSpecificityOutput,
    _augment_candidates_with_batch,
    _cosine_distance,
    _ProcessedBatchSignal,
    assign_and_emit_signal_activity,
    match_signal_to_report_activity,
    verify_match_specificity_activity,
)
from products.signals.backend.temporal.signal_queries import (
    FetchSignalsForReportInput,
    FetchSignalsForReportOutput,
    fetch_signals_for_report_activity,
)
from products.signals.backend.temporal.types import (
    EmitSignalInputs,
    ExistingReportMatch,
    MatchResult,
    NewReportMatch,
    NoMatchMetadata,
    ReportContext,
    SignalCandidate,
    SignalReportSummaryWorkflowInputs,
    SpecificityMetadata,
)

logger = structlog.get_logger(__name__)


@dataclass
class _SignalResult:
    """Result of processing a single signal through match → specificity → assign pipeline."""

    signal_id: str
    signal_idx: int
    match_result: MatchResult  # the final match result (possibly updated after specificity)
    assign_result: AssignAndEmitSignalOutput
    updated_title: Optional[str]


@dataclass
class SequentialPhaseResult:
    """Aggregated result of the parallel sequential phase."""

    dropped: int
    promoted_reports: dict[str, tuple[SignalReportSummaryWorkflowInputs, int]]
    emitted_signals: list[tuple[str, AssignAndEmitSignalOutput]]


def _would_be_candidate(
    query_embeddings: list[list[float]],
    ch_candidates_per_query: list[list[SignalCandidate]],
    embedding: list[float],
    limit: int = 10,
) -> bool:
    """
    Check if `embedding` would be inserted into any of the query candidate sets.
    Uses the same logic as _augment_candidates_with_batch: for each query, if fewer
    than `limit` CH candidates OR cosine distance < worst CH candidate distance, return True.
    """
    for query_emb, ch_candidates in zip(query_embeddings, ch_candidates_per_query):
        worst_distance = ch_candidates[-1].distance if ch_candidates else float("inf")
        dist = _cosine_distance(query_emb, embedding)
        if len(ch_candidates) < limit or dist < worst_distance:
            return True
    return False


def _compute_dependencies(
    per_signal_query_embeddings: list[list[list[float]]],
    per_signal_ch_results: list[list[list[SignalCandidate]]],
    signal_embeddings: list[list[float]],
    limit: int = 10,
) -> list[set[int]]:
    """
    For each signal j, find all earlier signals i (i < j) whose embedding would be
    a candidate for j. Returns a list of sets where deps[j] = {i, ...}.
    """
    n = len(signal_embeddings)
    deps: list[set[int]] = [set() for _ in range(n)]
    for j in range(1, n):
        for i in range(j):
            if _would_be_candidate(
                per_signal_query_embeddings[j],
                per_signal_ch_results[j],
                signal_embeddings[i],
                limit=limit,
            ):
                deps[j].add(i)
    return deps


def _assign_batch_levels(deps: list[set[int]]) -> list[int]:
    """
    For each signal, assign a batch level: 0 if no deps, else max(dep levels) + 1.
    Returns a list of levels.
    """
    n = len(deps)
    levels = [0] * n
    for j in range(n):
        if deps[j]:
            levels[j] = max(levels[i] for i in deps[j]) + 1
    return levels


def _group_into_batches(levels: list[int]) -> list[list[int]]:
    """
    Group signal indices by their level into ordered batches.
    Returns list of batches, where each batch is a list of signal indices.
    """
    if not levels:
        return []
    max_level = max(levels)
    batches: list[list[int]] = [[] for _ in range(max_level + 1)]
    for idx, level in enumerate(levels):
        batches[level].append(idx)
    return batches


def partition_into_parallel_batches(
    per_signal_query_embeddings: list[list[list[float]]],
    per_signal_ch_results: list[list[list[SignalCandidate]]],
    signal_embeddings: list[list[float]],
    limit: int = 10,
) -> list[list[int]]:
    """
    Public function: chains dependency analysis → level assignment → batch grouping.
    Returns an ordered list of batches, each batch is a list of signal indices
    that are safe to process in parallel.
    """
    deps = _compute_dependencies(per_signal_query_embeddings, per_signal_ch_results, signal_embeddings, limit=limit)
    levels = _assign_batch_levels(deps)
    return _group_into_batches(levels)


async def _process_signal(
    team_id: int,
    signal: EmitSignalInputs,
    signal_id: str,
    signal_idx: int,
    signal_embedding: list[float],
    queries: list[str],
    augmented_results: list[list[SignalCandidate]],
    report_contexts: dict[str, ReportContext],
) -> _SignalResult:
    """
    Process a single signal through the match → specificity → assign pipeline.
    Replicates the body of the sequential for-loop in _process_signal_batch.
    """
    # Step 5: Group-aware LLM match
    match_result = await workflow.execute_activity(
        match_signal_to_report_activity,
        MatchSignalToReportInput(
            description=signal.description,
            source_product=signal.source_product,
            source_type=signal.source_type,
            queries=queries,
            query_results=augmented_results,
            report_contexts=report_contexts,
        ),
        start_to_close_timeout=timedelta(minutes=10),
        retry_policy=RetryPolicy(maximum_attempts=5),
    )

    # Step 5.5: PR-specificity verification for existing matches
    updated_title: Optional[str] = None

    if isinstance(match_result, ExistingReportMatch):
        report_ctx = report_contexts.get(match_result.report_id)
        report_title = report_ctx.title if report_ctx else ""

        group_signals_result: FetchSignalsForReportOutput = await workflow.execute_activity(
            fetch_signals_for_report_activity,
            FetchSignalsForReportInput(team_id=team_id, report_id=match_result.report_id),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        specificity_result: VerifyMatchSpecificityOutput = await workflow.execute_activity(
            verify_match_specificity_activity,
            VerifyMatchSpecificityInput(
                team_id=team_id,
                report_id=match_result.report_id,
                report_title=report_title,
                new_signal_description=signal.description,
                new_signal_source_product=signal.source_product,
                new_signal_source_type=signal.source_type,
                group_signals=group_signals_result.signals,
            ),
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=5),
        )

        specificity_meta = SpecificityMetadata(
            pr_title=specificity_result.pr_title,
            specific_enough=specificity_result.specific_enough,
            reason=specificity_result.reason,
        )

        if specificity_result.specific_enough:
            updated_title = specificity_result.pr_title
            match_result.match_metadata.specificity = specificity_meta
        else:
            match_result = NewReportMatch(
                title=signal.description.split("\n")[0],
                summary=f"Split from group: {report_title}",
                match_metadata=NoMatchMetadata(
                    reason=f'PR-specificity rejected: "{specificity_result.pr_title}" — {specificity_result.reason}',
                    specificity_rejection=specificity_meta,
                ),
            )

    # Step 6: Assign + emit
    assign_result: AssignAndEmitSignalOutput = await workflow.execute_activity(
        assign_and_emit_signal_activity,
        AssignAndEmitSignalInput(
            team_id=signal.team_id,
            signal_id=signal_id,
            description=signal.description,
            weight=signal.weight,
            source_product=signal.source_product,
            source_type=signal.source_type,
            source_id=signal.source_id,
            extra=signal.extra,
            embedding=signal_embedding,
            match_result=match_result,
            updated_title=updated_title,
        ),
        start_to_close_timeout=timedelta(minutes=5),
        retry_policy=RetryPolicy(maximum_attempts=3),
    )

    return _SignalResult(
        signal_id=signal_id,
        signal_idx=signal_idx,
        match_result=match_result,
        assign_result=assign_result,
        updated_title=updated_title,
    )


async def _process_signal_safe(
    team_id: int,
    signal: EmitSignalInputs,
    signal_id: str,
    signal_idx: int,
    signal_embedding: list[float],
    queries: list[str],
    augmented_results: list[list[SignalCandidate]],
    report_contexts: dict[str, ReportContext],
) -> Optional[_SignalResult]:
    """Wrapper around _process_signal that catches exceptions and returns None on failure."""
    try:
        return await _process_signal(
            team_id=team_id,
            signal=signal,
            signal_id=signal_id,
            signal_idx=signal_idx,
            signal_embedding=signal_embedding,
            queries=queries,
            augmented_results=augmented_results,
            report_contexts=report_contexts,
        )
    except Exception:
        logger.exception(
            "Failed to process signal in parallel batch",
            team_id=team_id,
            source_product=signal.source_product,
            source_type=signal.source_type,
            source_id=signal.source_id,
        )
        return None


async def _process_parallel_batch(
    batch_indices: list[int],
    batch: list[EmitSignalInputs],
    team_id: int,
    per_signal_queries: list[list[str]],
    per_signal_query_embeddings: list[list[list[float]]],
    per_signal_ch_results: list[list[list[SignalCandidate]]],
    signal_embeddings: list[list[float]],
    processed_batch_signals: list[_ProcessedBatchSignal],
    report_contexts: dict[str, ReportContext],
) -> tuple[
    list[_ProcessedBatchSignal],
    list[tuple[str, AssignAndEmitSignalOutput]],
    dict[str, ReportContext],
    int,
    dict[str, tuple[SignalReportSummaryWorkflowInputs, int]],
]:
    """
    Process a single parallel batch. All signals in batch_indices are processed
    concurrently via asyncio.gather.

    Returns:
        - new_processed_signals: list of _ProcessedBatchSignal for successful signals
        - new_emitted_signals: list of (signal_id, AssignAndEmitSignalOutput)
        - updated report_contexts
        - dropped count
        - promoted_reports
    """
    dropped = 0
    new_processed_signals: list[_ProcessedBatchSignal] = []
    new_emitted_signals: list[tuple[str, AssignAndEmitSignalOutput]] = []
    promoted_reports: dict[str, tuple[SignalReportSummaryWorkflowInputs, int]] = {}

    # Prepare coroutines for each signal in the batch
    coroutines = []
    for idx in batch_indices:
        signal = batch[idx]
        signal_id = str(uuid.uuid4())

        # Augment CH candidates with all previously processed signals (from earlier batches)
        augmented_results = _augment_candidates_with_batch(
            per_signal_query_embeddings[idx],
            per_signal_ch_results[idx],
            processed_batch_signals,
            limit=10,
        )

        coroutines.append(
            _process_signal_safe(
                team_id=team_id,
                signal=signal,
                signal_id=signal_id,
                signal_idx=idx,
                signal_embedding=signal_embeddings[idx],
                queries=per_signal_queries[idx],
                augmented_results=augmented_results,
                report_contexts=report_contexts,
            )
        )

    # Process all signals in this batch concurrently
    results: list[Optional[_SignalResult]] = list(await asyncio.gather(*coroutines))

    # Collect results and update state
    for result in results:
        if result is None:
            dropped += 1
            continue

        idx = result.signal_idx
        signal = batch[idx]

        # Track for augmenting later batches
        new_processed_signals.append(
            _ProcessedBatchSignal(
                signal_id=result.signal_id,
                report_id=result.assign_result.report_id,
                content=signal.description,
                source_product=signal.source_product,
                source_type=signal.source_type,
                embedding=signal_embeddings[idx],
            )
        )
        new_emitted_signals.append((result.signal_id, result.assign_result))

        # Update local report_contexts so later batches see this report
        if isinstance(result.match_result, ExistingReportMatch):
            old_ctx = report_contexts.get(result.assign_result.report_id)
            report_contexts[result.assign_result.report_id] = ReportContext(
                report_id=result.assign_result.report_id,
                title=result.updated_title or (old_ctx.title if old_ctx else ""),
                signal_count=(old_ctx.signal_count if old_ctx else 0) + 1,
            )
        else:
            report_contexts[result.assign_result.report_id] = ReportContext(
                report_id=result.assign_result.report_id,
                title=result.match_result.title,
                signal_count=1,
            )

        if result.assign_result.promoted:
            promoted_reports[result.assign_result.report_id] = (
                SignalReportSummaryWorkflowInputs(team_id=signal.team_id, report_id=result.assign_result.report_id),
                result.assign_result.run_count,
            )

    return new_processed_signals, new_emitted_signals, report_contexts, dropped, promoted_reports


async def process_sequential_phase_parallel(
    batch: list[EmitSignalInputs],
    team_id: int,
    per_signal_queries: list[list[str]],
    per_signal_query_embeddings: list[list[list[float]]],
    per_signal_ch_results: list[list[list[SignalCandidate]]],
    signal_embeddings: list[list[float]],
    report_contexts: dict[str, ReportContext],
) -> SequentialPhaseResult:
    """
    Main public function: replaces the sequential phase of _process_signal_batch with
    parallel sub-batches based on embedding dependency analysis.

    Calls partition_into_parallel_batches, then iterates through each batch calling
    _process_parallel_batch, accumulating results across batches.
    """
    parallel_batches = partition_into_parallel_batches(
        per_signal_query_embeddings=per_signal_query_embeddings,
        per_signal_ch_results=per_signal_ch_results,
        signal_embeddings=signal_embeddings,
        limit=10,
    )

    batch_sizes = [len(b) for b in parallel_batches]
    logger.info(
        "Partitioned signals into parallel batches",
        team_id=team_id,
        num_batches=len(parallel_batches),
        batch_sizes=batch_sizes,
        total_signals=len(batch),
    )

    # Accumulate across batches
    all_processed_signals: list[_ProcessedBatchSignal] = []
    all_emitted_signals: list[tuple[str, AssignAndEmitSignalOutput]] = []
    all_promoted_reports: dict[str, tuple[SignalReportSummaryWorkflowInputs, int]] = {}
    total_dropped = 0

    for batch_idx, batch_indices in enumerate(parallel_batches):
        logger.info(
            "Processing parallel batch",
            team_id=team_id,
            batch_idx=batch_idx,
            batch_size=len(batch_indices),
            accumulated_signals=len(all_processed_signals),
        )

        new_processed, new_emitted, report_contexts, dropped, promoted = await _process_parallel_batch(
            batch_indices=batch_indices,
            batch=batch,
            team_id=team_id,
            per_signal_queries=per_signal_queries,
            per_signal_query_embeddings=per_signal_query_embeddings,
            per_signal_ch_results=per_signal_ch_results,
            signal_embeddings=signal_embeddings,
            processed_batch_signals=all_processed_signals,
            report_contexts=report_contexts,
        )

        all_processed_signals.extend(new_processed)
        all_emitted_signals.extend(new_emitted)
        all_promoted_reports.update(promoted)
        total_dropped += dropped

    return SequentialPhaseResult(
        dropped=total_dropped,
        promoted_reports=all_promoted_reports,
        emitted_signals=all_emitted_signals,
    )
