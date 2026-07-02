from datetime import timedelta

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events

from django.utils import timezone

from products.experiments.backend.experiment_service import ExperimentService
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag


# ClickHouse-backed correctness proof for the bounded exposed-set scan (`_fetch_exposed_person_uuids`),
# the one freeze_exposure path the unit tests stub. The matching side of the freeze (a static-cohort
# condition gates new users while enrolled users keep their variant) is owned by the Rust flags service —
# see test_static_cohort_matching_* in rust/feature-flags/src/flags/test_flag_matching.rs.
class TestFreezeExposureClickhouse(ClickhouseTestMixin, APIBaseTest):
    def test_fetch_exposed_person_uuids_returns_only_the_exposed_set(self) -> None:
        exposed_1 = _create_person(team=self.team, distinct_ids=["exposed-1"])
        exposed_2 = _create_person(team=self.team, distinct_ids=["exposed-2"])
        _create_person(team=self.team, distinct_ids=["other-flag-user"])
        _create_person(team=self.team, distinct_ids=["pre-start-user"])

        start_date = timezone.now() - timedelta(days=7)
        flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="freeze-fetch-flag",
            name="Freeze fetch flag",
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        experiment = Experiment.objects.create(
            name="Freeze fetch experiment",
            team=self.team,
            feature_flag=flag,
            start_date=start_date,
            created_by=self.user,
        )

        for distinct_id in ["exposed-1", "exposed-2"]:
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=distinct_id,
                properties={"$feature_flag": "freeze-fetch-flag"},
                timestamp=start_date + timedelta(days=1),
            )
        # Exposure to a different flag doesn't count.
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="other-flag-user",
            properties={"$feature_flag": "some-other-flag"},
            timestamp=start_date + timedelta(days=1),
        )
        # Exposure before the experiment started doesn't count.
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="pre-start-user",
            properties={"$feature_flag": "freeze-fetch-flag"},
            timestamp=start_date - timedelta(days=1),
        )
        flush_persons_and_events()

        uuids = ExperimentService(team=self.team, user=self.user)._fetch_exposed_person_uuids(experiment)

        assert sorted(uuids) == sorted([str(exposed_1.uuid), str(exposed_2.uuid)])
