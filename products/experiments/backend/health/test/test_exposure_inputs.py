from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import (
    CachedExperimentExposureQueryResponse,
    CacheMissResponse,
    DateRange,
    QueryStatus,
    SampleRatioMismatch,
)

from posthog.clickhouse.client.execute_async import QueryStatusManager, get_query_status

from products.experiments.backend.facade.contracts import HealthExposureInputsStatus
from products.experiments.backend.health.exposure_inputs import load_exposure_inputs
from products.experiments.backend.hogql_queries.experiment_exposures_query_runner import (
    ExperimentExposuresQueryRunner,
    build_experiment_exposure_query,
)
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag

LAUNCHED_AT = datetime(2026, 10, 1, 12, tzinfo=UTC)
COMPUTED_AT = LAUNCHED_AT + timedelta(hours=30)
CALCULATION_ERROR = "The exposure criteria name an event property that does not exist."


def _cached_answer(*, recalculating: bool) -> CachedExperimentExposureQueryResponse:
    return CachedExperimentExposureQueryResponse(
        cache_key="exposures",
        date_range=DateRange(date_from=LAUNCHED_AT.isoformat()),
        is_cached=True,
        last_refresh=COMPUTED_AT,
        next_allowed_client_refresh=COMPUTED_AT,
        timeseries=[],
        timezone="UTC",
        total_exposures={"control": 480, "test": 520},
        sample_ratio_mismatch=SampleRatioMismatch(expected={"control": 500, "test": 500}, p_value=0.2),
        query_status=QueryStatus(id="q", team_id=1, complete=False) if recalculating else None,
    )


class TestLoadExposureInputs(BaseTest):
    def _create_experiment(self, key: str) -> Experiment:
        flag = FeatureFlag.objects.create(
            team=self.team,
            key=key,
            created_by=self.user,
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "rollout_percentage": 50},
                        {"key": "test", "rollout_percentage": 50},
                    ]
                },
            },
        )
        return Experiment.objects.create(team=self.team, name=key, feature_flag=flag, start_date=LAUNCHED_AT)

    def _store_failed_calculation(self, experiment: Experiment) -> str:
        runner = ExperimentExposuresQueryRunner(
            query=build_experiment_exposure_query(experiment), team=self.team, user=self.user, error_event_context=None
        )
        cache_key = runner.get_cache_key()
        QueryStatusManager(cache_key, self.team.pk).store_query_status(
            QueryStatus(id=cache_key, team_id=self.team.pk, complete=True, error=True, error_message=CALCULATION_ERROR)
        )
        return cache_key

    @parameterized.expand(
        [
            ("fresh_answer", _cached_answer(recalculating=False), False, HealthExposureInputsStatus.READY, True),
            ("stale_answer", _cached_answer(recalculating=True), False, HealthExposureInputsStatus.STALE, True),
            (
                "answer_after_a_failed_refresh",
                _cached_answer(recalculating=False),
                True,
                HealthExposureInputsStatus.STALE,
                True,
            ),
            (
                "no_answer",
                CacheMissResponse(cache_key="exposures"),
                False,
                HealthExposureInputsStatus.CALCULATING,
                False,
            ),
        ]
    )
    def test_reads_what_the_exposure_checks_read_from_the_cached_answer(
        self,
        _name: str,
        response: CachedExperimentExposureQueryResponse | CacheMissResponse,
        refresh_failed: bool,
        expected_status: HealthExposureInputsStatus,
        has_totals: bool,
    ) -> None:
        experiment = self._create_experiment(f"exposure-inputs-{_name}")
        if refresh_failed:
            self._store_failed_calculation(experiment)

        with patch(
            "products.experiments.backend.health.exposure_inputs.ExperimentExposuresQueryRunner.run",
            return_value=response,
        ):
            inputs = load_exposure_inputs(experiment, user=self.user, can_query_events=True)

        self.assertEqual(
            (inputs.status, inputs.error), (expected_status, CALCULATION_ERROR if refresh_failed else None)
        )
        if not has_totals:
            self.assertIsNone(inputs.totals)
            return
        assert inputs.totals is not None
        self.assertEqual(
            (
                dict(inputs.totals.total_exposures),
                inputs.totals.sample_ratio_mismatch_p_value,
                inputs.totals.hours_since_launch,
            ),
            ({"control": 480, "test": 520}, 0.2, 30.0),
        )

    def test_reports_failed_for_malformed_exposure_criteria(self) -> None:
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="exposure-inputs-malformed",
            created_by=self.user,
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {"variants": [{"key": "control", "rollout_percentage": 100}]},
            },
        )
        experiment = Experiment.objects.create(
            team=self.team,
            name="exposure-inputs-malformed",
            feature_flag=flag,
            start_date=LAUNCHED_AT,
            exposure_criteria={"multiple_variant_handling": "not_a_handling"},
        )

        inputs = load_exposure_inputs(experiment, user=self.user, can_query_events=True)

        self.assertEqual(inputs.status, HealthExposureInputsStatus.FAILED)

    def test_reports_a_failed_calculation_and_does_not_start_another(self) -> None:
        experiment = self._create_experiment("exposure-inputs-failed-calculation")
        cache_key = self._store_failed_calculation(experiment)

        inputs = load_exposure_inputs(experiment, user=self.user, can_query_events=True)

        self.assertEqual((inputs.status, inputs.error), (HealthExposureInputsStatus.FAILED, CALCULATION_ERROR))
        self.assertEqual(get_query_status(team_id=self.team.pk, query_id=cache_key).error_message, CALCULATION_ERROR)
