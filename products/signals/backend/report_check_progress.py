from __future__ import annotations

import ast
import time
from copy import deepcopy
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

from django.core.cache import cache
from django.db.models import TextChoices
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen
from posthog.utils import relative_date_parse

from products.signals.backend.report_checks import CheckComparison, MetricThresholdConfig, parse_check_config
from products.signals.backend.report_metric_refresh import (
    REPORT_METRIC_REFRESH_TIME_BUDGET_SECONDS,
    REPORT_METRIC_SNAPSHOT_FRESH_FOR,
    metric_series,
    whole_window_value,
)

if TYPE_CHECKING:
    from posthog.models import Team

    from products.signals.backend.models import SignalReport, SignalReportCheck
    from products.signals.backend.report_metric_access import ReportMetricAccessPolicy

logger = structlog.get_logger(__name__)
MAX_PROGRESS_CHECKS = 6
MAX_PROGRESS_SOURCE_RUNS = 40


class CheckProgressStatus(TextChoices):
    ON_TRACK = "on_track", "Looks on track"
    OFF_TRACK = "off_track", "Not looking good"
    INSUFFICIENT_DATA = "insufficient_data", "Not enough data"
    UNAVAILABLE = "unavailable", "Unavailable"
    ERROR = "error", "Couldn't measure"


class ProgressTargetType(TextChoices):
    PROPORTIONAL = "proportional", "Proportional"
    FIXED = "fixed", "Fixed"


@frozen
class ProgressPoint:
    at: datetime
    value: float
    target: float | None
    target_upper: float | None


@frozen
class CheckProgress:
    check_id: str
    status: CheckProgressStatus
    explanation: str
    started_at: datetime | None = None
    ended_at: datetime | None = None
    measured_at: datetime | None = None
    value: float | None = None
    target: float | None = None
    target_upper: float | None = None
    target_type: Literal["proportional", "fixed"] | None = None
    sample_size: float | None = None
    query: dict[str, Any] | None = None
    points: list[ProgressPoint] | None = None


def _aggregation_degree(series: dict[str, Any]) -> int | None:
    aggregation = series.get("math") or "total"
    if aggregation in ("total", "dau", "weekly_active", "monthly_active", "unique_session", "unique_group", "sum"):
        return 1
    if aggregation in ("avg", "median", "min", "max", "p90", "p95", "p99", "p75", "p50"):
        return 0
    if aggregation == "hogql":
        from posthog.hogql import ast as hogql_ast  # noqa: PLC0415 — keeps the query parser off startup
        from posthog.hogql.parser import parse_expr  # noqa: PLC0415 — keeps the query parser off startup

        expression = parse_expr(series.get("math_hogql") or "")
        if isinstance(expression, hogql_ast.Call):
            if expression.name.lower() in ("count", "countif", "sum", "sumif", "uniq", "uniqexact"):
                return 1
            if expression.name.lower() in ("avg", "avgif", "min", "max", "median"):
                return 0
    return None


def _formula_degree(node: ast.AST, degrees: list[int | None]) -> int | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
        return 0
    if isinstance(node, ast.Name) and len(node.id) == 1:
        index = ord(node.id.upper()) - ord("A")
        return degrees[index] if 0 <= index < len(degrees) else None
    if isinstance(node, ast.UnaryOp):
        return _formula_degree(node.operand, degrees)
    if isinstance(node, ast.BinOp):
        left = _formula_degree(node.left, degrees)
        right = _formula_degree(node.right, degrees)
        if left is None or right is None:
            return None
        if isinstance(node.op, ast.Add | ast.Sub):
            return left if left == right else None
        if isinstance(node.op, ast.Mult):
            return left + right
        if isinstance(node.op, ast.Div):
            return left - right
    return None


def progress_target_type(config: MetricThresholdConfig) -> Literal["proportional", "fixed"] | None:
    if config.progress_target_type is not None:
        return config.progress_target_type
    if config.value_format in ("percentage", "percentage_scaled"):
        return "fixed"
    if config.query is None:
        return None
    source = config.query["source"]
    trends_filter = source.get("trendsFilter") or {}
    series = source["series"]
    degrees = [_aggregation_degree(item) for item in series]
    formula = trends_filter.get("formula")
    if trends_filter.get("formulaNodes"):
        formula = trends_filter["formulaNodes"][0].get("formula")
    elif trends_filter.get("formulas"):
        formula = trends_filter["formulas"][0]
    degree = _formula_degree(ast.parse(formula.strip(), mode="eval").body, degrees) if formula else degrees[0]
    return "proportional" if degree == 1 else "fixed" if degree == 0 else None


def bounded_progress_query(query: dict[str, Any], *, start: datetime, end: datetime) -> dict[str, Any]:
    bounded = deepcopy(query)
    source = bounded["source"]
    source["dateRange"] = {"date_from": start.isoformat(), "date_to": end.isoformat(), "explicitDate": True}
    source["interval"] = "hour" if end - start <= timedelta(days=2) else "day"
    # Display modifiers must not turn an interim rate into a sum of bucket rates.
    trends_filter = source.get("trendsFilter") or {}
    source["trendsFilter"] = {
        key: value for key, value in trends_filter.items() if key not in ("cumulative", "aggregationAxisFormat")
    }
    return bounded


def observation_count_query(query: dict[str, Any]) -> dict[str, Any]:
    counted = deepcopy(query)
    source = counted["source"]
    series = source["series"]
    trends_filter = source.get("trendsFilter") or {}
    formula = trends_filter.get("formula")
    if trends_filter.get("formulaNodes"):
        formula = trends_filter["formulaNodes"][0].get("formula")
    elif trends_filter.get("formulas"):
        formula = trends_filter["formulas"][0]
    if formula:
        denominator_names = {
            name.id.upper()
            for node in ast.walk(ast.parse(formula.strip(), mode="eval"))
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)
            for name in ast.walk(node.right)
            if isinstance(name, ast.Name)
        }
        if denominator_names:
            series = [item for index, item in enumerate(series) if chr(ord("A") + index) in denominator_names]
            source["series"] = series
    for item in series:
        for key in list(item):
            if key.startswith("math"):
                del item[key]
        item["math"] = "total"
    source["trendsFilter"] = {"formula": "+".join(chr(ord("A") + index) for index in range(len(series)))}
    return counted


def interim_comparison(
    comparison: CheckComparison, *, target_type: Literal["proportional", "fixed"], fraction: float
) -> CheckComparison:
    multiplier = fraction if target_type == "proportional" else 1.0
    copied = comparison.model_dump()
    if comparison.operator == "between":
        assert comparison.bounds is not None
        copied["bounds"] = {
            "lower": comparison.bounds.lower * multiplier,
            "upper": comparison.bounds.upper * multiplier,
        }
    else:
        assert comparison.value is not None
        copied["value"] = comparison.value * multiplier
    return CheckComparison.model_validate(copied)


def evaluate_progress(
    *, value: float, comparison: CheckComparison, sample_size: float, minimum: int
) -> CheckProgressStatus:
    if sample_size < minimum:
        return CheckProgressStatus.INSUFFICIENT_DATA
    if comparison.operator == "between":
        assert comparison.bounds is not None
        matches = comparison.bounds.lower <= value <= comparison.bounds.upper
    else:
        assert comparison.value is not None
        matches = value <= comparison.value if comparison.operator == "lte" else value >= comparison.value
    return CheckProgressStatus.ON_TRACK if matches else CheckProgressStatus.OFF_TRACK


def measure_progress(
    *, check: SignalReportCheck, report: SignalReport, team: Team, policy: ReportMetricAccessPolicy, deadline: float
) -> CheckProgress:
    check_id = str(check.id)
    config = parse_check_config(check.kind, check.config)
    assert isinstance(config, MetricThresholdConfig)
    if config.query is None or not policy.may_read_snapshot({"query": config.query}):
        return CheckProgress(
            check_id=check_id,
            status=CheckProgressStatus.UNAVAILABLE,
            explanation="The measurement query is not available to you.",
        )
    if config.eligibility_query is not None and not policy.may_read_snapshot({"query": config.eligibility_query}):
        return CheckProgress(
            check_id=check_id,
            status=CheckProgressStatus.UNAVAILABLE,
            explanation="The activity query is not available to you.",
        )
    start = report.monitoring_started_at
    end = report.monitoring_ended_at if report.status == "resolved" else timezone.now()
    if start is not None and report.status == "resolved" and end is None:
        return CheckProgress(
            check_id=check_id,
            status=CheckProgressStatus.UNAVAILABLE,
            explanation="The resolution time wasn't recorded for this monitoring period.",
        )
    if start is None or end is None or end <= start:
        return CheckProgress(
            check_id=check_id,
            status=CheckProgressStatus.INSUFFICIENT_DATA,
            explanation="No monitoring period is available yet.",
        )
    end_key = report.monitoring_ended_at.isoformat() if report.monitoring_ended_at else "ongoing"
    cache_key = f"report-check-progress:{team.id}:{check_id}:{check.updated_at.isoformat()}:{start.isoformat()}:{end_key}:{report.status}"
    cached = cache.get(cache_key)
    if isinstance(cached, CheckProgress):
        return cached
    target_type = progress_target_type(config)
    if target_type is None:
        return CheckProgress(
            check_id=check_id,
            status=CheckProgressStatus.UNAVAILABLE,
            explanation="Choose a proportional or fixed interim target for this custom measurement.",
        )
    full_end = relative_date_parse(
        config.query["source"]["dateRange"]["date_from"], team.timezone_info, now=start, increase=True
    )
    window_seconds = (full_end - start).total_seconds()
    if window_seconds <= 0:
        raise ValueError("invalid measurement window")
    query = bounded_progress_query(config.query, start=start, end=end)
    evidence = (
        bounded_progress_query(config.eligibility_query, start=start, end=end)
        if config.eligibility_query
        else observation_count_query(query)
    )
    sample_size, measured_at = whole_window_value(evidence, team, deadline=deadline)
    value: float | None = None
    if sample_size > 0 or target_type == "proportional":
        value, measured_at = whole_window_value(query, team, deadline=deadline)
    comparison = interim_comparison(
        config.comparison, target_type=target_type, fraction=(end - start).total_seconds() / window_seconds
    )
    verdict = (
        evaluate_progress(
            value=value, comparison=comparison, sample_size=sample_size, minimum=config.minimum_data_points
        )
        if value is not None
        else CheckProgressStatus.INSUFFICIENT_DATA
    )
    explanation = (
        "No relevant activity was observed. Zero events alone cannot show whether the fix is working."
        if sample_size == 0
        else f"Only {sample_size:g} qualifying observations; this measurement needs {config.minimum_data_points}."
        if verdict == CheckProgressStatus.INSUFFICIENT_DATA
        else "Compared with the target for the time elapsed. This is a provisional pace estimate."
        if target_type == "proportional"
        else "Compared with the original rate or average target. This is a provisional assessment."
    )
    points: list[ProgressPoint] | None = None
    try:
        series = metric_series(query, team, deadline=deadline)
        points = []
        for index, at in enumerate(series.dates):
            bucket_end = series.dates[index + 1] if index + 1 < len(series.dates) else end
            fraction = max(0, (min(bucket_end, end) - max(at, start)).total_seconds()) / window_seconds
            bucket_comparison = interim_comparison(config.comparison, target_type=target_type, fraction=fraction)
            points.append(
                ProgressPoint(
                    at=at,
                    value=series.values[index],
                    target=bucket_comparison.bounds.lower if bucket_comparison.bounds else bucket_comparison.value,
                    target_upper=bucket_comparison.bounds.upper if bucket_comparison.bounds else None,
                )
            )
    except Exception:
        logger.exception("signals.check_progress.series_failed", team_id=team.id, check_id=check_id)
    progress = CheckProgress(
        check_id=check_id,
        status=verdict,
        explanation=explanation,
        started_at=start,
        ended_at=end,
        measured_at=measured_at,
        value=value,
        target=comparison.bounds.lower if comparison.bounds else comparison.value,
        target_upper=comparison.bounds.upper if comparison.bounds else None,
        target_type=target_type,
        sample_size=sample_size,
        query=query,
        points=points,
    )
    cache.set(cache_key, progress, timeout=int(REPORT_METRIC_SNAPSHOT_FRESH_FOR.total_seconds()))
    return progress


def report_check_progress(
    *, checks: list[SignalReportCheck], report: SignalReport, team: Team, policy: ReportMetricAccessPolicy
) -> list[CheckProgress]:
    deadline = time.monotonic() + REPORT_METRIC_REFRESH_TIME_BUDGET_SECONDS
    results: list[CheckProgress] = []
    source_runs = 0
    for check in checks[:MAX_PROGRESS_CHECKS]:
        main_query = check.config.get("query") or {}
        eligibility = check.config.get("eligibility_query") or main_query
        cost = 2 * len(main_query.get("source", {}).get("series", [])) + len(
            eligibility.get("source", {}).get("series", [])
        )
        if source_runs + cost > MAX_PROGRESS_SOURCE_RUNS or time.monotonic() >= deadline:
            results.append(
                CheckProgress(
                    check_id=str(check.id),
                    status=CheckProgressStatus.ERROR,
                    explanation="The refresh limit was reached. Reopen the report to try again.",
                )
            )
            continue
        source_runs += cost
        try:
            results.append(measure_progress(check=check, report=report, team=team, policy=policy, deadline=deadline))
        except Exception:
            logger.exception("signals.check_progress.failed", team_id=team.id, check_id=str(check.id))
            results.append(
                CheckProgress(
                    check_id=str(check.id),
                    status=CheckProgressStatus.ERROR,
                    explanation="Couldn't measure progress. Refresh the report to try again.",
                )
            )
    return results
