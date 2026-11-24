"""Evaluation of a team's recording rules, once a minute.

Each rule sends its PromQL expression to Snuffle as one instant query, at the current minute held back
to where the team's ingestion has reached, and writes the series it returns into the team's metrics as
gauge points of `metric_name` at that minute. A rule records the minute it wrote, so a retried or
overlapping run writes each minute at most once. A minute that no run reached is not filled in later:
PromQL's lookback bridges a short gap, as it does for a Prometheus rule that missed an evaluation.

This reads with the same partition checkpoint as metrics alerts, so a rule never records a window that
ingestion is still writing. Without the checkpoint nothing is recorded, because a recorded minute is final and
an alert can still correct a read later.
"""

import math
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any, Final

from django.conf import settings
from django.db.models import F, Min

import structlog

from posthog.models import Team
from posthog.permissions import posthog_feature_flag_enabled

from products.metrics.backend.alerts.freshness import IngestionReach, fetch_partition_checkpoint
from products.metrics.backend.facade.contracts import METRICS_RECORDING_RULES_FEATURE_FLAG, PromQLQueryError
from products.metrics.backend.models import MetricRecordingRule
from products.metrics.backend.promql import snuffle_payload
from products.metrics.backend.recording_rules.otlp import (
    IngestError,
    IngestUnconfirmed,
    RecordedSample,
    export_request,
    send,
)

logger = structlog.get_logger(__name__)

# Below the evaluation activity's timeout, so the run stops starting queries before it is cut off.
TEAM_QUERY_BUDGET_SECONDS: Final = 40
MAX_QUERY_SECONDS: Final = 10
MIN_QUERY_SECONDS: Final = 2
FRESHNESS_QUERY_SECONDS: Final = 5
# Every series becomes a stored series, so one high-cardinality expression is refused rather than
# multiplying the team's metrics.
MAX_SERIES: Final = 1000

_UNEXPECTED_ERROR: Final = "The rule failed unexpectedly. PostHog has been notified."


def teams_with_recording_rules() -> list[int]:
    """Projects with an enabled rule, the one whose rules waited longest first, so a run that is cut off
    starts with the projects it did not reach."""
    return list(
        MetricRecordingRule.objects.unscoped()
        .filter(enabled=True)
        .values("team_id")
        .annotate(oldest_attempt=Min("last_attempted_at"))
        .order_by(F("oldest_attempt").asc(nulls_first=True), "team_id")
        .values_list("team_id", flat=True)
    )


def evaluate_team_recording_rules(team_id: int, now: datetime) -> int:
    """Evaluates the team's enabled rules for the minute ingestion has reached. Returns how many rules wrote."""
    if not settings.METRICS_RECORDING_RULES_INGEST_URL:
        return 0
    # The rule that has waited longest goes first, so when the budget runs out the same rules do not lose
    # their turn every minute.
    rules = list(
        MetricRecordingRule.objects.filter(team_id=team_id, enabled=True).order_by(
            F("last_attempted_at").asc(nulls_first=True), "metric_name"
        )
    )
    if not rules:
        return 0
    team = Team.objects.filter(id=team_id).first()
    if team is None:
        return 0
    # The flag also gates the work, so turning it off stops the rules a project already has. A background run has
    # no user, so the flag has to target the project or its organization.
    if not posthog_feature_flag_enabled(
        METRICS_RECORDING_RULES_FEATURE_FLAG,
        f"metrics-recording-rules:{team.id}",
        organization_id=team.organization_id,
        team_id=team.id,
        only_evaluate_locally=True,
    ):
        return 0

    deadline = time.monotonic() + TEAM_QUERY_BUDGET_SECONDS
    checkpoint = _read_instant(fetch_partition_checkpoint, team)
    if checkpoint is None:
        logger.info("Recording rules are waiting for ingestion to report how far it has reached", team_id=team_id)
        MetricRecordingRule.objects.filter(team_id=team_id, enabled=True).update(
            last_error="Waiting for metrics ingestion to catch up."
        )
        return 0
    at = IngestionReach(checkpoint=checkpoint, newest_point=None).evaluation_time(now).replace(second=0, microsecond=0)

    written = 0
    for rule in rules:
        if rule.last_evaluated_at is not None and rule.last_evaluated_at >= at:
            continue
        remaining = deadline - time.monotonic()
        if remaining < MIN_QUERY_SECONDS:
            logger.info("Recording rules ran out of time", team_id=team_id, at=at.isoformat())
            break
        try:
            samples = _query(team, rule.query, at=at, timeout_seconds=min(MAX_QUERY_SECONDS, remaining))
            # A result with no number in it has nothing to write, and an empty request is not a valid export.
            if any(sample.value is not None for sample in samples):
                send(team.api_token, export_request(rule.metric_name, samples, at))
        except IngestUnconfirmed as error:
            # The write may have landed, so a retry could record the minute twice. Skip the minute instead.
            _record(rule, now, last_evaluated_at=at, last_series_count=len(samples), last_error=str(error))
            continue
        except (PromQLQueryError, IngestError) as error:
            _record(rule, now, last_error=str(error))
            continue
        except Exception:
            logger.exception("Failed to evaluate a recording rule", team_id=team_id, rule_id=str(rule.id))
            _record(rule, now, last_error=_UNEXPECTED_ERROR)
            continue
        _record(rule, now, last_evaluated_at=at, last_series_count=len(samples), last_error=None)
        written += 1
    return written


def _read_instant(fetch: Callable[..., datetime | None], team: Team) -> datetime | None:
    try:
        return fetch(team, max_execution_time=FRESHNESS_QUERY_SECONDS)
    except Exception:
        # Without the read the rules still run, at the current minute.
        logger.exception("Failed to fetch how far metrics ingestion has reached", team_id=team.id)
        return None


def _query(team: Team, expr: str, *, at: datetime, timeout_seconds: float) -> list[RecordedSample]:
    payload = snuffle_payload(
        team,
        "POST",
        "/api/v1/query",
        data={"query": expr, "time": str(at.timestamp()), "timeout": f"{int(timeout_seconds)}s"},
        timeout=timeout_seconds,
    )
    data = payload.get("data") or {}
    result_type = data.get("resultType")
    result: Any = data.get("result")
    if result_type == "scalar":
        return [RecordedSample(labels={}, value=_number(result[1]))] if result else []
    if result_type != "vector":
        raise PromQLQueryError(
            f"A recording rule query must return an instant vector or a scalar, not a {result_type}."
        )
    if len(result or []) > MAX_SERIES:
        raise PromQLQueryError(
            f"The query returned more than {MAX_SERIES} series. Aggregate it, for example with sum by (...)."
        )
    samples = [
        RecordedSample(
            labels={str(key): str(value) for key, value in (series.get("metric") or {}).items()},
            value=_number((series.get("value") or [None, None])[1]),
        )
        for series in result or []
    ]
    # The recorded series has no metric name of its own, so two series that differ only by it would share one.
    distinct = {tuple(sorted((k, v) for k, v in sample.labels.items() if k != "__name__")) for sample in samples}
    if len(distinct) < len(samples):
        raise PromQLQueryError(
            "The query returned series that differ only by metric name. Aggregate it, for example with sum by (...)."
        )
    return samples


def _number(raw: Any) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _record(rule: MetricRecordingRule, attempted_at: datetime, **fields: Any) -> None:
    # An update of only these fields, so an edit saved while the query ran is kept.
    MetricRecordingRule.objects.filter(team_id=rule.team_id, id=rule.id).update(
        last_attempted_at=attempted_at, **fields
    )
