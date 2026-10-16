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

from products.experiments.backend.health.exposure_inputs import HealthExposureInputsStatus, load_exposure_inputs
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag

LAUNCHED_AT = datetime(2026, 10, 1, 12, tzinfo=UTC)
COMPUTED_AT = LAUNCHED_AT + timedelta(hours=30)


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
    @parameterized.expand(
        [
            ("fresh_answer", _cached_answer(recalculating=False), HealthExposureInputsStatus.READY, True),
            ("stale_answer", _cached_answer(recalculating=True), HealthExposureInputsStatus.STALE, True),
            ("no_answer", CacheMissResponse(cache_key="exposures"), HealthExposureInputsStatus.CALCULATING, False),
        ]
    )
    def test_reads_what_the_exposure_checks_read_from_the_cached_answer(
        self,
        _name: str,
        response: CachedExperimentExposureQueryResponse | CacheMissResponse,
        expected_status: HealthExposureInputsStatus,
        has_totals: bool,
    ) -> None:
        flag = FeatureFlag.objects.create(
            team=self.team,
            key=f"exposure-inputs-{_name}",
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
        experiment = Experiment.objects.create(
            team=self.team, name="exposure-inputs", feature_flag=flag, start_date=LAUNCHED_AT
        )

        with patch(
            "products.experiments.backend.health.exposure_inputs.ExperimentExposuresQueryRunner.run",
            return_value=response,
        ):
            inputs = load_exposure_inputs(experiment, user=self.user, can_query_events=True)

        self.assertEqual(inputs.status, expected_status)
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
