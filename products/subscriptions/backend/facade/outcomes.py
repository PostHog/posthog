"""One-shot, non-causal outcome readouts for adopted proactive artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from products.product_analytics.backend.facade.api import measure_saved_insight_trends
from products.subscriptions.backend.facade.measurements import FrozenMeasurement, parse_frozen_measurement
from products.subscriptions.backend.models import (
    ProactivePreparedArtifact,
    ProactiveRecommendation,
    ProactiveRecommendationOutcome,
)


@dataclass(frozen=True)
class ProvisionedOutcome:
    outcome_id: UUID
    status: str
    created: bool


@dataclass(frozen=True)
class OutcomeReadResult:
    outcome_id: UUID | None
    status: str
    persisted: bool


@dataclass(frozen=True)
class OutcomeVerdict:
    status: str
    failure_code: str | None
    delta: Decimal


def provision_outcome_for_adopted_artifact(*, team_id: int, artifact_id: UUID) -> ProvisionedOutcome | None:
    """Create the sole outcome row after adoption, preserving every replay unchanged."""
    with transaction.atomic():
        artifact = (
            ProactivePreparedArtifact.objects.for_team(team_id).select_for_update().filter(id=artifact_id).first()
        )
        if (
            artifact is None
            or artifact.status != ProactivePreparedArtifact.Status.ADOPTED
            or artifact.adopted_at is None
        ):
            return None
        recommendation = (
            ProactiveRecommendation.objects.for_team(team_id)
            .select_for_update()
            .filter(id=artifact.recommendation_id)
            .first()
        )
        if recommendation is None:
            return None
        defaults = _outcome_defaults(artifact=artifact, recommendation=recommendation)
        outcome, created = ProactiveRecommendationOutcome.objects.for_team(team_id).get_or_create(
            artifact=artifact,
            defaults={"team_id": team_id, **defaults},
        )
        return ProvisionedOutcome(outcome_id=outcome.id, status=outcome.status, created=created)


def read_outcome_once(*, team_id: int, outcome_id: UUID) -> OutcomeReadResult:
    """Read a due pending outcome once; duplicate workers may query, not overwrite."""
    outcome = (
        ProactiveRecommendationOutcome.objects.for_team(team_id)
        .select_related("artifact")
        .filter(id=outcome_id)
        .first()
    )
    if outcome is None:
        return OutcomeReadResult(outcome_id=None, status="missing", persisted=False)
    if outcome.status != ProactiveRecommendationOutcome.Status.PENDING:
        return OutcomeReadResult(outcome_id=outcome.id, status="terminal", persisted=False)
    if outcome.due_at is None or outcome.due_at > timezone.now():
        return OutcomeReadResult(outcome_id=outcome.id, status="not_due", persisted=False)

    measurement = parse_frozen_measurement(outcome.measurement_spec)
    if measurement is None or outcome.artifact.adopted_at is None:
        return _persist_terminal(
            team_id=team_id,
            outcome_id=outcome.id,
            status=ProactiveRecommendationOutcome.Status.UNAVAILABLE,
            failure_code=ProactiveRecommendationOutcome.FailureCode.BASELINE_UNAVAILABLE,
        )
    observed_from, observed_to = observed_window_for_baseline(
        adopted_at=outcome.artifact.adopted_at,
        baseline_from=measurement.baseline_from,
        baseline_to=measurement.baseline_to,
    )
    measurement_result = measure_saved_insight_trends(
        team_id=team_id,
        insight_id=measurement.saved_insight_id,
        short_id=measurement.saved_insight_short_id,
        last_modified_at=measurement.saved_insight_last_modified_at,
        frozen_query=measurement.frozen_query,
        date_from=observed_from,
        date_to=observed_to,
    )
    if measurement_result.status != "success" or measurement_result.value is None:
        return _persist_terminal(
            team_id=team_id,
            outcome_id=outcome.id,
            status=ProactiveRecommendationOutcome.Status.UNAVAILABLE,
            failure_code=_unavailable_failure_code(measurement_result.status),
            observed_from=observed_from,
            observed_to=observed_to,
        )
    if not _fits_decimal_field(measurement_result.value):
        return _persist_terminal(
            team_id=team_id,
            outcome_id=outcome.id,
            status=ProactiveRecommendationOutcome.Status.UNAVAILABLE,
            failure_code=ProactiveRecommendationOutcome.FailureCode.RESPONSE_UNSUPPORTED,
            observed_from=observed_from,
            observed_to=observed_to,
        )
    verdict = verdict_for_measurement(
        baseline=measurement.baseline_value,
        observed=measurement_result.value,
        direction=measurement.direction,
    )
    return _persist_terminal(
        team_id=team_id,
        outcome_id=outcome.id,
        status=verdict.status,
        failure_code=verdict.failure_code,
        observed_from=observed_from,
        observed_to=observed_to,
        observed_value=measurement_result.value,
        delta=verdict.delta,
    )


def observed_window_for_baseline(
    *, adopted_at: datetime, baseline_from: date, baseline_to: date
) -> tuple[datetime, datetime]:
    """Return an inclusive full-day window with the frozen calendar span."""
    days = (baseline_to - baseline_from).days + 1
    return adopted_at, adopted_at + timedelta(days=days) - timedelta(microseconds=1)


def verdict_for_measurement(*, baseline: Decimal, observed: Decimal, direction: str) -> OutcomeVerdict:
    delta = observed - baseline
    if baseline == 0:
        return OutcomeVerdict(
            status=ProactiveRecommendationOutcome.Status.INCONCLUSIVE,
            failure_code=ProactiveRecommendationOutcome.FailureCode.ZERO_BASELINE,
            delta=delta,
        )
    if delta == 0:
        return OutcomeVerdict(
            status=ProactiveRecommendationOutcome.Status.INCONCLUSIVE,
            failure_code=ProactiveRecommendationOutcome.FailureCode.FLAT_MOVEMENT,
            delta=delta,
        )
    improved = (direction == "increase" and delta > 0) or (direction == "decrease" and delta < 0)
    return OutcomeVerdict(
        status=ProactiveRecommendationOutcome.Status.IMPROVED
        if improved
        else ProactiveRecommendationOutcome.Status.REGRESSED,
        failure_code=None,
        delta=delta,
    )


def _outcome_defaults(
    *, artifact: ProactivePreparedArtifact, recommendation: ProactiveRecommendation
) -> dict[str, object]:
    measurement = parse_frozen_measurement(recommendation.recommendation.get("measurement"))
    if measurement is None or artifact.adopted_at is None:
        return {
            "status": ProactiveRecommendationOutcome.Status.UNAVAILABLE,
            "failure_code": ProactiveRecommendationOutcome.FailureCode.BASELINE_UNAVAILABLE,
        }
    return {
        "status": ProactiveRecommendationOutcome.Status.PENDING,
        "measurement_spec": _measurement_spec(measurement),
        "metric_name": measurement.metric_name,
        "expected_metric_movement": measurement.expected_metric_movement,
        "direction": measurement.direction,
        "baseline_value": measurement.baseline_value,
        "baseline_from": measurement.baseline_from,
        "baseline_to": measurement.baseline_to,
        "due_at": artifact.adopted_at + timedelta(days=7),
    }


def _measurement_spec(measurement: FrozenMeasurement) -> dict[str, object]:
    return {
        "saved_insight": {
            "id": measurement.saved_insight_id,
            "short_id": measurement.saved_insight_short_id,
            "last_modified_at": measurement.saved_insight_last_modified_at.isoformat(),
        },
        "query": measurement.frozen_query,
    }


def _persist_terminal(
    *,
    team_id: int,
    outcome_id: UUID,
    status: str,
    failure_code: str | None,
    observed_from: datetime | None = None,
    observed_to: datetime | None = None,
    observed_value: Decimal | None = None,
    delta: Decimal | None = None,
) -> OutcomeReadResult:
    with transaction.atomic():
        outcome = (
            ProactiveRecommendationOutcome.objects.for_team(team_id).select_for_update().filter(id=outcome_id).first()
        )
        if outcome is None:
            return OutcomeReadResult(outcome_id=None, status="missing", persisted=False)
        if outcome.status != ProactiveRecommendationOutcome.Status.PENDING:
            return OutcomeReadResult(outcome_id=outcome.id, status="terminal", persisted=False)
        outcome.status = status
        outcome.failure_code = failure_code
        outcome.observed_from = observed_from
        outcome.observed_to = observed_to
        outcome.observed_value = observed_value
        outcome.delta = delta
        outcome.save(
            update_fields=[
                "status",
                "failure_code",
                "observed_from",
                "observed_to",
                "observed_value",
                "delta",
                "updated_at",
            ]
        )
        return OutcomeReadResult(outcome_id=outcome.id, status=outcome.status, persisted=True)


def _unavailable_failure_code(status: str) -> str:
    known = {
        ProactiveRecommendationOutcome.FailureCode.INSIGHT_NOT_FOUND,
        ProactiveRecommendationOutcome.FailureCode.INSIGHT_AUTHORITY_CHANGED,
        ProactiveRecommendationOutcome.FailureCode.QUERY_ERROR,
        ProactiveRecommendationOutcome.FailureCode.RESPONSE_UNSUPPORTED,
    }
    return status if status in known else ProactiveRecommendationOutcome.FailureCode.RESPONSE_UNSUPPORTED


def _fits_decimal_field(value: Decimal) -> bool:
    return value.is_finite() and value.as_tuple().exponent >= -10 and value.adjusted() <= 19
