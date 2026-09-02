from datetime import datetime, timedelta
from typing import Any

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.models.person import Person

from products.experiments.backend.experiment_service import ExperimentService
from products.experiments.backend.hogql_queries.exposure_query_logic import (
    EXPERIMENT_EXPOSURE_EVENT,
    EXPERIMENT_EXPOSURE_EVENT_CUTOFF,
    EXPERIMENT_EXPOSURE_EVENT_FLAG,
)
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag


# ClickHouse-backed correctness proof for the bounded exposed-set scan (`_fetch_exposed_person_uuids`),
# the one freeze_exposure path the unit tests stub. The matching side of the freeze (a static-cohort
# condition gates new users while enrolled users keep their variant) is owned by the Rust flags service —
# see test_static_cohort_matching_* in rust/feature-flags/src/flags/test_flag_matching.rs.
class TestFreezeExposureClickhouse(ClickhouseTestMixin, APIBaseTest):
    def _create_running_experiment(
        self, flag_key: str, exposure_criteria: dict | None = None, start_date: datetime | None = None
    ) -> Experiment:
        flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key=flag_key,
            name=f"Flag {flag_key}",
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
        return Experiment.objects.create(
            name=f"Experiment {flag_key}",
            team=self.team,
            feature_flag=flag,
            start_date=start_date or (timezone.now() - timedelta(days=7)),
            created_by=self.user,
            exposure_criteria=exposure_criteria or {},
        )

    def _expose_person(
        self,
        distinct_id: str,
        flag_key: str,
        timestamp: datetime,
        *,
        event: str = "$feature_flag_called",
        variant: str | None = "test",
        extra_properties: dict | None = None,
    ) -> Person:
        """Create a person plus an exposure event shaped like the real SDK payloads:
        $feature_flag_called and its ingestion duplicate $experiment_exposure carry
        $feature_flag/$feature_flag_response, any other (custom exposure) event carries the
        $feature/<key> enrollment property."""
        person = _create_person(team=self.team, distinct_ids=[distinct_id])
        if event in ("$feature_flag_called", EXPERIMENT_EXPOSURE_EVENT):
            properties: dict = {"$feature_flag": flag_key}
            if variant is not None:
                properties["$feature_flag_response"] = variant
        else:
            properties = {f"$feature/{flag_key}": variant} if variant is not None else {}
        _create_event(
            team=self.team,
            event=event,
            distinct_id=distinct_id,
            properties={**properties, **(extra_properties or {})},
            timestamp=timestamp,
        )
        return person

    def _service(self) -> ExperimentService:
        return ExperimentService(team=self.team, user=self.user)

    def test_fetch_exposed_person_uuids_returns_only_the_exposed_set(self) -> None:
        experiment = self._create_running_experiment("freeze-fetch-flag")
        assert experiment.start_date is not None
        exposed_at = experiment.start_date + timedelta(days=1)

        exposed_1 = self._expose_person("exposed-1", "freeze-fetch-flag", exposed_at, variant="control")
        exposed_2 = self._expose_person("exposed-2", "freeze-fetch-flag", exposed_at)
        # Exposure to a different flag doesn't count.
        self._expose_person("other-flag-user", "some-other-flag", exposed_at)
        # Exposure before the experiment started doesn't count.
        self._expose_person("pre-start-user", "freeze-fetch-flag", experiment.start_date - timedelta(days=1))
        # A $feature_flag_called that landed no variant (user outside the rollout) is not an
        # enrollment — mirroring the metrics exposure definition.
        self._expose_person("no-variant-user", "freeze-fetch-flag", exposed_at, variant=None)
        flush_persons_and_events()

        uuids = self._service()._fetch_exposed_person_uuids(experiment)

        assert sorted(uuids) == sorted([str(exposed_1.uuid), str(exposed_2.uuid)])

    def test_fetch_exposed_person_uuids_honors_custom_exposure_criteria(self) -> None:
        experiment = self._create_running_experiment(
            "freeze-custom-flag",
            exposure_criteria={
                "exposure_config": {
                    "kind": "ExperimentEventExposureConfig",
                    "event": "checkout started",
                    "properties": [],
                }
            },
        )
        assert experiment.start_date is not None
        exposed_at = experiment.start_date + timedelta(days=1)

        exposed = self._expose_person("custom-exposed", "freeze-custom-flag", exposed_at, event="checkout started")
        # With a custom exposure event configured, plain $feature_flag_called events don't count —
        # teams configure this exactly because those events are absent or unreliable for them.
        self._expose_person("flag-called-only", "freeze-custom-flag", exposed_at)
        # A custom exposure event fired outside the experiment (no enrollment property) doesn't count.
        self._expose_person(
            "custom-no-variant", "freeze-custom-flag", exposed_at, event="checkout started", variant=None
        )
        flush_persons_and_events()

        uuids = self._service()._fetch_exposed_person_uuids(experiment)

        assert uuids == [str(exposed.uuid)]

    @parameterized.expand(
        [
            # (name, rollout flag enabled, experiment start offset from the cutoff, expected event)
            ("after_cutoff", True, 7, EXPERIMENT_EXPOSURE_EVENT),
            ("after_cutoff_flag_disabled", False, 7, "$feature_flag_called"),
            ("before_cutoff", True, -7, "$feature_flag_called"),
        ]
    )
    @freeze_time(EXPERIMENT_EXPOSURE_EVENT_CUTOFF + timedelta(days=10))
    def test_fetch_exposed_person_uuids_reads_the_resolved_exposure_event(
        self, _name: str, flag_enabled: bool, start_offset_days: int, expected_event: str
    ) -> None:
        experiment = self._create_running_experiment(
            "freeze-rollout-flag", start_date=EXPERIMENT_EXPOSURE_EVENT_CUTOFF + timedelta(days=start_offset_days)
        )
        exposed_at = EXPERIMENT_EXPOSURE_EVENT_CUTOFF + timedelta(days=8)
        new_event_person = self._expose_person(
            "new-event-user", "freeze-rollout-flag", exposed_at, event=EXPERIMENT_EXPOSURE_EVENT
        )
        legacy_event_person = self._expose_person("legacy-event-user", "freeze-rollout-flag", exposed_at)
        flush_persons_and_events()

        # Only answer for the exposure-event flag; returning True for every flag would flip
        # unrelated flag-gated behavior on and change what's under test.
        def fake_feature_enabled(flag_key: str, *args: Any, **kwargs: Any) -> bool:
            return flag_enabled if flag_key == EXPERIMENT_EXPOSURE_EVENT_FLAG else False

        with patch("posthoganalytics.feature_enabled", side_effect=fake_feature_enabled):
            uuids = self._service()._fetch_exposed_person_uuids(experiment)

        # The snapshot decides who keeps being served a variant, so it must count exposures on
        # the event the analysis resolves to: read off the other event, a post-cutoff experiment
        # would freeze an empty set once the two events stop being emitted together.
        expected_person = new_event_person if expected_event == EXPERIMENT_EXPOSURE_EVENT else legacy_event_person
        assert uuids == [str(expected_person.uuid)]

    def test_fetch_exposed_person_uuids_ignores_test_account_filters(self) -> None:
        # filterTestAccounts shapes which exposures are *analyzed*; the snapshot decides who keeps
        # being *served* a variant. Applying it here would evict the team's own users at freeze
        # time, so the scan must ignore it even when the criteria enable it.
        self.team.test_account_filters = [
            {"key": "$host", "type": "event", "operator": "not_icontains", "value": "localhost"}
        ]
        self.team.save()
        experiment = self._create_running_experiment(
            "freeze-testacct-flag", exposure_criteria={"filterTestAccounts": True}
        )
        assert experiment.start_date is not None
        exposed_at = experiment.start_date + timedelta(days=1)

        internal = self._expose_person(
            "internal-user", "freeze-testacct-flag", exposed_at, extra_properties={"$host": "localhost:8010"}
        )
        flush_persons_and_events()

        uuids = self._service()._fetch_exposed_person_uuids(experiment)

        assert uuids == [str(internal.uuid)]

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
