"""Tests for experiments facade layer."""

import uuid
from datetime import UTC, datetime, timedelta

import time_machine
from posthog.test.base import (
    APIBaseTest,
    BaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_flag_evaluations,
    flush_persons_and_events,
)

from django.utils import timezone

from parameterized import parameterized

from posthog.models.organization import Organization
from posthog.models.team import Team
from posthog.models.user import User
from posthog.test.persons import create_person

from products.experiments.backend.facade import api, count_running_experiments_on_feature_flag_called, create_experiment
from products.experiments.backend.facade.contracts import CreateExperimentInput, EndedExperiment
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.facade.enums import FlagEvaluationsMode
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.models.organization_feature_flags_config import OrganizationFeatureFlagsConfig

PAGEVIEW_EXPOSURE = {
    "exposure_config": {"kind": "ExperimentEventExposureConfig", "event": "$pageview", "properties": []}
}


class TestCreateExperiment(APIBaseTest):
    """Tests for create_experiment facade function."""

    def test_create_experiment_minimal_fields(self):
        """Test creating experiment with only required fields."""
        input_dto = CreateExperimentInput(
            name="Test Experiment",
            feature_flag_key="test-flag",
        )

        result = create_experiment(team=self.team, user=self.user, input_dto=input_dto)

        # Verify DTO fields
        assert result.name == "Test Experiment"
        assert result.feature_flag_key == "test-flag"
        assert result.is_draft is True
        assert result.description is None or result.description == ""

        # Verify model was created
        from products.experiments.backend.models.experiment import Experiment

        experiment = Experiment.objects.get(id=result.id)
        assert experiment.name == "Test Experiment"
        assert experiment.feature_flag.key == "test-flag"
        assert experiment.feature_flag_rule_id is None
        assert experiment.feature_flag_rule_snapshot is None

    def test_create_experiment_with_description(self):
        """Test creating experiment with description."""
        input_dto = CreateExperimentInput(
            name="Test Experiment",
            feature_flag_key="test-flag-2",
            description="Testing the facade layer",
        )

        result = create_experiment(team=self.team, user=self.user, input_dto=input_dto)

        assert result.description == "Testing the facade layer"

    def test_create_experiment_with_experiment_own_parameters(self):
        """parameters carries experiment-own keys (variant_notes) and is persisted verbatim."""
        input_dto = CreateExperimentInput(
            name="Test Experiment",
            feature_flag_key="test-flag-3",
            parameters={"variant_notes": {"control": "baseline", "test": "new checkout"}},
        )

        result = create_experiment(team=self.team, user=self.user, input_dto=input_dto)

        from products.experiments.backend.models.experiment import Experiment

        experiment = Experiment.objects.get(id=result.id)
        assert experiment.parameters == {"variant_notes": {"control": "baseline", "test": "new checkout"}}

    @time_machine.travel("2025-01-01 12:00:00", tick=False)
    def test_create_experiment_with_start_date(self):
        """Test creating launched (non-draft) experiment."""
        start_date = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
        input_dto = CreateExperimentInput(
            name="Test Experiment",
            feature_flag_key="test-flag-6",
            start_date=start_date,
        )

        result = create_experiment(team=self.team, user=self.user, input_dto=input_dto)

        assert result.is_draft is False
        assert result.start_date == start_date

    def test_create_experiment_with_metrics(self):
        """Test creating experiment with metrics."""
        input_dto = CreateExperimentInput(
            name="Test Experiment",
            feature_flag_key="test-flag-7",
            metrics=[
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "source": {"kind": "EventsNode", "event": "$pageview"},
                }
            ],
            allow_unknown_events=True,
        )

        result = create_experiment(team=self.team, user=self.user, input_dto=input_dto)

        # Verify experiment was created with metrics
        from products.experiments.backend.models.experiment import Experiment

        experiment = Experiment.objects.get(id=result.id)
        assert experiment.metrics is not None
        assert len(experiment.metrics) == 1

    def test_create_experiment_with_all_fields(self):
        """Test creating experiment with comprehensive field set."""
        input_dto = CreateExperimentInput(
            name="Comprehensive Test",
            feature_flag_key="test-flag-8",
            description="Full feature test",
            type="web",
            parameters={"minimum_detectable_effect": 5},
            metrics=[
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "source": {"kind": "EventsNode", "event": "$pageview"},
                }
            ],
            stats_config={"method": "bayesian"},
            exposure_criteria={"filter_test_accounts": True},
            archived=False,
            deleted=False,
            allow_unknown_events=True,
        )

        result = create_experiment(team=self.team, user=self.user, input_dto=input_dto)

        assert result.name == "Comprehensive Test"
        assert result.description == "Full feature test"


class TestCountRunningExperimentsOnFeatureFlagCalled(BaseTest):
    @parameterized.expand(
        [
            ("running_on_the_default_exposure", {}, datetime(2026, 8, 1, tzinfo=UTC), None, False, False, False, 1),
            (
                "custom_exposure_event",
                PAGEVIEW_EXPOSURE,
                datetime(2026, 8, 1, tzinfo=UTC),
                None,
                False,
                False,
                False,
                0,
            ),
            ("draft", {}, None, None, False, False, False, 0),
            ("ended", {}, datetime(2026, 8, 1, tzinfo=UTC), datetime(2026, 8, 20, tzinfo=UTC), False, False, False, 0),
            ("archived", {}, datetime(2026, 8, 1, tzinfo=UTC), None, True, False, False, 0),
            ("deleted", {}, datetime(2026, 8, 1, tzinfo=UTC), None, False, True, False, 0),
            ("another_organization", {}, datetime(2026, 8, 1, tzinfo=UTC), None, False, False, True, 0),
        ]
    )
    def test_counts_only_running_experiments_that_count_exposures_on_feature_flag_called(
        self,
        _name: str,
        exposure_criteria: dict,
        start_date: datetime | None,
        end_date: datetime | None,
        archived: bool,
        deleted: bool,
        other_organization: bool,
        expected: int,
    ) -> None:
        team = (
            Team.objects.create(organization=Organization.objects.create(name="Other"), name="Other")
            if other_organization
            else self.team
        )
        flag = FeatureFlag.objects.create(team=team, key="experiment-flag", created_by=self.user)
        Experiment.objects.create(
            team=team,
            name="Experiment",
            feature_flag=flag,
            exposure_criteria=exposure_criteria,
            start_date=start_date,
            end_date=end_date,
            archived=archived,
            deleted=deleted,
        )

        assert count_running_experiments_on_feature_flag_called(self.organization.id) == expected


@time_machine.travel("2026-10-14T12:00:00Z", tick=False)
class TestHighlightFacts(BaseTest):
    def _experiment(self, name: str, created_by: User | None = None, **fields: object) -> Experiment:
        flag = FeatureFlag.objects.create(team=self.team, key=f"flag-{uuid.uuid4().hex[:8]}", created_by=self.user)
        return Experiment.objects.create(
            team=self.team, name=name, feature_flag=flag, created_by=created_by or self.user, **fields
        )

    def test_lists_ended_experiments_without_a_conclusion(self) -> None:
        now = timezone.now()
        started = now - timedelta(days=30)
        ended_at = now - timedelta(days=1)
        listed = self._experiment("Pricing page layout", start_date=started, end_date=ended_at)
        self._experiment("Concluded", start_date=started, end_date=ended_at, conclusion="won")
        self._experiment("Ended long ago", start_date=started, end_date=now - timedelta(days=10))
        self._experiment("Archived", start_date=started, end_date=ended_at, archived=True)
        self._experiment("Deleted", start_date=started, end_date=ended_at, deleted=True)
        self._experiment("Still running", start_date=started)
        self._experiment(
            "Not yours", start_date=started, end_date=ended_at, created_by=self._create_user("other@example.com")
        )

        assert api.list_ended_experiments_without_conclusion(
            team_id=self.team.pk, user_id=self.user.pk, since=now - timedelta(days=7), limit=20
        ) == [EndedExperiment(id=listed.id, name="Pricing page layout", ended_at=ended_at)]

    @parameterized.expand(
        [("any start", None, ["Checkout copy", "Onboarding tips"]), ("a recent start", 67, ["Checkout copy"])]
    )
    def test_lists_running_experiments_that_started_in_the_window(
        self, _name: str, started_after_days: int | None, expected: list[str]
    ) -> None:
        now = timezone.now()
        listed = {
            experiment.name: experiment.feature_flag.key
            for experiment in (
                self._experiment("Onboarding tips", start_date=now - timedelta(days=80)),
                self._experiment("Checkout copy", start_date=now - timedelta(days=62)),
            )
        }
        self._experiment("Started recently", start_date=now - timedelta(days=10))
        self._experiment("Custom exposure", start_date=now - timedelta(days=62), exposure_criteria=PAGEVIEW_EXPOSURE)
        self._experiment(
            "Activation",
            start_date=now - timedelta(days=62),
            exposure_criteria={"activation_config": {"event": "signed up", "properties": []}},
        )
        self._experiment(
            "Filtered exposure",
            start_date=now - timedelta(days=62),
            exposure_criteria={
                "exposure_config": {
                    "kind": "ExperimentEventExposureConfig",
                    "event": "$feature_flag_called",
                    "properties": [{"key": "plan", "value": ["paid"], "operator": "exact", "type": "person"}],
                }
            },
        )
        self._experiment(
            "Legacy criteria",
            start_date=now - timedelta(days=62),
            exposure_criteria={"multiple_variant_handling": "whatever_this_was"},
        )
        self._experiment("Draft")
        self._experiment("Ended", start_date=now - timedelta(days=80), end_date=now - timedelta(days=1))
        self._experiment(
            "Not yours", start_date=now - timedelta(days=80), created_by=self._create_user("other@example.com")
        )

        found = api.list_running_experiments(
            team_id=self.team.pk,
            user_id=self.user.pk,
            started_after=None if started_after_days is None else now - timedelta(days=started_after_days),
            started_before=now - timedelta(days=60),
            limit=20,
        )

        assert [(e.name, e.flag_key) for e in found] == [(name, listed[name]) for name in expected]


class TestCountEnrolledPeople(ClickhouseTestMixin, BaseTest):
    def _ago(self, days: int) -> datetime:
        return timezone.now() - timedelta(days=days)

    @parameterized.expand(
        [("events", FlagEvaluationsMode.EVENTS), ("flag_evaluations", FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY)]
    )
    def test_counts_people_who_got_a_variant_in_the_last_14_days(self, _name: str, mode: FlagEvaluationsMode) -> None:
        OrganizationFeatureFlagsConfig.objects.update_or_create(
            organization=self.organization, defaults={"flag_evaluations_mode": mode}
        )
        calls = [
            ("checkout", "test", 2),
            ("checkout", "control", 3),
            ("checkout", "false", 2),
            ("checkout", "test", 20),
            ("other", "test", 2),
        ]
        for flag_key, response, days_ago in calls:
            distinct_id = str(uuid.uuid4())
            if mode == FlagEvaluationsMode.EVENTS:
                create_person(team=self.team, distinct_ids=[distinct_id])
                _create_event(
                    team=self.team,
                    event="$feature_flag_called",
                    distinct_id=distinct_id,
                    properties={"$feature_flag": flag_key, "$feature_flag_response": response},
                    timestamp=self._ago(days_ago),
                )
            else:
                _create_flag_evaluations(
                    self.team.pk, flag_key, timestamp=self._ago(days_ago), distinct_id=distinct_id, response=response
                )
        flush_persons_and_events()

        assert api.count_enrolled_people(team=self.team, user=self.user, flag_keys=["checkout"]) == {"checkout": 2}
