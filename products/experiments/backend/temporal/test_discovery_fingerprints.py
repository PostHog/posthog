import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models import Organization, Team, User
from posthog.temporal.experiments.activities import (
    _calculate_experiment_saved_metric_sync,
    _get_experiment_regular_metrics_for_hour_sync,
    _get_experiment_saved_metrics_for_hour_sync,
)

from products.experiments.backend.metric_calculation.spec import plan_metric
from products.experiments.backend.metric_resolution import build_metric, find_metric_dict
from products.experiments.backend.models.experiment import Experiment, ExperimentSavedMetric, ExperimentToSavedMetric
from products.feature_flags.backend.models.feature_flag import FeatureFlag

METRIC_UUID = "metric-uuid-1"
METRIC = {"metric_type": "mean", "uuid": METRIC_UUID, "source": {"kind": "EventsNode", "event": "test"}}
SAVED_FUNNEL: dict[str, Any] = {
    "kind": "ExperimentMetric",
    "metric_type": "funnel",
    "uuid": "saved-funnel-uuid",
    "series": [{"kind": "EventsNode", "event": "signup"}, {"kind": "EventsNode", "event": "purchase"}],
    "breakdownAttributionType": "first_touch",
    "breakdownFilter": {"breakdown_limit": 5},
}

# Access the underlying sync functions, patching out close_old_connections which kills the test DB connection
_raw_regular_sync = _get_experiment_regular_metrics_for_hour_sync.func  # type: ignore[attr-defined]
_raw_saved_sync = _get_experiment_saved_metrics_for_hour_sync.func  # type: ignore[attr-defined]
_raw_saved_calc = _calculate_experiment_saved_metric_sync.func  # type: ignore[attr-defined]


@pytest.mark.django_db
class TestDiscoveryFingerprints:
    def _create_experiment(
        self, metrics: list[dict] | None = None, only_count_matured_users: bool = False
    ) -> tuple[Experiment, User]:
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
            only_count_matured_users=only_count_matured_users,
        )
        return experiment, user

    def _recalculation_key(self, experiment: Experiment, metric_uuid: str) -> str:
        spec = plan_metric(experiment, metric_uuid)
        assert spec is not None
        return spec.calculation_key()

    @parameterized.expand([("without_maturity", False), ("with_maturity", True)])
    def test_regular_metric_discovery_uses_the_recalculation_key(
        self, _name: str, only_count_matured_users: bool
    ) -> None:
        experiment, _ = self._create_experiment(only_count_matured_users=only_count_matured_users)

        with patch("posthog.temporal.experiments.activities.close_old_connections"):
            results = _raw_regular_sync(hour=2)

        fingerprints = [r.fingerprint for r in results if r.experiment_id == experiment.id]
        assert fingerprints == [self._recalculation_key(experiment, METRIC_UUID)]

    @parameterized.expand([("without_maturity", False), ("with_maturity", True)])
    def test_saved_metric_discovery_uses_the_recalculation_key(
        self, _name: str, only_count_matured_users: bool
    ) -> None:
        experiment, user = self._create_experiment(metrics=[], only_count_matured_users=only_count_matured_users)
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
        assert fingerprints == [self._recalculation_key(experiment, METRIC_UUID)]

    @parameterized.expand(
        [
            ("no_breakdowns", {}),
            ("with_breakdowns", {"type": "primary", "breakdowns": [{"type": "event", "property": "$os_name"}]}),
            (
                "with_attribution_and_limit_overrides",
                {
                    "type": "primary",
                    "breakdowns": [{"type": "event", "property": "$os_name"}],
                    "breakdownAttributionType": "step",
                    "breakdownAttributionValue": 0,
                    "breakdown_limit": 20,
                },
            ),
        ]
    )
    def test_saved_metric_calculation_uses_the_fingerprinted_definition(self, _name: str, metadata: dict) -> None:
        experiment, user = self._create_experiment(metrics=[])
        saved_metric = ExperimentSavedMetric.objects.create(
            team=experiment.team,
            name="Saved metric",
            query=SAVED_FUNNEL,
            created_by=user,
        )
        ExperimentToSavedMetric.objects.create(experiment=experiment, saved_metric=saved_metric, metadata=metadata)

        with (
            patch("posthog.temporal.experiments.activities.close_old_connections"),
            patch("posthog.temporal.experiments.activities.ExperimentQueryRunner") as mock_runner_class,
        ):
            mock_runner_class.return_value.run.return_value.model_dump.return_value = {"variant_results": []}
            results = _raw_saved_sync(hour=2)
            [discovered] = [r for r in results if r.experiment_id == experiment.id]
            outcome = _raw_saved_calc(experiment.id, discovered.metric_uuid, discovered.fingerprint)

        assert outcome.success, outcome.error_message
        effective = find_metric_dict(experiment, SAVED_FUNNEL["uuid"])
        assert effective is not None
        assert discovered.fingerprint == self._recalculation_key(experiment, SAVED_FUNNEL["uuid"])
        calculated_metric = mock_runner_class.call_args.kwargs["query"].metric
        assert calculated_metric == build_metric({**effective, "fingerprint": discovered.fingerprint})
        assert calculated_metric.breakdownFilter.breakdown_limit == metadata.get("breakdown_limit", 5)
