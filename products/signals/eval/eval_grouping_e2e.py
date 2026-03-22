"""
Grouping e2e eval — measures how well the signal grouping pipeline clusters
signals into reports, evaluated against known ground-truth groups.

Feeds synthetic signals through the real pipeline (LLM query generation,
embedding search, LLM matching, specificity verification) with mocked
infrastructure (in-memory embedding store replaces ClickHouse + Kafka).

After grouping, each report is summarized and judged for safety (prompt
injection detection) and actionability (can a coding agent act on it).

Captures four levels of metrics:
- Per-signal matching: correct_match (binary), correct_match_pre_specificity
  (binary, LLM matcher decision before specificity judge),
  failure_mode (categorical: NONE, UNDERGROUP, OVERGROUP),
  query_diversity (numeric, avg pairwise cosine distance between query
  embeddings), candidate_diversity (numeric, avg 1 − Jaccard across
  query pairs' candidate sets)
- Per-report grouping: purity, is_pure, group_recall
- Per-report judges: correct_classification (binary) for both
  report-safety-check and report-actionability-check
- Aggregate: ARI, homogeneity, completeness, mean_purity,
  group_recall, malicious_leaked_rate

Run:
    pytest products/signals/eval/eval_grouping_e2e.py -xvs
    pytest products/signals/eval/eval_grouping_e2e.py -xvs --limit 10 --no-capture
"""

import sys
import uuid
import random
import asyncio
import logging
from dataclasses import dataclass
from enum import Enum
from itertools import combinations
from time import time
from typing import Any

import pytest

from sklearn.metrics import adjusted_rand_score, homogeneity_completeness_v_measure
from tqdm import tqdm

from posthog.temporal.data_imports.workflow_activities.emit_signals import (
    _check_actionability,
    _summarize_long_descriptions,
)

from products.signals.backend.temporal.actionability_judge import ActionabilityChoice, judge_report_actionability
from products.signals.backend.temporal.grouping import (
    generate_search_queries,
    match_signal_to_report,
    verify_match_specificity,
)
from products.signals.backend.temporal.report_safety_judge import judge_report_safety
from products.signals.backend.temporal.safety_filter import safety_filter
from products.signals.backend.temporal.summarize_signals import summarize_signals
from products.signals.backend.temporal.types import (
    ExistingReportMatch,
    MatchResult,
    NewReportMatch,
    NoMatchMetadata,
    SignalCandidate,
    SpecificityMetadata,
)
from products.signals.eval.capture import EvalMetric, capture_evaluation, deterministic_uuid
from products.signals.eval.data_spec import EvalSignalSpec
from products.signals.eval.fixtures.grouping_data import GROUP_DATA
from products.signals.eval.mock import EmbeddingStore, ReportStore

RNG_SEED = 1337
MAX_CONCURRENT_RUNS = 70


class EvalProgress:
    """Encapsulates tqdm progress bars and error counters for the eval run."""

    def __init__(self, n_signals: int, n_groups: int):
        self.n_signals = n_signals
        self.n_groups = n_groups
        self.active = 0
        self.dropped = 0
        self._bar = tqdm(total=n_signals, desc="Matching", unit="sig", file=sys.stderr)

    def signal_started(self):
        self.active += 1
        self._update_postfix()

    def signal_done(self):
        self.active -= 1
        self._bar.update(1)
        self._update_postfix()

    def signal_dropped(self):
        self.active -= 1
        self.dropped += 1
        self._bar.update(1)
        self._update_postfix()

    def _update_postfix(self):
        parts: dict[str, int] = {}
        if self.active:
            parts["processing"] = self.active
        if self.dropped:
            parts["filtered"] = self.dropped
        self._bar.set_postfix(parts)

    def start_judging(self, n_reports: int):
        self._bar.close()
        self._bar = tqdm(total=n_reports, desc="Judging", unit="report", file=sys.stderr)

    def report_judged(self):
        self._bar.update(1)

    def done(self):
        self._bar.close()


class MatchFailureMode(Enum):
    NONE = "NONE"  # correct match
    UNDERGROUP = "UNDERGROUP"  # created new report when should have joined existing
    OVERGROUP = "OVERGROUP"  # joined a report belonging to a different ground-truth group


@dataclass
class EvalSignalCase:
    group_index: int
    signal_index: int
    actionable: bool
    safe: bool
    signal: EvalSignalSpec


def get_signals_stream() -> list[EvalSignalCase]:
    """Interleave signals across groups randomly, preserving within-group order."""
    rng = random.Random(RNG_SEED)
    cursors = [0] * len(GROUP_DATA)
    stream: list[EvalSignalCase] = []

    def get_active():
        return [i for i, g in enumerate(GROUP_DATA) if cursors[i] < len(g.signals)]

    while active := get_active():
        k = rng.randint(0, len(active) - 1)
        group_index = active[k]
        group = GROUP_DATA[group_index]
        signal = group.signals[cursors[group_index]]
        stream.append(
            EvalSignalCase(
                group_index=group_index,
                signal_index=cursors[group_index],
                safe=group.safe,
                actionable=group.actionable,
                signal=signal,
            )
        )
        cursors[group_index] += 1

    return stream


class TestGroupingPipeline:
    @pytest.fixture(autouse=True)
    def _setup(self, posthog_client, openai_client, gemini_client, mock_temporal, limit, no_capture, online):
        self.posthog_client = posthog_client
        self.gemini_client = gemini_client
        self.openai_client = openai_client
        self.store = EmbeddingStore(openai_client)
        self.report_store = ReportStore()
        self.limit = limit
        self.no_capture = no_capture
        self.online = online
        self._match_lock = asyncio.Lock()
        self.start_time = time()

        # Suppress structlog noise from downstream modules during the eval
        root_logger = logging.getLogger()
        previous_level = root_logger.level
        root_logger.setLevel(logging.ERROR)
        yield
        root_logger.setLevel(previous_level)

    @pytest.mark.django_db(transaction=True)
    async def test_grouping_pipeline(self):
        stream = get_signals_stream()
        if self.limit:
            stream = stream[: self.limit]
            tqdm.write(f"Limiting to {self.limit} signals.", file=sys.stderr)

        n_groups = len({case.group_index for case in stream})
        self.progress = EvalProgress(n_signals=len(stream), n_groups=n_groups)

        sem = asyncio.Semaphore(MAX_CONCURRENT_RUNS)
        await asyncio.gather(
            *[self.run_signal_pipeline_concurrently(sem, record_id=i, case=case) for i, case in enumerate(stream)]
        )

        reports = self.report_store.all_reports()
        self.progress.start_judging(len(reports))
        await self._judge_reports()
        self.progress.done()

        self._capture_grouping_quality()
        self._capture_aggregate_metrics(stream)

    async def run_signal_pipeline_concurrently(self, sem: asyncio.Semaphore, record_id: int, case: EvalSignalCase):
        async with sem:
            await self.run_signal_pipeline(record_id, case)

    async def run_signal_pipeline(self, record_id: int, case: EvalSignalCase):
        """Run a single signal through the pre-emit pipeline."""

        self.progress.signal_started()
        try:
            description = await self.pre_emit(record_id, case)

            if not description:
                self.progress.signal_dropped()
                return

            safety_result = await safety_filter(description)
            await self._capture_safety_filter(case, safety_result)

            if not safety_result.safe:
                self.progress.signal_dropped()
                return

            # Prepare queries and embeddings outside the lock — these are
            # store-independent and can run concurrently across signals.
            queries, query_embeddings, signal_embedding = await self._prepare(description, case)

            async with self._match_lock:
                match_result, specificity_result, candidates = await self._match(
                    description, case, queries, query_embeddings
                )
                self._capture_match_quality(
                    case, match_result, specificity_result, queries, query_embeddings, candidates
                )
                self._persist_signal(record_id, description, case, specificity_result, signal_embedding)

            self.progress.signal_done()
        except Exception:
            self.progress.signal_dropped()

    async def _prepare(
        self, description: str, case: EvalSignalCase
    ) -> tuple[list[str], list[list[float]], list[float]]:
        """Generate search queries and compute all embeddings. No store mutations."""

        queries = await generate_search_queries(
            description=description,
            source_product=case.signal.config.source_product,
            source_type=case.signal.config.source_type,
            signal_type_examples=self.store.get_type_examples(),
        )

        all_embeddings = await asyncio.gather(
            *[self.store.embed(q) for q in queries],
            self.store.embed(description),
        )
        query_embeddings = list(all_embeddings[: len(queries)])
        signal_embedding = all_embeddings[-1]

        return queries, query_embeddings, signal_embedding

    async def _match(
        self,
        description: str,
        case: EvalSignalCase,
        queries: list[str],
        query_embeddings: list[list[float]],
    ) -> tuple[MatchResult, MatchResult, list[list[SignalCandidate]]]:
        """Search, LLM-match, and verify specificity. Must run under _match_lock."""

        candidates = [self.store.search(emb) for emb in query_embeddings]

        match_result = await match_signal_to_report(
            description=description,
            source_product=case.signal.config.source_product,
            source_type=case.signal.config.source_type,
            queries=queries,
            query_results=candidates,
            report_contexts=self.report_store.get_contexts(),
        )
        specificity_match_result = match_result

        if isinstance(specificity_match_result, ExistingReportMatch):
            report_ctx = self.report_store.get(specificity_match_result.report_id)
            report_title = report_ctx.context.title if report_ctx else ""
            group_signals = self.store.get_signals_for_report(specificity_match_result.report_id)

            specificity_result = await verify_match_specificity(
                new_signal_description=description,
                new_signal_source_product=case.signal.config.source_product,
                new_signal_source_type=case.signal.config.source_type,
                report_title=report_title,
                group_signals=group_signals,
            )

            specificity_meta = SpecificityMetadata(
                pr_title=specificity_result.pr_title,
                specific_enough=specificity_result.specific_enough,
                reason=specificity_result.reason,
            )

            if specificity_result.specific_enough:
                specificity_match_result.match_metadata.specificity = specificity_meta
            else:
                specificity_match_result = NewReportMatch(
                    title=description.split("\n")[0],
                    summary=f"Split from group: {report_title}",
                    match_metadata=NoMatchMetadata(
                        reason=f'PR-specificity rejected: "{specificity_result.pr_title}" — {specificity_result.reason}',
                        specificity_rejection=specificity_meta,
                    ),
                )

        return match_result, specificity_match_result, candidates

    def _persist_signal(
        self,
        record_id: int,
        description: str,
        case: EvalSignalCase,
        match_result: MatchResult,
        signal_embedding: list[float],
    ) -> str:
        """Write match result to both stores. Must run under _match_lock."""

        report_id = match_result.report_id if isinstance(match_result, ExistingReportMatch) else str(uuid.uuid4())

        self.report_store.insert(report_id, match_result, case.group_index)

        self.store.store(
            signal_id=f"sig-{record_id}",
            content=description,
            embedding=signal_embedding,
            report_id=report_id,
            source_product=case.signal.config.source_product,
            source_type=case.signal.config.source_type,
            source_id="",
            weight=1.0,
        )

        return report_id

    async def pre_emit(self, record_id: int, case: EvalSignalCase) -> str | None:
        output = case.signal.content
        config = case.signal.config

        outputs = [output]

        if config.summarization_prompt is not None and config.description_summarization_threshold_chars is not None:
            outputs = await _summarize_long_descriptions(
                outputs=outputs,
                summarization_prompt=config.summarization_prompt,
                threshold=config.description_summarization_threshold_chars,
                extra={},
            )

        output = outputs[0]

        if config.actionability_prompt:
            is_actionable, thoughts = await _check_actionability(
                self.gemini_client, output, config.actionability_prompt
            )
            await self._capture_pre_emit_actionability(case, thoughts, is_actionable)
            if not is_actionable:
                return None

        return output.description or None

    async def _capture_safety_filter(self, case: EvalSignalCase, result):
        passed = result.safe == case.safe
        self._capture(
            eval_name="signal-safety-filter",
            item_name=f"filter-{case.group_index}-{case.signal_index}",
            input=case.signal.content.description,
            output="SAFE" if result.safe else f"UNSAFE ({result.threat_type})",
            expected="SAFE" if case.safe else "UNSAFE",
            metrics=[
                EvalMetric(
                    name="correct_classification",
                    result_type="binary",
                    score=1.0 if passed else 0.0,
                    score_min=0,
                    score_max=1,
                    reasoning=result.explanation,
                ),
            ],
            passed=passed,
        )

    async def _capture_pre_emit_actionability(self, case: EvalSignalCase, thoughts: str | None, outcome: bool):
        passed = outcome == case.actionable
        self._capture(
            eval_name=f"{case.signal.source.value.lower()}-actionability-check",
            item_name=f"case-{case.group_index}-{case.signal_index}",
            input=case.signal.content.description,
            output="ACTIONABLE" if outcome else "NOT_ACTIONABLE",
            expected="ACTIONABLE" if case.actionable else "NOT_ACTIONABLE",
            metrics=[
                EvalMetric(
                    name="correct_classification",
                    result_type="binary",
                    score=1.0 if passed else 0.0,
                    score_min=0,
                    score_max=1,
                    reasoning=thoughts,
                )
            ],
            passed=passed,
        )

    def _capture_match_quality(
        self,
        case: EvalSignalCase,
        match_result: MatchResult,
        specificity_match_result: MatchResult,
        queries: list[str],
        query_embeddings: list[list[float]],
        candidates: list[list[SignalCandidate]],
    ):
        """Captures whether the matching decision was correct and classifies the failure mode."""
        expected_report = self.report_store.find_report_by_group_index(case.group_index)
        expected_id = expected_report.context.report_id if expected_report else None
        expected = "NEW_REPORT" if expected_report is None else "EXISTING_REPORT"

        def evaluate_match_failure(mr: MatchResult) -> MatchFailureMode:
            is_existing = isinstance(mr, ExistingReportMatch)
            if expected_report is None:
                return MatchFailureMode.OVERGROUP if is_existing else MatchFailureMode.NONE
            if isinstance(mr, ExistingReportMatch) and mr.report_id == expected_id:
                return MatchFailureMode.NONE
            if is_existing:
                return MatchFailureMode.OVERGROUP
            return MatchFailureMode.UNDERGROUP

        match_failure_mode = evaluate_match_failure(match_result)
        specificity_failure_mode = evaluate_match_failure(specificity_match_result)
        correct = specificity_failure_mode == MatchFailureMode.NONE
        pre_specificity_correct = match_failure_mode == MatchFailureMode.NONE

        specificity_reasoning = (
            specificity_match_result.match_metadata.reason
            if hasattr(specificity_match_result.match_metadata, "reason")
            else ""
        )

        # Query diversity: average pairwise cosine distance between query embeddings
        if len(query_embeddings) < 2:
            query_diversity = 0.0
        else:
            distances = [
                self.store.cosine_distance(query_embeddings[i], query_embeddings[j])
                for i, j in combinations(range(len(query_embeddings)), 2)
            ]
            query_diversity = sum(distances) / len(distances)

        # Candidate diversity
        if len(candidates) < 2:
            candidate_diversity = 0.0
        else:
            candidate_sets = [{c.signal_id for c in cands} for cands in candidates]
            jaccards = []
            for i, j in combinations(range(len(candidate_sets)), 2):
                union = candidate_sets[i] | candidate_sets[j]
                if not union:
                    jaccards.append(0.0)
                else:
                    intersection = candidate_sets[i] & candidate_sets[j]
                    jaccards.append(1.0 - len(intersection) / len(union))
            candidate_diversity = sum(jaccards) / len(jaccards)

        is_existing = isinstance(specificity_match_result, ExistingReportMatch)
        report_id = (
            specificity_match_result.report_id if isinstance(specificity_match_result, ExistingReportMatch) else None
        )

        output = {
            "report": "EXISTING_REPORT" if is_existing else "NEW_REPORT",
            "specificity_reasoning": specificity_reasoning,
            "queries": queries,
            "report_signals": [sig.content for sig in self.store.get_signals_for_report(report_id)]
            if report_id
            else None,
        }

        self._capture(
            eval_name="match-quality",
            item_name=f"match-{case.group_index}-{case.signal_index}",
            input=case.signal.content.description,
            output=output,
            expected=expected,
            metrics=[
                EvalMetric(
                    name="correct_match",
                    result_type="binary",
                    score=1.0 if correct else 0.0,
                    score_min=0,
                    score_max=1,
                    reasoning=None if correct else f"Failure mode: {specificity_failure_mode.value}",
                ),
                EvalMetric(
                    name="correct_match_pre_specificity",
                    result_type="binary",
                    score=1.0 if pre_specificity_correct else 0.0,
                    score_min=0,
                    score_max=1,
                    reasoning=None if pre_specificity_correct else f"Failure mode: {match_failure_mode.value}",
                ),
                EvalMetric(
                    name="query_diversity",
                    description="Average pairwise cosine distance between query embeddings (0 = identical, 1 = orthogonal)",
                    result_type="numeric",
                    score=query_diversity,
                ),
                EvalMetric(
                    name="candidate_diversity",
                    description="Average (1 - Jaccard similarity) across query pairs' candidate sets (0 = identical, 1 = disjoint)",
                    result_type="numeric",
                    score=candidate_diversity,
                ),
            ],
            passed=correct,
        )

    async def _judge_reports(self):
        await asyncio.gather(*[self._judge_single_report(report) for report in self.report_store.all_reports()])

    async def _judge_single_report(self, report):
        report_id = report.context.report_id
        signals = self.store.get_signals_for_report(report_id)
        if not signals:
            return

        try:
            dominant_group = GROUP_DATA[report.true_group_index]
            expected_safe = dominant_group.safe
            expected_actionable = dominant_group.actionable

            title, summary = await summarize_signals(signals)

            safety_result, actionability_result = await asyncio.gather(
                judge_report_safety(title=title, summary=summary, signals=signals),
                judge_report_actionability(title=title, summary=summary, signals=signals),
            )

            report.safety_choice = safety_result.choice
            passed = safety_result.choice == expected_safe

            self._capture(
                eval_name="report-safety-check",
                item_name=f"report-{report_id[:12]}",
                input=f"{title}\n\n{summary}",
                output="SAFE" if safety_result.choice else "UNSAFE",
                expected="SAFE" if expected_safe else "UNSAFE",
                metrics=[
                    EvalMetric(
                        name="correct_classification",
                        result_type="binary",
                        score=1.0 if passed else 0.0,
                        reasoning=safety_result.explanation,
                    ),
                ],
                passed=passed,
            )

            is_actionable = actionability_result.choice == ActionabilityChoice.IMMEDIATELY_ACTIONABLE
            self._capture(
                eval_name="report-actionability-check",
                item_name=f"report-{report_id[:12]}",
                input=f"{title}\n\n{summary}",
                output=actionability_result.choice.value.upper(),
                expected="IMMEDIATELY_ACTIONABLE" if expected_actionable else "NOT_IMMEDIATELY_ACTIONABLE",
                metrics=[
                    EvalMetric(
                        name="correct_classification",
                        result_type="binary",
                        score=1.0 if is_actionable == expected_actionable else 0.0,
                        reasoning=actionability_result.explanation,
                    ),
                ],
                passed=is_actionable == expected_actionable,
            )
            self.progress.report_judged()
        except Exception:
            self.progress.report_judged()

    def _capture_grouping_quality(self):
        """Per-report metrics: purity, is_pure, group_recall."""
        for report in self.report_store.all_reports():
            groups = report.true_signal_groups
            total = len(groups)
            if total == 0:
                continue

            dominant_group = report.true_group_index
            dominant_count = groups.count(dominant_group)

            purity = dominant_count / total
            is_pure = dominant_count == total

            # recall: what fraction of the dominant group's total signals landed here
            total_in_group = len(GROUP_DATA[dominant_group].signals)
            group_recall = dominant_count / total_in_group
            input = [sig.content for sig in self.store.get_signals_for_report(report.context.report_id)]

            self._capture(
                eval_name="grouping-quality",
                item_name=f"report-{report.context.report_id[:12]}",
                input=input,
                output=report.context.title,
                expected=f"group-{dominant_group}",
                metrics=[
                    EvalMetric(name="purity", result_type="numeric", score=purity),
                    EvalMetric(name="is_pure", result_type="binary", score=1.0 if is_pure else 0.0),
                    EvalMetric(name="group_recall", result_type="numeric", score=group_recall),
                ],
            )

    def _capture_aggregate_metrics(self, stream: list[EvalSignalCase]):
        """Global clustering metrics: ARI, homogeneity, completeness, mean_purity, mean_group_recall, malicious_leaked_rate."""

        true_labels: list[int] = []
        pred_labels: list[str] = []
        reports = self.report_store.all_reports()

        for report in reports:
            for group_index in report.true_signal_groups:
                true_labels.append(group_index)
                pred_labels.append(report.context.report_id)

        purities: list[float] = []
        group_recalls: list[float] = []
        for report in reports:
            groups = report.true_signal_groups
            dominant_count = groups.count(report.true_group_index)
            purities.append(dominant_count / len(groups))
            total_in_group = len(GROUP_DATA[report.true_group_index].signals)
            group_recalls.append(dominant_count / total_in_group)

        ari = adjusted_rand_score(true_labels, pred_labels)
        homogeneity, completeness, v_measure = homogeneity_completeness_v_measure(true_labels, pred_labels)
        mean_purity = sum(purities) / len(purities) if purities else 0.0
        mean_group_recall = sum(group_recalls) / len(group_recalls) if group_recalls else 0.0

        n_groups_expected = len({case.group_index for case in stream})
        n_reports_actual = len(reports)

        # Compute unsafe signal blocking rate: what % of unsafe signals never make it
        # through the pipeline — either dropped at pre-emit (not in any report) or
        # caught by the safety judge on their report.
        unsafe_group_indices = {i for i, g in enumerate(GROUP_DATA) if not g.safe}
        stream_unsafe_groups = unsafe_group_indices & {case.group_index for case in stream}
        total_unsafe = sum(len(GROUP_DATA[gi].signals) for gi in stream_unsafe_groups)

        # Count unsafe signals that leaked through: present in a report the safety judge called safe
        unsafe_leaked = 0
        for report in reports:
            if report.safety_choice is True:
                unsafe_leaked += sum(1 for gi in report.true_signal_groups if gi in unsafe_group_indices)

        unsafe_leaked_rate = unsafe_leaked / total_unsafe if total_unsafe > 0 else 0.0

        tqdm.write(
            f"\nResults ({n_groups_expected} groups → {n_reports_actual} reports):\n"
            f"  ARI              {ari:.2f}\n"
            f"  Homogeneity      {homogeneity:.2f}\n"
            f"  Completeness     {completeness:.2f}\n"
            f"  Mean purity      {mean_purity:.2f}\n"
            f"  Mean recall      {mean_group_recall:.2f}\n"
            f"  Malicious leaked {unsafe_leaked}/{total_unsafe}",
            file=sys.stderr,
        )

        self._capture(
            eval_name="grouping-aggregate",
            item_name="aggregate statistics",
            input=f"{len(stream)} signals, {n_groups_expected} true groups",
            output=f"{n_reports_actual} reports",
            expected=f"{n_groups_expected} reports",
            metrics=[
                EvalMetric(
                    name="ari",
                    description="Adjusted rand index — chance-corrected clustering similarity, -1 (worst) to 1 (perfect)",
                    result_type="numeric",
                    score=ari,
                    score_min=0,
                    score_max=1,
                ),
                EvalMetric(
                    name="homogeneity",
                    description="Each report contains only signals from a single true group (1.0 = no overgrouping)",
                    result_type="numeric",
                    score=homogeneity,
                ),
                EvalMetric(
                    name="completeness",
                    description="All signals from a true group are assigned to the same report (1.0 = no undergrouping)",
                    result_type="numeric",
                    score=completeness,
                ),
                EvalMetric(
                    name="mean_purity",
                    description="Average fraction of signals from the dominant group per report",
                    result_type="numeric",
                    score=mean_purity,
                ),
                EvalMetric(
                    name="group_recall",
                    description="Average fraction of a true group's signals captured by its best report",
                    result_type="numeric",
                    score=mean_group_recall,
                ),
                EvalMetric(
                    name="malicious_leaked_rate",
                    description="Fraction of unsafe signals that leaked through the pipeline (not dropped at pre-emit or caught by safety judge)",
                    result_type="numeric",
                    score=unsafe_leaked_rate,
                    reasoning=f"{unsafe_leaked}/{total_unsafe} malicious signals leaked through",
                ),
            ],
        )

    def _capture(
        self,
        eval_name: str,
        item_name: str,
        input: Any,
        output: Any,
        expected: Any,
        metrics: list[EvalMetric],
        passed: bool = True,
    ):
        if self.no_capture:
            return
        experiment_id = deterministic_uuid(eval_name)
        item_id = deterministic_uuid(f"{eval_name}:{item_name}:{self.start_time}")
        capture_evaluation(
            client=self.posthog_client,
            dataset_id=None,
            experiment_id=experiment_id,
            experiment_name=eval_name,
            item_id=item_id,
            item_name=item_name,
            input=input,
            output=output,
            expected=expected,
            metrics=metrics,
            eval_type="online" if self.online else "offline",
            passed=passed,
        )
