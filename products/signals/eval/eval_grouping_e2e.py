"""
Grouping e2e eval — clustering quality against known ground-truth groups.

Feeds synthetic signals through the real grouping pipeline (LLM matching,
embeddings) with mocked infrastructure (ClickHouse, Temporal).

One eval item per predicted report, with metrics:
- purity (numeric 0-1): fraction of signals from the dominant true group
- is_pure (binary): whether all signals belong to a single true group
- group_recall (numeric 0-1): fraction of the dominant group captured (undergrouping)

Plus global metrics: ari, homogeneity, completeness, v_measure, mean_purity, mean_group_recall.

Note: --limit truncates the interleaved stream, so metrics like completeness and
group_recall will penalize the pipeline for groups it never saw. Use with caution.

Run:
    pytest products/signals/eval/eval_grouping_e2e.py -xvs --log-cli-level=WARNING
    pytest products/signals/eval/eval_grouping_e2e.py -xvs --log-cli-level=WARNING [--limit <limit>] [--no-capture]
"""

import uuid
import random
import logging
from collections import Counter

import pytest

from sklearn.metrics import adjusted_rand_score, completeness_score, homogeneity_score, v_measure_score

from products.signals.backend.api import emit_signal
from products.signals.backend.models import SignalReport
from products.signals.eval.capture import EvalMetric, capture_evaluation, deterministic_uuid
from products.signals.eval.data_spec import SignalSpec
from products.signals.eval.fixtures.grouping_data import GROUP_DATA

RNG_SEED = 1337
EVAL_NAME = "signal-grouping-e2e"

logger = logging.getLogger(__name__)


def get_signals_stream() -> list[tuple[int, SignalSpec]]:
    """Interleave signals across groups randomly, preserving within-group order.

    Returns (group_index, signal) tuples so callers know the ground truth.
    """
    rng = random.Random(RNG_SEED)
    cursors = [0] * len(GROUP_DATA)
    stream: list[tuple[int, SignalSpec]] = []

    def get_active():
        return [i for i, g in enumerate(GROUP_DATA) if cursors[i] < len(g.signals)]

    while active := get_active():
        k = rng.randint(0, len(active) - 1)
        group_idx = active[k]
        signal = GROUP_DATA[group_idx].signals[cursors[group_idx]]
        cursors[group_idx] += 1
        stream.append((group_idx, signal))

    return stream


class TestGroupingPipeline:
    @pytest.fixture(autouse=True)
    def _setup(self, team, mock_temporal, mock_clickhouse, posthog_client, limit, no_capture):
        self.team = team
        self.store = mock_clickhouse
        self.posthog_client = posthog_client
        self.limit = limit
        self.no_capture = no_capture

    @pytest.mark.django_db(transaction=True)
    async def test_grouping_pipeline(self):
        stream = get_signals_stream()
        if self.limit:
            stream = stream[: self.limit]
            groups_in_stream = {g_idx for g_idx, _ in stream}
            total_groups = len(GROUP_DATA)
            if len(groups_in_stream) < total_groups:
                logger.warning(
                    "--limit %d: stream covers %d/%d groups — completeness and group_recall will be unreliable",
                    self.limit,
                    len(groups_in_stream),
                    total_groups,
                )

        # Emit signals through the real pipeline

        n_groups = len({g_idx for g_idx, _ in stream})
        logger.warning("Emitting %d signals from %d ground-truth groups...", len(stream), n_groups)

        ground_truth: dict[str, int] = {}
        signal_ids_in_order: list[str] = []

        for group_idx, signal in stream:
            signal_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"eval:{group_idx}:{signal.description}"))
            ground_truth[signal_id] = group_idx
            signal_ids_in_order.append(signal_id)

            await emit_signal(
                team=self.team,
                source_product=signal.source_product,
                source_type=signal.source_type,
                source_id=signal_id,
                description=signal.description,
            )

        logger.warning("Pipeline complete. %d signals stored.", len(self.store._signals))

        # Build predicted grouping from store

        predicted: dict[str, str] = {}
        signal_content: dict[str, str] = {}
        for sig in self.store._signals:
            if not sig.deleted:
                predicted[sig.source_id] = sig.report_id
                signal_content[sig.source_id] = sig.content

        aligned_ids = [sid for sid in signal_ids_in_order if sid in predicted]
        assert aligned_ids, (
            f"No signals were stored — pipeline produced no output "
            f"({len(signal_ids_in_order)} emitted, {len(self.store._signals)} in store)"
        )
        dropped = len(signal_ids_in_order) - len(aligned_ids)
        if dropped:
            logger.warning("Pipeline dropped %d/%d signals", dropped, len(signal_ids_in_order))

        true_labels = [ground_truth[sid] for sid in aligned_ids]
        pred_labels = [predicted[sid] for sid in aligned_ids]

        logger.warning("Computing metrics for %d aligned signals...", len(aligned_ids))

        # Compute global clustering metrics

        ari = adjusted_rand_score(true_labels, pred_labels)
        homogeneity = homogeneity_score(true_labels, pred_labels)
        completeness = completeness_score(true_labels, pred_labels)
        v_measure = v_measure_score(true_labels, pred_labels)

        n_true_groups = len(set(true_labels))
        n_pred_groups = len(set(pred_labels))
        report_titles = {str(r.id): r.title async for r in SignalReport.objects.filter(team=self.team)}

        # Per-report breakdown and purity scoring

        experiment_id = deterministic_uuid(EVAL_NAME)

        true_group_sizes = Counter(true_labels)

        report_purities: list[float] = []
        report_recalls: list[float] = []
        report_rows: list[str] = []

        for report_id in sorted(set(pred_labels)):
            title = report_titles.get(report_id, "(untitled)")
            member_ids = [sid for sid in aligned_ids if predicted[sid] == report_id]
            true_group_counts = Counter(ground_truth[sid] for sid in member_ids)

            # Purity: fraction of signals from the dominant true group
            dominant_count = max(true_group_counts.values())
            purity = dominant_count / len(member_ids)
            report_purities.append(purity)

            # Group recall: fraction of the dominant true group captured by this report
            dominant_group = true_group_counts.most_common(1)[0][0]
            group_recall = dominant_count / true_group_sizes[dominant_group]
            report_recalls.append(group_recall)

            # Build output: list of signals in this report
            signals_output = [
                {
                    "signal_id": sid,
                    "true_group": ground_truth[sid],
                    "true_scenario": GROUP_DATA[ground_truth[sid]].scenario,
                    "content": signal_content.get(sid, "")[:200],
                }
                for sid in member_ids
            ]

            is_pure = len(true_group_counts) == 1

            report_rows.append(
                f"  {report_id[:12]}: {title} "
                f"({len(member_ids)} signals, purity={purity:.2f}, recall={group_recall:.2f}, "
                f"groups={dict(true_group_counts)})"
            )

            if not self.no_capture:
                item_id = deterministic_uuid(f"{EVAL_NAME}:{report_id}")
                capture_evaluation(
                    client=self.posthog_client,
                    experiment_id=experiment_id,
                    experiment_name=EVAL_NAME,
                    item_id=item_id,
                    item_name=f"{title} ({len(member_ids)} signals)",
                    input=f"Report: {title}\nScenario (dominant): {GROUP_DATA[dominant_group].scenario}",
                    output=signals_output,
                    expected=None,
                    metrics=[
                        EvalMetric(
                            name="purity",
                            description="Fraction of signals from the dominant true group in a predicted report",
                            result_type="numeric",
                            score=purity,
                            score_min=0.0,
                            score_max=1.0,
                            reasoning=f"{'Pure' if is_pure else 'Mixed'}: {dict(true_group_counts)}",
                        ),
                        EvalMetric(
                            name="is_pure",
                            description="Whether all signals in a predicted report belong to a single true group",
                            result_type="binary",
                            score=1.0 if is_pure else 0.0,
                            score_min=0.0,
                            score_max=1.0,
                            reasoning=f"{'All signals from group ' + str(dominant_group) if is_pure else 'Mixed: ' + str(dict(true_group_counts))}",
                        ),
                        EvalMetric(
                            name="group_recall",
                            description="Fraction of the dominant true group's signals captured by this report — low values indicate undergrouping",
                            result_type="numeric",
                            score=group_recall,
                            score_min=0.0,
                            score_max=1.0,
                            reasoning=f"{dominant_count}/{true_group_sizes[dominant_group]} signals from group {dominant_group}",
                        ),
                    ],
                )

        mean_purity = sum(report_purities) / len(report_purities) if report_purities else 0.0
        mean_group_recall = sum(report_recalls) / len(report_recalls) if report_recalls else 0.0

        results = "\n".join(
            [
                "=" * 60,
                "GROUPING EVAL RESULTS",
                "=" * 60,
                f"Signals: {len(aligned_ids)} | True groups: {n_true_groups} | Predicted groups: {n_pred_groups}",
                f"ARI: {ari:.3f} | Homogeneity: {homogeneity:.3f} | Completeness: {completeness:.3f} | V-measure: {v_measure:.3f}",
                "",
                "Per-report breakdown:",
                *report_rows,
                "",
                f"Global: mean_purity={mean_purity:.3f} mean_group_recall={mean_group_recall:.3f} ARI={ari:.3f} V-measure={v_measure:.3f}",
                "=" * 60,
            ]
        )
        logger.warning("\n%s", results)

        if not self.no_capture:
            global_input = f"{len(aligned_ids)} signals, {n_true_groups} true groups, {n_pred_groups} predicted groups"
            capture_evaluation(
                client=self.posthog_client,
                experiment_id=f"{experiment_id}-aggregate",
                experiment_name=EVAL_NAME,
                item_id=deterministic_uuid(f"{EVAL_NAME}:global"),
                item_name="global",
                input=global_input,
                output=None,
                expected=None,
                metrics=[
                    EvalMetric(
                        name="ari",
                        description="Adjusted Rand Index — similarity between predicted and true groupings, adjusted for chance",
                        result_type="numeric",
                        score=ari,
                        score_min=-1.0,
                        score_max=1.0,
                    ),
                    EvalMetric(
                        name="homogeneity",
                        description="Whether each predicted report contains only signals from a single true group",
                        result_type="numeric",
                        score=homogeneity,
                        score_min=0.0,
                        score_max=1.0,
                    ),
                    EvalMetric(
                        name="completeness",
                        description="Whether all signals from a true group are assigned to the same predicted report",
                        result_type="numeric",
                        score=completeness,
                        score_min=0.0,
                        score_max=1.0,
                    ),
                    EvalMetric(
                        name="v_measure",
                        description="Harmonic mean of homogeneity and completeness",
                        result_type="numeric",
                        score=v_measure,
                        score_min=0.0,
                        score_max=1.0,
                    ),
                    EvalMetric(
                        name="mean_purity",
                        description="Average purity across all predicted reports",
                        result_type="numeric",
                        score=mean_purity,
                        score_min=0.0,
                        score_max=1.0,
                    ),
                    EvalMetric(
                        name="mean_group_recall",
                        description="Average group recall across all predicted reports — low values indicate undergrouping",
                        result_type="numeric",
                        score=mean_group_recall,
                        score_min=0.0,
                        score_max=1.0,
                    ),
                ],
            )
            self.posthog_client.flush()
