"""Experiment precompute canary: detects broken or unstable precomputed experiment results in production.

Samples (experiment, metric) pairs across precompute-enabled teams and runs each metric three times:
runs A and B force the precomputed path (``PrecomputationMode.PRECOMPUTED``), run C forces a direct events
scan (``PrecomputationMode.DIRECT``). Two checks per metric:

- stability (A vs B): two precomputed reads seconds apart must agree. Funnel reads are fully frozen, so the
  tolerance is strict; mean/ratio metrics join live event values onto frozen exposures, so only the exposure
  counts are held to the strict tolerance.
- correctness (B vs C): the precomputed read must agree with the events table within a loose tolerance that
  covers live ingestion between the cache writes and the direct scan.

The bug class this guards (multi-node ClickHouse read-your-writes, see
``products/analytics_platform/backend/lazy_computation/CONSISTENCY.md``) cannot be reproduced in dev/CI
(single-node, synchronous inserts) — production observation is the point of the canary.

Runbook:

- Outcomes land in Prometheus via the pushgateway (job ``experiment_precompute_canary``):
  ``experiment_precompute_canary_outcomes{outcome=pass|divergence|path_flip|error|skipped}``,
  ``experiment_precompute_canary_max_deviation{check=stability|correctness}``, and
  ``experiment_precompute_canary_last_run_timestamp``. Suggested alerts:
  ``outcomes{outcome="divergence"} > 0`` (experiment results unstable between refreshes or cache content
  wrong) and ``last_run_timestamp`` stale for >48h (the canary itself is broken).
- A divergence also posts to Slack (``settings.EXPERIMENT_CANARY_SLACK_WEBHOOK_URL``; unset → skipped) and
  emits a structured ``experiment_precompute_canary_divergence`` error log with each run's per-variant
  numbers and the ``experiment-canary-*`` client_query_ids to look up in ``system.query_log``.
- On-demand forensics run against one experiment:
  ``python manage.py run_experiment_canary --experiment-id <id>``.
"""

import time
import uuid
import random
import dataclasses
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

import requests
import structlog
from prometheus_client import Gauge

from posthog.schema import ExperimentQuery, PrecomputationMode

from posthog.clickhouse.query_tagging import tags_context
from posthog.metrics import pushed_metrics_registry
from posthog.models.scoping import team_scope

from products.experiments.backend.hogql_queries.experiment_query_runner import ExperimentQueryRunner
from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig
from products.experiments.backend.temporal.metric_resolution import (
    ExperimentMetric,
    build_metric,
    find_metric_dict,
    iter_metric_dicts,
)
from products.experiments.backend.temporal.models import (
    ALL_OUTCOMES,
    MAX_CANARY_DETAIL_LENGTH,
    OUTCOME_DIVERGENCE,
    OUTCOME_ERROR,
    OUTCOME_PASS,
    OUTCOME_PATH_FLIP,
    OUTCOME_SKIPPED,
    CanaryMetricResult,
    CanaryMetricTarget,
    CanaryReportInputs,
    CanaryRunSnapshot,
    CanaryVariantStats,
    ExperimentPrecomputeCanaryInputs,
)

logger = structlog.get_logger(__name__)

# Frozen-vs-frozen reads should be identical; the only legitimate noise is ReplacingMergeTree background
# merges collapsing a handful of duplicate-key rows (measured ~1 in 40K). The incident signature was 15-40%.
STRICT_TOLERANCE = 0.001
# Precomputed-vs-direct (and mean-metric sums, which join live values) legitimately drift by the few minutes
# of ingestion between the cache writes and the comparison read.
LOOSE_TOLERANCE = 0.02

# Below this, a single user moves a variant by more than the strict tolerance and comparison is meaningless.
MIN_EXPOSURES_PER_VARIANT = 100

# Only metric types that use the precompute path. Retention metrics don't, so a paired run tests nothing.
ELIGIBLE_METRIC_TYPES = ("funnel", "mean", "ratio")

# Experiments must have been running this long to be sampled — comfortably past the runner's 12h
# precomputation gate, with enough accumulated exposures for the comparison to be meaningful.
MIN_EXPERIMENT_RUNTIME = timedelta(days=2)

_CANARY_RUNS: tuple[tuple[str, PrecomputationMode], ...] = (
    ("a", PrecomputationMode.PRECOMPUTED),
    ("b", PrecomputationMode.PRECOMPUTED),
    ("c", PrecomputationMode.DIRECT),
)


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------


def _eligible_experiments() -> list[Experiment]:
    """Running experiments on precompute-enabled teams, past the minimum runtime."""
    team_ids = list(
        TeamExperimentsConfig.objects.filter(experiment_precomputation_enabled=True).values_list("team_id", flat=True)
    )
    if not team_ids:
        return []
    return list(
        Experiment.objects.filter(
            team_id__in=team_ids,
            start_date__lte=timezone.now() - MIN_EXPERIMENT_RUNTIME,
            end_date__isnull=True,
        )
        .exclude(deleted=True)
        .exclude(archived=True)
        .select_related("team")
        # Metric discovery walks saved metrics per experiment; prefetch to avoid an N+1 over the sample.
        .prefetch_related("experimenttosavedmetric_set__saved_metric")
    )


def _experiment_metric_dicts(experiment: Experiment) -> list[dict[str, Any]]:
    with team_scope(experiment.team_id, canonical=True):
        return [m for m in iter_metric_dicts(experiment) if m.get("metric_type") in ELIGIBLE_METRIC_TYPES]


def _forensics_targets(experiment_id: int, metric_uuids: list[str] | None) -> list[CanaryMetricTarget]:
    """On-demand mode: all eligible metrics of one experiment, quotas and runtime gates ignored."""
    experiment = (
        Experiment.objects.filter(id=experiment_id, start_date__isnull=False)
        .exclude(deleted=True)
        .select_related("team")
        .first()
    )
    if experiment is None:
        logger.warning("experiment_precompute_canary_forensics_target_not_found", experiment_id=experiment_id)
        return []

    targets: list[CanaryMetricTarget] = []
    seen_uuids: set[str] = set()
    for metric_dict in _experiment_metric_dicts(experiment):
        metric_uuid = metric_dict["uuid"]
        if metric_uuid in seen_uuids or (metric_uuids and metric_uuid not in metric_uuids):
            continue
        seen_uuids.add(metric_uuid)
        targets.append(
            CanaryMetricTarget(
                team_id=experiment.team_id,
                experiment_id=experiment.id,
                metric_uuid=metric_uuid,
                metric_type=metric_dict["metric_type"],
            )
        )
    return targets


def sample_canary_targets_sync(inputs: ExperimentPrecomputeCanaryInputs) -> list[CanaryMetricTarget]:
    """Pick a sample of metrics across eligible experiments: shuffle experiments, take up to
    per_experiment_cap metrics from each into the remaining per-type quotas, stop when quotas are full.
    Under-filled when the eligible population is small — run what we have. Output stays grouped by
    experiment so metrics sharing an exposures cache run adjacently."""
    close_old_connections()

    if inputs.experiment_id is not None:
        return _forensics_targets(inputs.experiment_id, inputs.metric_uuids)

    quotas = {"funnel": inputs.funnel_quota, "mean": inputs.mean_quota, "ratio": inputs.ratio_quota}
    experiments = _eligible_experiments()
    random.shuffle(experiments)

    targets: list[CanaryMetricTarget] = []
    for experiment in experiments:
        if not any(quotas.values()):
            break
        metric_dicts = _experiment_metric_dicts(experiment)
        random.shuffle(metric_dicts)
        taken = 0
        seen_uuids: set[str] = set()
        for metric_dict in metric_dicts:
            if taken == inputs.per_experiment_cap:
                break
            metric_type = metric_dict["metric_type"]
            metric_uuid = metric_dict["uuid"]
            if quotas.get(metric_type, 0) <= 0 or metric_uuid in seen_uuids:
                continue
            seen_uuids.add(metric_uuid)
            targets.append(
                CanaryMetricTarget(
                    team_id=experiment.team_id,
                    experiment_id=experiment.id,
                    metric_uuid=metric_uuid,
                    metric_type=metric_type,
                )
            )
            quotas[metric_type] -= 1
            taken += 1

    logger.info(
        "experiment_precompute_canary_sampled",
        target_count=len(targets),
        experiment_count=len({t.experiment_id for t in targets}),
        unfilled_quotas={k: v for k, v in quotas.items() if v > 0},
    )
    return targets


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class CanaryVerdict:
    outcome: str
    stability_deviation: float | None = None
    correctness_deviation: float | None = None
    detail: str | None = None


def relative_deviation(a: float, b: float) -> float:
    return abs(a - b) / max(abs(a), abs(b), 1.0)


def _max_deviation(run_x: CanaryRunSnapshot, run_y: CanaryRunSnapshot) -> float:
    deviations = [0.0]
    for key, stats_x in run_x.variants.items():
        stats_y = run_y.variants[key]
        deviations.append(relative_deviation(stats_x.sum, stats_y.sum))
        deviations.append(relative_deviation(stats_x.number_of_samples, stats_y.number_of_samples))
    return max(deviations)


def _stability_violated(metric_type: str, run_a: CanaryRunSnapshot, run_b: CanaryRunSnapshot) -> bool:
    for key, stats_a in run_a.variants.items():
        stats_b = run_b.variants[key]
        if relative_deviation(stats_a.number_of_samples, stats_b.number_of_samples) > STRICT_TOLERANCE:
            return True
        # Funnel sums are reads of frozen caches; mean/ratio sums join live event values and drift.
        sum_tolerance = STRICT_TOLERANCE if metric_type == "funnel" else LOOSE_TOLERANCE
        if relative_deviation(stats_a.sum, stats_b.sum) > sum_tolerance:
            return True
    return False


def evaluate_canary_runs(
    metric_type: str, run_a: CanaryRunSnapshot, run_b: CanaryRunSnapshot, run_c: CanaryRunSnapshot
) -> CanaryVerdict:
    """Compare the three runs: A↔B is the stability check, B↔C the correctness check (B is adjacent in
    time to C, minimizing live-ingestion drift)."""
    runs = (run_a, run_b, run_c)
    if any(not run.variants for run in runs):
        return CanaryVerdict(outcome=OUTCOME_SKIPPED, detail="empty results (no exposures yet)")

    # Checked before the variant-set comparison: a flipped run compares live vs frozen data, so it can
    # also explain a variant showing up in one run but not another.
    flipped = [run.label for run in (run_a, run_b) if not run.is_precomputed]
    if flipped:
        # A forced-precomputed run fell back to the direct scan (e.g. the lazy computation executor timed
        # out). Deviation is expected — not a divergence.
        return CanaryVerdict(outcome=OUTCOME_PATH_FLIP, detail=f"run(s) {', '.join(flipped)} fell back to direct scan")

    variant_keys = {frozenset(run.variants) for run in runs}
    if len(variant_keys) > 1:
        return CanaryVerdict(outcome=OUTCOME_ERROR, detail="variant set mismatch between runs")

    # Gated on every run: a thin variant in the direct scan would make the correctness comparison just as
    # meaningless as one in the precomputed reads.
    if min(stats.number_of_samples for run in runs for stats in run.variants.values()) < MIN_EXPOSURES_PER_VARIANT:
        return CanaryVerdict(
            outcome=OUTCOME_SKIPPED, detail=f"fewer than {MIN_EXPOSURES_PER_VARIANT} exposures in a variant"
        )

    stability_deviation = _max_deviation(run_a, run_b)
    correctness_deviation = _max_deviation(run_b, run_c)
    diverged = _stability_violated(metric_type, run_a, run_b) or correctness_deviation > LOOSE_TOLERANCE

    return CanaryVerdict(
        outcome=OUTCOME_DIVERGENCE if diverged else OUTCOME_PASS,
        stability_deviation=stability_deviation,
        correctness_deviation=correctness_deviation,
        detail="deviation beyond tolerance" if diverged else None,
    )


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def _execute_canary_run(
    experiment: Experiment, metric: ExperimentMetric, mode: PrecomputationMode, label: str, query_id: str
) -> CanaryRunSnapshot:
    # Fresh runner per run: the runner caches precomputation state from its first execution. The workload
    # is deliberately left at its default (online cluster) — the bug class this canary hunts is only
    # observable on the path users actually read from. user_facing=False keeps original exceptions intact
    # for Temporal's retry classification instead of converting them to friendly ValidationErrors.
    runner = ExperimentQueryRunner(
        query=ExperimentQuery(experiment_id=experiment.id, metric=metric, precomputation_mode=mode),
        team=experiment.team,
        user_facing=False,
        # Userless background recompute. Warehouse access is enforced when the metric is authored, so
        # resolve warehouse tables here instead of failing closed.
        bypass_warehouse_access_control=True,
    )
    with tags_context(client_query_id=query_id, trigger="experiment_precompute_canary"):
        response = runner.calculate()

    stats_entries = [*([response.baseline] if response.baseline else []), *(response.variant_results or [])]
    return CanaryRunSnapshot(
        label=label,
        query_id=query_id,
        is_precomputed=bool(response.is_precomputed),
        variants={
            entry.key: CanaryVariantStats(sum=entry.sum, number_of_samples=entry.number_of_samples)
            for entry in stats_entries
        },
    )


def run_metric_canary_sync(target: CanaryMetricTarget) -> CanaryMetricResult:
    """Run one metric three times (precomputed, precomputed, direct) and compare.

    Deterministic dead ends (experiment/metric gone, unparseable definition) return a skipped result.
    Query failures raise so Temporal retries the whole triple — the comparisons require runs adjacent in
    time, so retrying a single run against stale siblings would skew the pair.
    """
    close_old_connections()

    def _skipped(detail: str) -> CanaryMetricResult:
        return CanaryMetricResult(target=target, outcome=OUTCOME_SKIPPED, detail=detail)

    with team_scope(target.team_id, canonical=True):
        experiment = (
            Experiment.objects.filter(id=target.experiment_id, team_id=target.team_id, start_date__isnull=False)
            .exclude(deleted=True)
            .select_related("team")
            .first()
        )
        if experiment is None:
            return _skipped("experiment not found, deleted, or missing start_date")

        metric_dict = find_metric_dict(experiment, target.metric_uuid)
        if metric_dict is None:
            return _skipped("metric no longer present on experiment")
        # Re-resolved, so the type can differ from what was sampled (metric edited in between). The verdict
        # rules depend on it, so use the current type — and bail if it changed to an ineligible one.
        metric_type = metric_dict.get("metric_type")
        if metric_type not in ELIGIBLE_METRIC_TYPES:
            return _skipped(f"metric type changed to ineligible {metric_type!r}")
        try:
            metric = build_metric(metric_dict)
        except Exception as e:
            return _skipped(f"metric definition not parseable: {str(e)[:MAX_CANARY_DETAIL_LENGTH]}")

        canary_id = uuid.uuid4().hex[:12]
        runs: list[CanaryRunSnapshot] = []
        for label, mode in _CANARY_RUNS:
            query_id = f"experiment-canary-{canary_id}-{label}"
            try:
                runs.append(_execute_canary_run(experiment, metric, mode, label, query_id))
            except Exception:
                logger.warning(
                    "experiment_precompute_canary_run_failed",
                    team_id=target.team_id,
                    experiment_id=target.experiment_id,
                    metric_uuid=target.metric_uuid,
                    run_label=label,
                    query_id=query_id,
                    exc_info=True,
                )
                raise

        verdict = evaluate_canary_runs(metric_type, *runs)
        result = CanaryMetricResult(
            target=target,
            outcome=verdict.outcome,
            stability_deviation=verdict.stability_deviation,
            correctness_deviation=verdict.correctness_deviation,
            runs=runs,
            detail=verdict.detail,
        )

    if result.outcome == OUTCOME_DIVERGENCE:
        # Full forensics in one log line: enough to investigate without re-running the canary.
        logger.error(
            "experiment_precompute_canary_divergence",
            team_id=target.team_id,
            experiment_id=target.experiment_id,
            metric_uuid=target.metric_uuid,
            metric_type=target.metric_type,
            stability_deviation=result.stability_deviation,
            correctness_deviation=result.correctness_deviation,
            runs=[dataclasses.asdict(run) for run in runs],
        )
    return result


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _format_run_line(run: CanaryRunSnapshot) -> str:
    path = "precomputed" if run.is_precomputed else "direct"
    variants = ", ".join(
        f"{key} {stats.sum:g}/{stats.number_of_samples}" for key, stats in sorted(run.variants.items())
    )
    return f"{run.label} [{path}] `{run.query_id}`: {variants}"


def _build_slack_blocks(divergent: list[CanaryMetricResult], counts: dict[str, int], manual: bool) -> list[dict]:
    header = ":rotating_light: *Experiment precompute canary: divergence detected*"
    if manual:
        header += " (manual run)"
    blocks: list[dict[str, Any]] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": header}},
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "  |  ".join(f"{outcome}: {counts.get(outcome, 0)}" for outcome in ALL_OUTCOMES),
                }
            ],
        },
        {"type": "divider"},
    ]
    for result in divergent:
        target = result.target
        lines = [
            f":red_circle: *team {target.team_id} / experiment {target.experiment_id} / metric `{target.metric_uuid}` ({target.metric_type})*",
            f"stability deviation {100 * (result.stability_deviation or 0):.4f}% | correctness deviation {100 * (result.correctness_deviation or 0):.4f}%",
            *(_format_run_line(run) for run in result.runs),
        ]
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}})
    return blocks


def _send_slack_alert(divergent: list[CanaryMetricResult], counts: dict[str, int], manual: bool) -> None:
    webhook_url = settings.EXPERIMENT_CANARY_SLACK_WEBHOOK_URL
    if not webhook_url:
        logger.info("experiment_precompute_canary_slack_not_configured")
        return
    try:
        response = requests.post(
            webhook_url, json={"blocks": _build_slack_blocks(divergent, counts, manual)}, timeout=10
        )
        response.raise_for_status()
    except requests.RequestException as e:
        # Not re-raised: the divergence is already in the error log and the Prometheus gauges.
        # str(e) would include the request URL, i.e. the webhook secret — log only safe fields.
        logger.warning(
            "experiment_precompute_canary_slack_failed",
            error_type=type(e).__name__,
            status_code=getattr(e.response, "status_code", None),
        )


def report_canary_results_sync(report: CanaryReportInputs) -> None:
    counts = dict.fromkeys(ALL_OUTCOMES, 0)
    for result in report.results:
        counts[result.outcome] = counts.get(result.outcome, 0) + 1

    logger.info("experiment_precompute_canary_run_finished", triggered_manually=report.triggered_manually, **counts)

    if not report.triggered_manually:
        with pushed_metrics_registry("experiment_precompute_canary") as registry:
            outcome_gauge = Gauge(
                "experiment_precompute_canary_outcomes",
                "Number of metrics per outcome in the last canary run",
                labelnames=["outcome"],
                registry=registry,
            )
            for outcome, count in counts.items():
                outcome_gauge.labels(outcome=outcome).set(count)
            deviation_gauge = Gauge(
                "experiment_precompute_canary_max_deviation",
                "Max relative deviation observed across metrics in the last canary run",
                labelnames=["check"],
                registry=registry,
            )
            deviation_gauge.labels(check="stability").set(
                max((r.stability_deviation or 0.0 for r in report.results), default=0.0)
            )
            deviation_gauge.labels(check="correctness").set(
                max((r.correctness_deviation or 0.0 for r in report.results), default=0.0)
            )
            Gauge(
                "experiment_precompute_canary_last_run_timestamp",
                "Unix timestamp of the last canary run; staleness means the canary itself is broken",
                registry=registry,
            ).set(time.time())

    divergent = [result for result in report.results if result.outcome == OUTCOME_DIVERGENCE]
    if divergent:
        _send_slack_alert(divergent, counts, report.triggered_manually)
