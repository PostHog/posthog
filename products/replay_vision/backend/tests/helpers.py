from typing import Any

from posthog.models import Team

from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.replay_vision.backend.temporal.activities.create_observation import _build_scanner_snapshot


def snapshot_for(scanner: ReplayScanner) -> dict[str, Any]:
    """Build the same `scanner_snapshot` payload that `create_observation_activity` would persist."""
    return _build_scanner_snapshot(scanner)


def create_experiment(team: Team, flag_key: str) -> Experiment:
    """A launched-enough experiment with a multivariate flag, for targeting tests."""
    flag = FeatureFlag.objects.create(
        team=team,
        key=flag_key,
        filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
    )
    return Experiment.objects.create(team=team, name=f"exp-{flag_key}", feature_flag=flag)
