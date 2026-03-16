"""
Grouping quality eval — per-group coherence assessment.

Runs the grouping pipeline, then an LLM judge evaluates each group for
coherence, weak-chaining, and misplaced signals.

One eval item per group, with metrics:
- coherence (numeric 0-1): group coherence score from judge (1-5 normalized)
- no_misplaced_signals (binary): whether the group has zero misplaced signals
- no_weak_chain (binary): whether the group avoids weak-chaining (coherence > 2)

Run:
    pytest products/signals/eval/grouping/eval_grouping_quality.py -xvs --log-cli-level=WARNING
    pytest products/signals/eval/grouping/eval_grouping_quality.py -xvs --log-cli-level=WARNING --limit 5
"""

import sys
import json
import logging
from pathlib import Path

import pytest

from evaluate import evaluate_grouping_quality, format_evaluation
from harness import EmbeddingCache, TestSignal, run_harness
from pr_specificity_and_group_aware import PRSpecificityAndGroupAwareStrategy

from products.signals.eval.framework import EvalMetric, capture_evaluation, deterministic_uuid

GROUPING_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(GROUPING_DIR))

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"

logger = logging.getLogger(__name__)

EVAL_NAME = "signal-grouping-quality"


def load_grouping_signals() -> list[dict]:
    with open(FIXTURES_DIR / "grouping_signals.json") as f:
        return json.load(f)


def serialize_signal(sig: TestSignal) -> dict:
    """Convert TestSignal into a JSON-safe structure for eval logging."""
    return {
        "signal_id": sig.signal_id,
        "content": sig.content[:500],  # trim to keep payload reasonable
        "source_product": sig.source_product,
        "source_type": sig.source_type,
    }


async def run_grouping_pipeline(signals_data: list[dict]):
    signals = [
        TestSignal(
            signal_id=s["signal_id"],
            content=s["content"],
            source_product=s["source_product"],
            source_type=s["source_type"],
            source_id=s.get("source_id", ""),
            weight=s.get("weight", 0.5),
            timestamp=s.get("timestamp", ""),
            extra=s.get("extra") or {},
            original_report_id=s.get("original_report_id", ""),
        )
        for s in signals_data
    ]

    embedding_cache = EmbeddingCache()
    strategy = PRSpecificityAndGroupAwareStrategy()

    logger.warning("Embedding %d signals...", len(signals))
    result = await run_harness(strategy, signals, embedding_cache)
    logger.warning("Harness complete. %d groups formed.", len(result.groups))

    return result


class TestGroupingQuality:
    @pytest.fixture(autouse=True)
    def _setup(self, posthog_client, limit):
        self.posthog_client = posthog_client
        self.limit = limit

    @pytest.mark.django_db
    async def test_grouping_quality(self):
        signals_data = load_grouping_signals()

        if self.limit:
            signals_data = signals_data[: self.limit]

        result = await run_grouping_pipeline(signals_data)

        logger.warning("Running grouping quality judge...")
        evaluation = await evaluate_grouping_quality(result)
        logger.warning("\n%s", format_evaluation(evaluation))

        experiment_id = deterministic_uuid(EVAL_NAME)
        signal_lookup = {s.signal_id: s for s in result.signals}

        group_assessments = evaluation.get("group_assessments", [])
        logger.warning("Judge returned %d group assessments", len(group_assessments))

        if not group_assessments:
            logger.warning("Raw judge response: %s", json.dumps(evaluation)[:500])

        for ga in group_assessments:
            group_id = ga["group_id"]
            signal_count = ga.get("signal_count", 0)
            coherence = ga.get("coherence_score")
            misplaced = ga.get("misplaced_signal_count", 0)
            assessment = ga.get("assessment", "")

            matching_group = next(
                (g for g in result.groups.values() if g.report_id.startswith(group_id)),
                None,
            )

            group_title = (matching_group.title or "(untitled)")[:80] if matching_group else "(unknown)"

            item_id = deterministic_uuid(f"{EVAL_NAME}:{group_id}")
            item_name = f"{group_title} (group size: {signal_count})"

            input_signals = []
            if matching_group:
                for sid in matching_group.signal_ids:
                    sig = signal_lookup.get(sid)
                    if sig:
                        input_signals.append(serialize_signal(sig))

            is_singleton = coherence is None
            status = "SINGLETON" if is_singleton else f"coherence={coherence}/5"

            logger.warning(
                "  Group %s (%d signals) — %s | misplaced=%d | %s",
                group_id,
                signal_count,
                status,
                misplaced,
                assessment[:60],
            )

            output_str = (
                f"Group: {group_id} — {group_title}\n"
                f"Signals: {signal_count}\n"
                f"Coherence: {coherence}/5\n"
                f"Misplaced: {misplaced}\n"
                f"Assessment: {assessment}"
            )

            common = {
                "client": self.posthog_client,
                "experiment_id": experiment_id,
                "experiment_name": EVAL_NAME,
                "item_id": item_id,
                "item_name": item_name,
                "input": input_signals,
                "output": output_str,
                "expected": None,
            }

            coherence_score = 1.0 if is_singleton else coherence / 5.0

            coherence_reasoning = (
                "Singleton (coherent by definition)" if is_singleton else f"Coherence {coherence}/5: {assessment}"
            )

            capture_evaluation(
                **common,
                metric=EvalMetric(
                    name="coherence",
                    version="1",
                    result_type="numeric",
                    score=coherence_score,
                    score_min=0,
                    score_max=1,
                    reasoning=coherence_reasoning,
                ),
            )

            if not is_singleton:
                capture_evaluation(
                    **common,
                    metric=EvalMetric(
                        name="no_weak_chain",
                        version="1",
                        result_type="binary",
                        score=1.0 if coherence > 2 else 0.0,
                        score_min=0,
                        score_max=1,
                        reasoning=f"Coherence {coherence}/5 {'> 2 (no weak chain)' if coherence > 2 else '<= 2 (weak-chained)'}",
                    ),
                )

            capture_evaluation(
                **common,
                metric=EvalMetric(
                    name="no_misplaced_signals",
                    version="1",
                    result_type="binary",
                    score=1.0 if misplaced == 0 else 0.0,
                    score_min=0,
                    score_max=1,
                    reasoning=f"{misplaced} misplaced signal{'s' if misplaced != 1 else ''} in group of {signal_count}",
                ),
            )

            capture_evaluation(
                **common,
                metric=EvalMetric(
                    name="is_group",
                    version="1",
                    result_type="binary",
                    score=0.0 if is_singleton else 1.0,
                    score_min=0,
                    score_max=1,
                    reasoning="Singleton" if is_singleton else f"Group of {signal_count}",
                ),
            )

        undergrouping = evaluation.get("undergrouping", [])

        if undergrouping:
            logger.warning("\nUnder-grouping issues:")
            for ug in undergrouping:
                logger.warning(
                    "  %s should merge with %s: %s",
                    ug["singleton_id"],
                    ug["should_merge_with"],
                    ug["reason"],
                )

        overall = evaluation.get("overall_score", "?")
        overall_assessment = evaluation.get("overall_assessment", "")

        logger.warning("\nOverall: %s/5 — %s", overall, overall_assessment)

        self.posthog_client.flush()
