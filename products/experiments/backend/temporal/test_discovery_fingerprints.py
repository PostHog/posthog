import datetime
from zoneinfo import ZoneInfo

import pytest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models import Organization, Team, User
from posthog.temporal.experiments.activities import (
    _get_experiment_regular_metrics_for_hour_sync,
    _get_experiment_saved_metrics_for_hour_sync,
)

from products.experiments.backend.hogql_queries.experiment_metric_fingerprint import compute_metric_fingerprint
from products.experiments.backend.hogql_queries.utils import get_experiment_stats_method
from products.experiments.backend.models.experiment import Experiment, ExperimentSavedMetric, ExperimentToSavedMetric
from products.experiments.backend.temporal.metric_resolution import find_metric_dict
from products.feature_flags.backend.models.feature_flag import FeatureFlag

METRIC_UUID = "metric-uuid-1"
METRIC = {"metric_type": "mean", "uuid": METRIC_UUID, "source": {"kind": "EventsNode", "event": "test"}}

# Access the underlying sync functions, patching out close_old_connections which kills the test DB connection
_raw_regular_sync = _get_experiment_regular_metrics_for_hour_sync.func  # type: ignore[attr-defined]
_raw_saved_sync = _get_experiment_saved_metrics_for_hour_sync.func  # type: ignore[attr-defined]


@pytest.mark.django_db
class TestDiscoveryFingerprints:
    def _create_experiment(self, metrics: list[dict] | None = None) -> tuple[Experiment, User]:
        org = Organization.objects.create(name="Test Org")
        team = Team.objects.create(organization=org, name="Test Team")
        user = User.objects.create(email="fingerprint@test.com")
        flag = FeatureFlag.objects.create(team=team, key="fingerprint-test", created_by=user)
        experiment = Experiment.objects.create(
            name="Fingerprint test",
            team=team,
            feature_flag=flag,
            start_date=datetime.datetime.now(ZoneInfo("UTC")) - datetime.timedelta(days=1),
            status=Experiment.Status.RUNNING,
            metrics=metrics if metrics is not None else [METRIC],
            excluded_variants=["enterprise_holdout"],
        )
        return experiment, user

    def _expected_fingerprint(self, experiment: Experiment, metric: dict) -> str:
        return compute_metric_fingerprint(
            metric,
            experiment.start_date,
            get_experiment_stats_method(experiment),
            experiment.exposure_criteria,
            only_count_matured_users=experiment.only_count_matured_users,
            excluded_variants=experiment.excluded_variants,
        )

    def test_regular_metric_fingerprint_includes_excluded_variants(self) -> None:
        experiment, _ = self._create_experiment()

        with patch("posthog.temporal.experiments.activities.close_old_connections"):
            results = _raw_regular_sync(hour=2)

        fingerprints = [r.fingerprint for r in results if r.experiment_id == experiment.id]
        assert fingerprints == [self._expected_fingerprint(experiment, METRIC)]

    def test_saved_metric_fingerprint_includes_excluded_variants(self) -> None:
        experiment, user = self._create_experiment(metrics=[])
        saved_metric = ExperimentSavedMetric.objects.create(
            team=experiment.team,
            name="Saved metric",
            query=METRIC,
            created_by=user,
        )
        ExperimentToSavedMetric.objects.create(experiment=experiment, saved_metric=saved_metric)

        with patch("posthog.temporal.experiments.activities.close_old_connections"):
            results = _raw_saved_sync(hour=2)

        fingerprints = [r.fingerprint for r in results if r.experiment_id == experiment.id]
        assert fingerprints == [self._expected_fingerprint(experiment, saved_metric.query)]

    @parameterized.expand(
        [
            ("no_breakdowns", {}),
            ("with_breakdowns", {"type": "primary", "breakdowns": [{"type": "event", "property": "$os_name"}]}),
        ]
    )
    def test_saved_metric_discovery_fingerprint_matches_recalculation_resolution(
        self, _name: str, metadata: dict
    ) -> None:
        """The readers (timeseries sync, cold-start fallback, chart read) resolve a saved metric through
        find_metric_dict, which merges the link-metadata breakdowns. Discovery must fingerprint the same
        merged dict, or the daily points are filed under a hash no reader looks up and daily results are
        never published for that metric."""
        experiment, user = self._create_experiment(metrics=[])
        saved_metric = ExperimentSavedMetric.objects.create(
            team=experiment.team,
            name="Saved metric",
            query=METRIC,
            created_by=user,
        )
        ExperimentToSavedMetric.objects.create(experiment=experiment, saved_metric=saved_metric, metadata=metadata)

        with patch("posthog.temporal.experiments.activities.close_old_connections"):
            results = _raw_saved_sync(hour=2)

        discovery_fingerprints = [r.fingerprint for r in results if r.experiment_id == experiment.id]
        merged_dict = find_metric_dict(experiment, METRIC_UUID)
        assert merged_dict is not None
        assert discovery_fingerprints == [self._expected_fingerprint(experiment, merged_dict)]


@pytest.mark.parametrize(
    "variant,expected_equal",
    [
        ({**METRIC, "breakdownFilter": {"breakdowns": []}}, True),
        ({**METRIC, "breakdownFilter": {"breakdowns": None}}, True),
        ({**METRIC, "breakdownFilter": None}, True),
        ({**METRIC, "breakdownFilter": {"breakdowns": [{"type": "event", "property": "$os_name"}]}}, False),
    ],
)
def test_only_real_breakdowns_change_the_fingerprint(variant: dict, expected_equal: bool) -> None:
    """Empty breakdown shapes are the same config as no breakdowns and must hash identically, while an
    actual breakdown is a config change that must invalidate cached results."""
    start = datetime.datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC"))
    base_fp = compute_metric_fingerprint(METRIC, start, "bayesian", None)
    variant_fp = compute_metric_fingerprint(variant, start, "bayesian", None)
    assert (variant_fp == base_fp) is expected_equal
