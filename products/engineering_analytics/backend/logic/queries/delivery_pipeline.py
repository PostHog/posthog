"""Curated query: the pre-merge legs of a PR's path to production.

``created_at`` -> first merge-queue gate run starting -> ``merged_at``.

Nothing records when a PR entered the queue (Trunk keeps only each entry's last transition), so
the first gate run starting is the earliest queue activity in the data; review, rework, idle,
and the wait for a slot stay fused in one leg.

The post-merge leg is the DORA lead-time read in ``dora.py``: a deploy timestamp alone cannot
say which merges a deploy contains. Bots and drafts are excluded (the locked cycle-time recipe),
unlike the merge-queue overview, which measures the queue over every author.
"""

from datetime import datetime

from posthog.hogql import ast

from posthog.dataclasses import frozen

from products.engineering_analytics.backend.facade.contracts import DeliveryPipeline, DeliveryStage, DeliveryStageTiming
from products.engineering_analytics.backend.logic.merge_queue import GATE_RUN_LOOKBACK
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource, opt_float
from products.engineering_analytics.backend.logic.queries._workflow_filters import (
    date_to_filter_clause,
    run_started_floor_constant,
)

_HUMAN_MERGES = "NOT pr.is_bot AND NOT pr.is_draft"

# An outer join lands NULL or the epoch for a missed row depending on ``join_use_nulls``.
_EPOCH = "toDateTime(0)"


def _observed(expr: str) -> str:
    return f"nullIf(ifNull({expr}, {_EPOCH}), {_EPOCH})"


_PIPELINE_SELECT = f"""
    WITH
        gate_by_pr AS (
            SELECT pr_number, min(run_started_at) AS first_gate_at
            FROM __RUNS_SOURCE__ AS r
            WHERE r.is_merge_queue AND r.run_started_at >= {{gate_from}}
            GROUP BY pr_number
        ),
        merged AS (
            SELECT
                pr.created_at AS opened_at,
                pr.merged_at AS merged_at,
                {_observed("g.first_gate_at")} AS raw_gate_at
            FROM __PR_SOURCE__ AS pr
            LEFT JOIN gate_by_pr AS g ON g.pr_number = pr.number
            WHERE pr.merged_at IS NOT NULL AND pr.merged_at >= {{date_from}} AND {_HUMAN_MERGES}
                __DATE_TO_MERGED__
        )
    SELECT
        count() AS merged_prs,
        countIf(gate_at IS NOT NULL) AS gate_prs,
        quantileIf(0.5)(dateDiff('second', opened_at, gate_at), gate_at IS NOT NULL) AS open_to_gate_p50,
        quantileIf(0.9)(dateDiff('second', opened_at, gate_at), gate_at IS NOT NULL) AS open_to_gate_p90,
        quantileIf(0.5)(dateDiff('second', gate_at, merged_at), gate_at IS NOT NULL) AS gate_to_merge_p50,
        quantileIf(0.9)(dateDiff('second', gate_at, merged_at), gate_at IS NOT NULL) AS gate_to_merge_p90
    FROM (
        SELECT
            m.opened_at AS opened_at,
            m.merged_at AS merged_at,
            -- A gate run after the merge is the queue bisecting a later failure, not this PR landing.
            if(m.raw_gate_at <= m.merged_at, m.raw_gate_at, NULL) AS gate_at
        FROM merged AS m
    )
"""


@frozen
class _Timings:
    median: float | None
    p90: float | None
    pr_count: int


def _stage(stage: DeliveryStage, timings: _Timings) -> DeliveryStageTiming:
    return DeliveryStageTiming(
        stage=stage,
        median_seconds=timings.median,
        p90_seconds=timings.p90,
        pr_count=timings.pr_count,
    )


def _empty() -> DeliveryPipeline:
    return DeliveryPipeline(
        merged_pr_count=0,
        stages=[_stage(stage, _Timings(median=None, p90=None, pr_count=0)) for stage in DeliveryStage],
    )


def query_delivery_pipeline(
    *,
    curated: CuratedGitHubSource,
    date_from: datetime,
    date_to: datetime | None,
) -> DeliveryPipeline:
    """The open -> gate -> merge legs for [date_from, date_to], keyed on merge time."""
    # A first attempt older than the lookback truncates honestly: the first observed gate run
    # anchors both legs, the same rule as the merge-queue overview.
    gate_from = date_from - GATE_RUN_LOOKBACK
    placeholders: dict[str, ast.Expr] = {
        "date_from": ast.Constant(value=date_from),
        "gate_from": ast.Constant(value=gate_from),
        "run_started_floor": run_started_floor_constant(gate_from),
    }
    date_to_merged_clause = date_to_filter_clause(date_to, placeholders, column="pr.merged_at")
    sql = (
        _PIPELINE_SELECT.replace("__RUNS_SOURCE__", curated.run_source(started_floor=True))
        .replace("__PR_SOURCE__", curated.pr_source())
        .replace("__DATE_TO_MERGED__", date_to_merged_clause)
    )
    response = curated.run(sql, query_type="engineering_analytics.delivery_pipeline", placeholders=placeholders)
    if not response.results:
        return _empty()
    (
        merged_prs,
        gate_prs,
        open_to_gate_p50,
        open_to_gate_p90,
        gate_to_merge_p50,
        gate_to_merge_p90,
    ) = response.results[0]
    gate_count = int(gate_prs or 0)
    return DeliveryPipeline(
        merged_pr_count=int(merged_prs or 0),
        stages=[
            _stage(
                DeliveryStage.OPEN_TO_GATE,
                _Timings(median=opt_float(open_to_gate_p50), p90=opt_float(open_to_gate_p90), pr_count=gate_count),
            ),
            _stage(
                DeliveryStage.GATE_TO_MERGE,
                _Timings(median=opt_float(gate_to_merge_p50), p90=opt_float(gate_to_merge_p90), pr_count=gate_count),
            ),
        ],
    )
