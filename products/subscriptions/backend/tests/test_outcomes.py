from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from django.db import transaction
from django.utils import timezone as django_timezone

from products.product_analytics.backend.facade.contracts import SavedInsightMeasurement
from products.subscriptions.backend.facade import outcomes
from products.subscriptions.backend.facade.outcomes import (
    observed_window_for_baseline,
    parse_provisioned_measurement,
    provision_outcome_for_adopted_artifact,
    read_outcome_once,
    verdict_for_measurement,
)
from products.subscriptions.backend.models import (
    ProactivePreparedArtifact,
    ProactiveRecommendation,
    ProactiveRecommendationOutcome,
    ProactiveRecommendationRun,
)


@pytest.mark.parametrize(
    ("baseline_from", "baseline_to", "expected_end"),
    [
        (date(2026, 9, 1), date(2026, 9, 1), datetime(2026, 9, 9, 11, 29, 59, 999999)),
        (date(2026, 9, 1), date(2026, 9, 7), datetime(2026, 9, 15, 11, 29, 59, 999999)),
    ],
)
def test_observed_window_keeps_the_frozen_inclusive_calendar_span(
    baseline_from: date, baseline_to: date, expected_end: datetime
) -> None:
    observed_from = datetime(2026, 9, 8, 11, 30)

    assert observed_window_for_baseline(
        adopted_at=observed_from,
        baseline_from=baseline_from,
        baseline_to=baseline_to,
    ) == (observed_from, expected_end)


@pytest.mark.parametrize(
    ("baseline", "observed", "direction", "status", "failure_code"),
    [
        (Decimal("10"), Decimal("12"), "increase", "improved", None),
        (Decimal("10"), Decimal("8"), "increase", "regressed", None),
        (Decimal("10"), Decimal("8"), "decrease", "improved", None),
        (Decimal("10"), Decimal("12"), "decrease", "regressed", None),
        (Decimal("10"), Decimal("10"), "increase", "inconclusive", "flat_movement"),
        (Decimal("0"), Decimal("1"), "increase", "inconclusive", "zero_baseline"),
    ],
)
def test_verdict_uses_absolute_movement_without_a_threshold(
    baseline: Decimal, observed: Decimal, direction: str, status: str, failure_code: str | None
) -> None:
    decision = verdict_for_measurement(baseline=baseline, observed=observed, direction=direction)

    assert decision.status == status
    assert decision.failure_code == failure_code
    assert decision.delta == observed - baseline


def test_reader_reconstructs_the_compact_persisted_outcome_measurement() -> None:
    measurement = _measurement()
    parsed = parse_provisioned_measurement(
        measurement_spec={
            "saved_insight": measurement["saved_insight"],
            "query": {key: value for key, value in measurement["query"].items() if key != "dateRange"},
        },
        baseline_value=Decimal("10"),
        baseline_from=date(2026, 9, 1),
        baseline_to=date(2026, 9, 7),
        metric_name="Signups",
        expected_metric_movement="More signups",
        direction="increase",
    )

    assert parsed is not None
    assert parsed.frozen_query == {
        "kind": "TrendsQuery",
        "series": [{"kind": "EventsNode", "event": "signed_up", "math": "total"}],
        "interval": "day",
    }
    assert parsed.baseline_value == Decimal("10")


def _measurement(*, value: int = 10) -> dict[str, object]:
    return {
        "version": 1,
        "saved_insight": {
            "id": 42,
            "short_id": "signup-rate",
            "last_modified_at": "2026-09-08T10:30:00+00:00",
        },
        "query": {
            "kind": "TrendsQuery",
            "series": [{"kind": "EventsNode", "event": "signed_up", "math": "total"}],
            "interval": "day",
            "dateRange": {"date_from": "2026-09-01", "date_to": "2026-09-07"},
        },
        "baseline": {"value": value, "date_from": "2026-09-01", "date_to": "2026-09-07"},
        "metric": {"name": "Signups", "expected_movement": "More signups", "direction": "increase"},
    }


def _adopted_artifact(team, *, measurement: object = _measurement(), adopted_at: datetime | None = None):
    run = ProactiveRecommendationRun.objects.for_team(team.id).create(
        team_id=team.id,
        subscription_id=123,
        delivery_id=uuid4(),
        actor_id=456,
        snapshot_hash="a" * 64,
        status=ProactiveRecommendationRun.Status.COMPLETED,
    )
    recommendation = ProactiveRecommendation.objects.for_team(team.id).create(
        team_id=team.id,
        run=run,
        semantic_key=str(uuid4()),
        recommendation={"measurement": measurement} if measurement is not None else {},
        citations=[],
    )
    return ProactivePreparedArtifact.objects.for_team(team.id).create(
        team_id=team.id,
        run=run,
        recommendation=recommendation,
        kind=ProactivePreparedArtifact.Kind.EXPERIMENT_DRAFT,
        status=ProactivePreparedArtifact.Status.ADOPTED,
        artifact_config_hash="b" * 64,
        input_hash="c" * 64,
        adopted_at=adopted_at or django_timezone.now(),
    )


@pytest.mark.django_db
def test_provisioned_outcome_is_one_team_scoped_row_with_a_frozen_seven_day_due_date(team) -> None:
    adopted_at = datetime(2026, 9, 8, 11, 30, tzinfo=UTC)
    artifact = _adopted_artifact(team, adopted_at=adopted_at)

    first = provision_outcome_for_adopted_artifact(team_id=team.id, artifact_id=artifact.id)
    replay = provision_outcome_for_adopted_artifact(team_id=team.id, artifact_id=artifact.id)

    assert first is not None
    assert first.created is True
    assert first.status == ProactiveRecommendationOutcome.Status.PENDING
    assert replay is not None
    assert replay.outcome_id == first.outcome_id
    assert replay.created is False
    outcome = ProactiveRecommendationOutcome.objects.for_team(team.id).get(id=first.outcome_id)
    assert outcome.artifact_id == artifact.id
    assert outcome.team_id == team.id
    assert outcome.due_at == adopted_at + timedelta(days=7)
    assert outcome.measurement_spec == {
        "saved_insight": _measurement()["saved_insight"],
        "query": {key: value for key, value in _measurement()["query"].items() if key != "dateRange"},
    }


@pytest.mark.django_db
@pytest.mark.parametrize(
    "measurement", [None, {"baseline": {"value": 1}}, _measurement(value=10_000_000_000_000_000_000_000)]
)
def test_missing_or_malformed_measurement_is_terminal_unavailable(team, measurement: object) -> None:
    artifact = _adopted_artifact(team, measurement=measurement)

    provisioned = provision_outcome_for_adopted_artifact(team_id=team.id, artifact_id=artifact.id)

    assert provisioned is not None
    outcome = ProactiveRecommendationOutcome.objects.for_team(team.id).get(id=provisioned.outcome_id)
    assert outcome.status == ProactiveRecommendationOutcome.Status.UNAVAILABLE
    assert outcome.failure_code == ProactiveRecommendationOutcome.FailureCode.BASELINE_UNAVAILABLE
    assert outcome.due_at is None
    assert outcome.measurement_spec is None


@pytest.mark.django_db(transaction=True)
def test_due_read_queries_outside_the_terminal_write_lock(team, monkeypatch) -> None:
    artifact = _adopted_artifact(team, adopted_at=django_timezone.now() - timedelta(days=7))
    provisioned = provision_outcome_for_adopted_artifact(team_id=team.id, artifact_id=artifact.id)
    assert provisioned is not None

    def measure(**_kwargs: object) -> SavedInsightMeasurement:
        assert not transaction.get_connection().in_atomic_block
        return SavedInsightMeasurement(status="success", value=Decimal("12"))

    monkeypatch.setattr(outcomes, "measure_saved_insight_trends", measure)
    result = read_outcome_once(team_id=team.id, outcome_id=provisioned.outcome_id)

    assert result.persisted is True
    outcome = ProactiveRecommendationOutcome.objects.for_team(team.id).get(id=provisioned.outcome_id)
    assert outcome.status == ProactiveRecommendationOutcome.Status.IMPROVED
    assert outcome.observed_to is not None
    assert outcome.observed_to - outcome.observed_from == timedelta(days=7) - timedelta(microseconds=1)


@pytest.mark.django_db
def test_terminal_missing_and_not_due_reads_are_noops(team) -> None:
    artifact = _adopted_artifact(team)
    provisioned = provision_outcome_for_adopted_artifact(team_id=team.id, artifact_id=artifact.id)
    assert provisioned is not None

    assert read_outcome_once(team_id=team.id, outcome_id=uuid4()).status == "missing"
    assert read_outcome_once(team_id=team.id, outcome_id=provisioned.outcome_id).status == "not_due"
    ProactiveRecommendationOutcome.objects.for_team(team.id).filter(id=provisioned.outcome_id).update(
        status=ProactiveRecommendationOutcome.Status.UNAVAILABLE
    )
    assert read_outcome_once(team_id=team.id, outcome_id=provisioned.outcome_id).status == "terminal"
