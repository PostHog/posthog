from typing import Any

from django.utils import timezone

import numpy as np

from posthog.models import Team, User
from posthog.models.utils import uuid7

from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_observation_rank import ReplayObservationRank
from products.replay_vision.backend.models.replay_observation_usage import ReplayObservationUsage
from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.replay_vision.backend.observation_ranks import NewRank, record_ranks
from products.replay_vision.backend.temporal.activities.create_observation import _build_scanner_snapshot
from products.replay_vision.backend.watch_rank import ANCHOR_VERSION, ANCHORS, WatchCategory


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


def create_experiment(
    team: Team,
    flag_key: str,
    created_by: User | None = None,
    *,
    launched: bool = False,
    variants: list[str] | None = None,
) -> Experiment:
    """An experiment for targeting tests. `launched` plus `variants` makes it resolvable by
    `resolve_exposure_linkage`, which the experiment scanner type's write path requires."""
    filters: dict[str, Any] = {"groups": [{"properties": [], "rollout_percentage": 100}]}
    if variants:
        filters["multivariate"] = {
            "variants": [{"key": key, "rollout_percentage": 100 // len(variants)} for key in variants]
        }
    flag = FeatureFlag.objects.create(team=team, key=flag_key, filters=filters)
    return Experiment.objects.create(
        team=team,
        name=f"exp-{flag_key}",
        feature_flag=flag,
        created_by=created_by,
        start_date=timezone.now() if launched else None,
        exposure_criteria={},
    )


def axis_anchors() -> dict[WatchCategory, np.ndarray]:
    """Unit anchors in three dimensions: failure on x, struggle on y, revenue on -y, routine on z, one row per anchor
    sentence so similarities come out keyed like real ones."""
    axes = {
        "failure": [1.0, 0.0, 0.0],
        "struggle": [0.0, 1.0, 0.0],
        "revenue": [0.0, -1.0, 0.0],
        "routine": [0.0, 0.0, 1.0],
    }
    return {category: np.array([axes[category]] * len(ANCHORS[category])) for category in ANCHORS}


def set_rank(
    observation: ReplayObservation,
    *,
    category: str = "failure",
    contrast: float = 0.5,
    group: Any = None,
    theme: Any = None,
    anchor_version: int = ANCHOR_VERSION,
) -> None:
    """Give an observation the rank row the rank consumer would write, replacing any it has."""
    ranks = ReplayObservationRank.objects.for_team(observation.team_id)
    ranks.filter(observation_id=observation.id).delete()
    record_ranks(
        observation.team_id, anchor_version, {str(observation.id): NewRank(contrast=contrast, category=category)}
    )
    ranks.filter(observation_id=observation.id).update(feed_group_id=group, search_theme_id=theme)
