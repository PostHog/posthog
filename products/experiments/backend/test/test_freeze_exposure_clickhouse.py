from datetime import datetime, timedelta

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events
from unittest.mock import patch

from django.utils import timezone

from rest_framework.exceptions import ValidationError

from posthog.models.person import Person

from products.experiments.backend.experiment_service import ExperimentService
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag


# ClickHouse-backed correctness proof for the bounded exposed-set scan (`_fetch_exposed_person_uuids`),
# the one freeze_exposure path the unit tests stub. The matching side of the freeze (a static-cohort
# condition gates new users while enrolled users keep their variant) is owned by the Rust flags service —
# see test_static_cohort_matching_* in rust/feature-flags/src/flags/test_flag_matching.rs.
class TestFreezeExposureClickhouse(ClickhouseTestMixin, APIBaseTest):
    def _create_running_experiment(self, flag_key: str) -> Experiment:
        flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key=flag_key,
            name=f"Flag {flag_key}",
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        return Experiment.objects.create(
            name=f"Experiment {flag_key}",
            team=self.team,
            feature_flag=flag,
            start_date=timezone.now() - timedelta(days=7),
            created_by=self.user,
        )

    def _expose_person(self, distinct_id: str, flag_key: str, timestamp: datetime) -> Person:
        person = _create_person(team=self.team, distinct_ids=[distinct_id])
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id=distinct_id,
            properties={"$feature_flag": flag_key},
            timestamp=timestamp,
        )
        return person

    def _service(self) -> ExperimentService:
        return ExperimentService(team=self.team, user=self.user)

    def test_fetch_exposed_person_uuids_returns_only_the_exposed_set(self) -> None:
        experiment = self._create_running_experiment("freeze-fetch-flag")
        assert experiment.start_date is not None
        exposed_at = experiment.start_date + timedelta(days=1)

        exposed_1 = self._expose_person("exposed-1", "freeze-fetch-flag", exposed_at)
        exposed_2 = self._expose_person("exposed-2", "freeze-fetch-flag", exposed_at)
        # Exposure to a different flag doesn't count.
        self._expose_person("other-flag-user", "some-other-flag", exposed_at)
        # Exposure before the experiment started doesn't count.
        self._expose_person("pre-start-user", "freeze-fetch-flag", experiment.start_date - timedelta(days=1))
        flush_persons_and_events()

        uuids = self._service()._fetch_exposed_person_uuids(experiment)

        assert sorted(uuids) == sorted([str(exposed_1.uuid), str(exposed_2.uuid)])

    def test_fetch_exposed_person_uuids_is_not_clamped_by_default_query_limit(self) -> None:
        experiment = self._create_running_experiment("freeze-clamp-flag")
        assert experiment.start_date is not None
        exposed_at = experiment.start_date + timedelta(days=1)

        exposed = [self._expose_person(f"exposed-{i}", "freeze-clamp-flag", exposed_at) for i in range(4)]
        flush_persons_and_events()

        # Under the default limit context the HogQL printer rewrites any top-level LIMIT to
        # min(limit, MAX_SELECT_RETURNED_ROWS) — patched to 2 here so a clamp would truncate the
        # snapshot to half the enrolled users without any error. The scan must bypass that clamp:
        # a silently truncated snapshot evicts every user not in it the moment the flag narrows.
        with patch("posthog.hogql.constants.MAX_SELECT_RETURNED_ROWS", 2):
            uuids = self._service()._fetch_exposed_person_uuids(experiment)

        assert sorted(uuids) == sorted(str(person.uuid) for person in exposed)

    @patch("products.experiments.backend.experiment_service.FREEZE_EXPOSURE_MAX_EXPOSED_USERS", 2)
    def test_fetch_exposed_person_uuids_rejects_over_cap_exposed_set(self) -> None:
        experiment = self._create_running_experiment("freeze-overcap-flag")
        assert experiment.start_date is not None
        exposed_at = experiment.start_date + timedelta(days=1)

        for i in range(4):
            self._expose_person(f"exposed-{i}", "freeze-overcap-flag", exposed_at)
        flush_persons_and_events()

        # End-to-end proof that the real query returns cap+1 rows so the over-cap guard can fire —
        # the unit-level guard test mocks the query response, so it can't catch a LIMIT regression.
        with self.assertRaises(ValidationError) as ctx:
            self._service()._fetch_exposed_person_uuids(experiment)
        assert "too many exposed users" in str(ctx.exception)
