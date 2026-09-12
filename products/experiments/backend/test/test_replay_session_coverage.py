from datetime import timedelta

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events

from django.core.cache import cache
from django.utils import timezone

from parameterized import parameterized

from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.replay_session_coverage import COVERAGE_WINDOW_DAYS, resolve_flag_session_coverage
from products.feature_flags.backend.models.feature_flag import FeatureFlag


class TestReplaySessionCoverage(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()

    def _experiment(self, flag_key: str) -> Experiment:
        flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key=flag_key,
            name=flag_key,
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
            start_date=timezone.now() - timedelta(days=3),
            created_by=self.user,
        )

    def _flag_call(
        self,
        distinct_id: str,
        flag_key: str,
        *,
        session_id: str | None,
        days_ago: int = 1,
        host: str | None = None,
    ) -> None:
        properties: dict[str, str] = {"$feature_flag": flag_key, "$feature_flag_response": "test"}
        if session_id is not None:
            properties["$session_id"] = session_id
        if host is not None:
            properties["$host"] = host
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id=distinct_id,
            timestamp=timezone.now() - timedelta(days=days_ago),
            properties=properties,
        )

    def test_a_client_evaluated_flag_does_not_make_a_server_evaluated_one_look_linkable(self) -> None:
        _create_person(team_id=self.team.pk, distinct_ids=["someone"])
        client_side = self._experiment("client-side-flag")
        server_side = self._experiment("server-side-flag")
        self._flag_call("someone", "client-side-flag", session_id="0198f2e4-0000-7000-8000-000000000001")
        self._flag_call("someone", "server-side-flag", session_id=None)
        flush_persons_and_events()

        assert resolve_flag_session_coverage(self.team, client_side).exposure_event is True
        assert resolve_flag_session_coverage(self.team, server_side).exposure_event is False

    @parameterized.expand(
        [
            ("the exposure event has no coverage", None, None, False, True),
            ("the exposure event can match", None, "0198f2e4-0000-7000-8000-000000000002", True, None),
            (
                "the criteria name their own event, which the stamped property can't stand in for",
                {
                    "exposure_config": {
                        "kind": "ExperimentEventExposureConfig",
                        "event": "backend_exposure",
                        "properties": [],
                    }
                },
                None,
                False,
                None,
            ),
        ]
    )
    def test_the_stamped_property_is_only_scanned_where_a_surface_would_use_it(
        self,
        _name: str,
        exposure_criteria: dict | None,
        flag_call_session_id: str | None,
        expected_exposure: bool,
        expected_property: bool | None,
    ) -> None:
        _create_person(team_id=self.team.pk, distinct_ids=["someone"])
        experiment = self._experiment("server-side-flag")
        if exposure_criteria is not None:
            experiment.exposure_criteria = exposure_criteria
            experiment.save()
        self._flag_call("someone", "server-side-flag", session_id=flag_call_session_id)
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="someone",
            timestamp=timezone.now() - timedelta(days=1),
            properties={"$session_id": "0198f2e4-0000-7000-8000-000000000001", "$feature/server-side-flag": "test"},
        )
        flush_persons_and_events()

        coverage = resolve_flag_session_coverage(self.team, experiment)
        assert coverage.exposure_event is expected_exposure
        assert coverage.flag_property is expected_property

    def test_a_flag_with_no_stamped_property_either_reports_neither(self) -> None:
        _create_person(team_id=self.team.pk, distinct_ids=["someone"])
        experiment = self._experiment("server-side-flag")
        self._flag_call("someone", "server-side-flag", session_id=None)
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="someone",
            timestamp=timezone.now() - timedelta(days=1),
            properties={"$session_id": "0198f2e4-0000-7000-8000-000000000001"},
        )
        flush_persons_and_events()

        coverage = resolve_flag_session_coverage(self.team, experiment)
        assert coverage.exposure_event is False
        assert coverage.flag_property is False

    def test_evidence_from_a_filtered_test_account_does_not_count_as_coverage(self) -> None:
        self.team.test_account_filters = [{"key": "$host", "value": "localhost", "operator": "is_not", "type": "event"}]
        self.team.save()
        _create_person(team_id=self.team.pk, distinct_ids=["internal"])
        experiment = self._experiment("server-side-flag")
        experiment.exposure_criteria = {"filterTestAccounts": True}
        experiment.save()
        # The only session-linked evidence of either kind belongs to an account the list drops.
        self._flag_call(
            "internal", "server-side-flag", session_id="0198f2e4-0000-7000-8000-000000000001", host="localhost"
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="internal",
            timestamp=timezone.now() - timedelta(days=1),
            properties={
                "$session_id": "0198f2e4-0000-7000-8000-000000000001",
                "$feature/server-side-flag": "test",
                "$host": "localhost",
            },
        )
        flush_persons_and_events()

        coverage = resolve_flag_session_coverage(self.team, experiment)
        assert coverage.exposure_event is False
        assert coverage.flag_property is False

    def test_coverage_older_than_the_window_does_not_count(self) -> None:
        _create_person(team_id=self.team.pk, distinct_ids=["someone"])
        experiment = self._experiment("server-side-flag")
        experiment.start_date = timezone.now() - timedelta(days=COVERAGE_WINDOW_DAYS + 30)
        experiment.save()
        self._flag_call(
            "someone",
            "server-side-flag",
            session_id="0198f2e4-0000-7000-8000-000000000002",
            days_ago=COVERAGE_WINDOW_DAYS + 5,
        )
        flush_persons_and_events()

        assert resolve_flag_session_coverage(self.team, experiment).exposure_event is False

    @parameterized.expand(
        [
            ("never_launched", {"start_date": None}),
            ("action_exposure", {"exposure_criteria": {"exposure_config": {"kind": "ActionsNode", "id": 7}}}),
        ]
    )
    def test_an_unanswerable_experiment_reports_unknown_rather_than_absent(self, _name: str, attributes: dict) -> None:
        experiment = self._experiment("server-side-flag")
        for field, value in attributes.items():
            setattr(experiment, field, value)
        experiment.save()

        coverage = resolve_flag_session_coverage(self.team, experiment)
        assert coverage.exposure_event is None
        assert coverage.flag_property is None
