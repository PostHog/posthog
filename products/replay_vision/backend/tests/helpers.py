from typing import Any

from django.utils import timezone

from posthog.models import Team, User
from posthog.models.utils import uuid7

from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_observation_usage import ReplayObservationUsage
from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.replay_vision.backend.temporal.activities.create_observation import _build_scanner_snapshot


def snapshot_for(scanner: ReplayScanner) -> dict[str, Any]:
    """Build the same `scanner_snapshot` payload that `create_observation_activity` would persist."""
    return _build_scanner_snapshot(scanner)


def seed_scanner_spend(scanner: ReplayScanner, credits: int, *, observations: int = 1) -> None:
    """Settle spend for a scanner: `observations` succeeded rows, each with a `credits` receipt.
    The budget reads the receipt ledger, so receipt-less observations count nothing."""
    if credits <= 0 or observations <= 0:
        return
    snapshot = snapshot_for(scanner)
    rows = ReplayObservation.objects.bulk_create(
        ReplayObservation(
            scanner=scanner,
            team=scanner.team,
            session_id=f"seed-spend-{uuid7()}",
            status=ObservationStatus.SUCCEEDED,
            completed_at=timezone.now(),
            scanner_snapshot=snapshot,
            triggered_by=ObservationTrigger.SCHEDULE,
        )
        for _ in range(observations)
    )
    ReplayObservationUsage.objects.bulk_create(
        ReplayObservationUsage(
            observation_id=row.id,
            organization_id=scanner.team.organization_id,
            team_id=scanner.team_id,
            scanner_id=scanner.id,
            observation_created_at=row.created_at,
            model=scanner.model,
            credits=credits,
        )
        for row in rows
    )


def create_experiment(team: Team, flag_key: str, created_by: User | None = None) -> Experiment:
    """A launched-enough experiment with a multivariate flag, for targeting tests."""
    flag = FeatureFlag.objects.create(
        team=team,
        key=flag_key,
        filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
    )
    return Experiment.objects.create(team=team, name=f"exp-{flag_key}", feature_flag=flag, created_by=created_by)
