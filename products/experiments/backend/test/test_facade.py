"""Tests for experiments facade layer."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
import time_machine
from posthog.test.base import (
    APIBaseTest,
    BaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_flag_evaluations,
    flush_persons_and_events,
)
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized

from posthog.models.organization import Organization
from posthog.models.team import Team
from posthog.models.team.team import DEPRECATED_ATTRS
from posthog.models.user import User
from posthog.test.db_context_capturing import capture_db_queries
from posthog.test.persons import create_person

from products.experiments.backend.facade import api, count_running_experiments_on_feature_flag_called, create_experiment
from products.experiments.backend.facade.change_signals import connect_experiment_changed, experiment_changed
from products.experiments.backend.facade.contracts import (
    CreateExperimentInput,
    DigestCompletedExperiment,
    DigestLaunchedExperiment,
    EndedExperiment,
    ExperimentChanged,
    ExperimentValidationError,
    LinkedExperiment,
    StoredPrimaryResult,
    TeamExperimentsSettings,
    TeamExperimentsSettingsUpdate,
)
from products.experiments.backend.metric_calculation.config import build_primary_calculation_configs
from products.experiments.backend.models.experiment import Experiment, ExperimentHoldout, ExperimentMetricResult
from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig
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

    def test_create_experiment_refuses_a_holdout_of_another_team(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other")
        holdout = ExperimentHoldout.objects.create(team=other_team, created_by=self.user, name="Other team holdout")
        input_dto = CreateExperimentInput(name="Test Experiment", feature_flag_key="test-flag-9", holdout_id=holdout.id)

        with self.assertRaisesMessage(
            ExperimentValidationError, f"Holdout with id {holdout.id} does not exist for this team"
        ):
            create_experiment(team=self.team, user=self.user, input_dto=input_dto)

        assert not Experiment.objects.filter(team=self.team, name="Test Experiment").exists()


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


@time_machine.travel("2026-10-28T12:00:00Z", tick=False)
class TestConnectExperimentChanged(BaseTest):
    def test_receiver_gets_every_save_and_delete_inside_the_transaction(self) -> None:
        received: list[ExperimentChanged] = []

        def receiver(*, change: ExperimentChanged, **kwargs: object) -> None:
            received.append(change)

        connect_experiment_changed(receiver, dispatch_uid="test_connect_experiment_changed")
        self.addCleanup(experiment_changed.disconnect, dispatch_uid="test_connect_experiment_changed")

        flag = FeatureFlag.objects.create(team=self.team, key="checkout-flag", created_by=self.user)
        experiment = Experiment.objects.create(
            team=self.team, name="Checkout", description="Shorter checkout", feature_flag=flag
        )
        experiment_id = experiment.id
        experiment.deleted = True
        experiment.save()
        experiment.deleted = False
        experiment.archived = True
        experiment.save()
        experiment.delete()

        def change(*, created: bool, deleted: bool, archived: bool) -> ExperimentChanged:
            return ExperimentChanged(
                team_id=self.team.id,
                experiment_id=experiment_id,
                created=created,
                deleted=deleted,
                name="Checkout",
                description="Shorter checkout",
                archived=archived,
                created_at=timezone.now(),
                updated_at=timezone.now(),
            )

        # BaseTest never commits, so a receiver deferred to the commit would leave this list empty.
        assert received == [
            change(created=True, deleted=False, archived=False),
            change(created=False, deleted=True, archived=False),
            change(created=False, deleted=False, archived=True),
            change(created=False, deleted=True, archived=True),
        ]


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


_CHECKOUT = {"kind": "EventsNode", "event": "checkout"}


class TestGetStoredPrimaryResult(BaseTest):
    def _stored(self, metric: dict, stats_config: dict, baseline_sum: int) -> StoredPrimaryResult | None:
        flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="stored-result")
        experiment = Experiment.objects.create(
            team=self.team,
            feature_flag=flag,
            name="stored result",
            start_date=datetime(2026, 8, 1, tzinfo=UTC),
            stats_config=stats_config,
            metrics=[{"uuid": "m1", "kind": "ExperimentMetric", "name": "Checkout", "goal": "decrease", **metric}],
        )
        ExperimentMetricResult.objects.create(
            experiment=experiment,
            metric_uuid="m1",
            fingerprint=build_primary_calculation_configs(experiment)[0].calculation_key(),
            query_from=datetime(2026, 8, 1, tzinfo=UTC),
            query_to=datetime(2026, 8, 5, tzinfo=UTC),
            status=ExperimentMetricResult.Status.COMPLETED,
            completed_at=datetime(2026, 8, 5, tzinfo=UTC),
            result={
                "baseline": {"key": "control", "number_of_samples": 100, "sum": baseline_sum, "sum_squares": 20},
                "variant_results": [
                    {
                        "key": "test",
                        "method": "frequentist",
                        "number_of_samples": 50,
                        "sum": 15,
                        "sum_squares": 15,
                        "confidence_interval": [0.1, 0.4],
                        "significant": True,
                    }
                ],
            },
        )
        return api.get_stored_primary_result(team_id=self.team.pk, experiment_id=experiment.pk)

    @parameterized.expand(
        [
            ("funnel", {"metric_type": "funnel", "series": [_CHECKOUT]}, 20, 0.25, True),
            ("thresholded_mean", {"metric_type": "mean", "threshold": 5, "source": _CHECKOUT}, 20, 0.25, True),
            ("negative_baseline_mean", {"metric_type": "mean", "source": _CHECKOUT}, -20, None, False),
        ]
    )
    def test_returns_the_current_stored_result_of_the_primary_metric(
        self, _name: str, metric: dict, baseline_sum: int, change: float | None, proportion: bool
    ) -> None:
        result = self._stored(metric, {"method": "frequentist"}, baseline_sum)

        assert result is not None
        assert (result.metric_name, result.proportion, result.goal) == ("Checkout", proportion, "decrease")
        assert result.baseline.mean == pytest.approx(baseline_sum / 100)
        assert (result.variants[0].mean, result.variants[0].significant) == (0.3, True)
        assert result.variants[0].change == (None if change is None else pytest.approx(change))

    def test_returns_nothing_for_absolute_differences(self) -> None:
        stats_config = {"method": "frequentist", "frequentist": {"difference_type": "ABSOLUTE"}}

        assert self._stored({"metric_type": "funnel", "series": [_CHECKOUT]}, stats_config, 20) is None


class TestTeamHasLaunchedExperiments(BaseTest):
    @parameterized.expand(
        [
            ("draft", None, None, False, False, False),
            ("running", datetime(2026, 9, 1, tzinfo=UTC), None, False, False, True),
            ("stopped", datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 9, 20, tzinfo=UTC), False, False, True),
            ("deleted_still_counts", datetime(2026, 9, 1, tzinfo=UTC), None, True, False, True),
            ("another_team", datetime(2026, 9, 1, tzinfo=UTC), None, False, True, False),
        ]
    )
    def test_counts_running_and_stopped_experiments_of_the_team(
        self,
        _name: str,
        start_date: datetime | None,
        end_date: datetime | None,
        deleted: bool,
        other_team: bool,
        expected: bool,
    ) -> None:
        team = Team.objects.create(organization=self.organization, name="Other") if other_team else self.team
        flag = FeatureFlag.objects.create(team=team, key="experiment-flag", created_by=self.user)
        Experiment.objects.create(
            team=team, name="Experiment", feature_flag=flag, start_date=start_date, end_date=end_date, deleted=deleted
        )

        assert api.team_has_launched_experiments(self.team.id) is expected


class TestExperimentFlagIds(BaseTest):
    @parameterized.expand(
        [
            ("with_deleted", True, {"live", "archived", "deleted", "deleted_null", "listed_team"}),
            ("without_deleted", False, {"live", "archived", "listed_team"}),
        ]
    )
    def test_returns_the_flags_of_the_listed_teams_experiments(
        self, _name: str, include_deleted: bool, expected: set[str]
    ) -> None:
        listed_team = Team.objects.create(organization=self.organization, name="Listed")
        unlisted_team = Team.objects.create(organization=self.organization, name="Unlisted")
        flag_ids: dict[str, int] = {}
        for key, team, deleted, archived in [
            ("live", self.team, False, False),
            ("archived", self.team, False, True),
            ("deleted", self.team, True, False),
            ("deleted_null", self.team, None, False),
            ("listed_team", listed_team, False, False),
            ("unlisted_team", unlisted_team, False, False),
        ]:
            flag = FeatureFlag.objects.create(team=team, key=key, created_by=self.user)
            Experiment.objects.create(team=team, name=key, feature_flag=flag, deleted=deleted, archived=archived)
            flag_ids[key] = flag.id

        assert api.experiment_flag_ids([self.team.id, listed_team.id], include_deleted=include_deleted) == {
            flag_ids[key] for key in expected
        }


class TestFlagLiveExperiments(BaseTest):
    def test_lists_the_experiments_that_are_not_deleted_per_listed_flag(self) -> None:
        now = timezone.now()
        flag_ids: dict[str, int] = {}
        experiment_ids: dict[str, int] = {}
        for flag_key, name, start_date, end_date, deleted, archived in [
            ("running", "running", now, None, False, False),
            ("running", "draft on the same flag", None, None, False, False),
            ("stopped", "stopped", now - timedelta(days=1), now, False, False),
            ("archived", "archived", now, None, False, True),
            ("deleted", "deleted", now, None, True, False),
            ("deleted_null", "deleted_null", now, None, None, False),
            ("unlisted", "unlisted", now, None, False, False),
        ]:
            if flag_key not in flag_ids:
                flag_ids[flag_key] = FeatureFlag.objects.create(team=self.team, key=flag_key, created_by=self.user).id
            experiment_ids[name] = Experiment.objects.create(
                team=self.team,
                name=name,
                feature_flag_id=flag_ids[flag_key],
                start_date=start_date,
                end_date=end_date,
                deleted=deleted,
                archived=archived,
            ).id
        flag_ids["no_experiment"] = FeatureFlag.objects.create(team=self.team, key="none", created_by=self.user).id
        listed = {key: flag_id for key, flag_id in flag_ids.items() if key != "unlisted"}

        def linked(name: str, is_running: bool) -> LinkedExperiment:
            return LinkedExperiment(id=experiment_ids[name], name=name, is_running=is_running)

        experiments = api.live_experiments_by_flag(listed.values())

        assert {flag_id: set(linked_experiments) for flag_id, linked_experiments in experiments.items()} == {
            flag_ids["running"]: {linked("running", True), linked("draft on the same flag", False)},
            flag_ids["stopped"]: {linked("stopped", False)},
            flag_ids["archived"]: {linked("archived", True)},
        }
        assert {key: api.flag_has_live_experiment(flag_id) for key, flag_id in listed.items()} == {
            "running": True,
            "stopped": True,
            "archived": True,
            "deleted": False,
            "deleted_null": False,
            "no_experiment": False,
        }


class TestDigestExperiments(BaseTest):
    def test_lists_the_experiments_launched_and_completed_in_the_period(self) -> None:
        period_start = datetime(2026, 10, 19, tzinfo=UTC)
        period_end = datetime(2026, 10, 26, tzinfo=UTC)
        day = timedelta(days=1)
        next_batch_team = Team.objects.create(organization=self.organization, name="Next batch")
        ids: dict[str, int] = {}
        for name, team, start_date, end_date, deleted in [
            ("started at the period start", self.team, period_start, None, False),
            ("started in the period", self.team, period_start + day, None, False),
            ("started at the period end", self.team, period_end, None, False),
            ("started and ended in the period", self.team, period_start + day, period_start + 2 * day, False),
            ("ended after the period", self.team, period_start + day, period_end + day, False),
            ("ended at the period start", self.team, period_start - 10 * day, period_start, False),
            ("ended at the period end", self.team, period_start - 10 * day, period_end, False),
            ("ended without a launch", self.team, None, period_start + 3 * day, False),
            ("deleted", self.team, period_start + day, None, True),
            ("launched in the next batch", next_batch_team, period_start + day, None, False),
            ("ended in the next batch", next_batch_team, period_start - 10 * day, period_end, False),
        ]:
            flag = FeatureFlag.objects.create(team=team, key=f"flag-{len(ids)}", created_by=self.user)
            experiment = Experiment.objects.create(
                team=team, name=name, feature_flag=flag, start_date=start_date, end_date=end_date, deleted=deleted
            )
            ids[name] = experiment.id
        batch = range(self.team.id, next_batch_team.id)

        launched = api.list_launched_experiments_for_digest(
            period_start=period_start, period_end=period_end, team_ids=batch
        )
        completed = api.list_completed_experiments_for_digest(
            period_start=period_start, period_end=period_end, team_ids=batch
        )

        assert sorted(launched, key=lambda experiment: experiment.id) == [
            DigestLaunchedExperiment(team_id=self.team.id, id=ids[name], name=name, start_date=start_date)
            for name, start_date in [
                ("started in the period", period_start + day),
                ("started at the period end", period_end),
                ("ended after the period", period_start + day),
                ("deleted", period_start + day),
            ]
        ]
        assert sorted(completed, key=lambda experiment: experiment.id) == [
            DigestCompletedExperiment(
                team_id=self.team.id, id=ids[name], name=name, start_date=start_date, end_date=end_date
            )
            for name, start_date, end_date in [
                ("started and ended in the period", period_start + day, period_start + 2 * day),
                ("ended at the period end", period_start - 10 * day, period_end),
                ("ended without a launch", None, period_start + 3 * day),
            ]
        ]


class TestPrecomputationSettings(BaseTest):
    def test_lists_the_teams_with_precomputation_enabled(self) -> None:
        enabled_team = Team.objects.create(organization=self.organization, name="Enabled")
        disabled_team = Team.objects.create(organization=self.organization, name="Disabled")
        unconfigured_team = Team.objects.create(organization=self.organization, name="Unconfigured")
        TeamExperimentsConfig.objects.create(team=self.team, experiment_precomputation_enabled=True)
        TeamExperimentsConfig.objects.create(team=enabled_team, experiment_precomputation_enabled=True)
        TeamExperimentsConfig.objects.create(team=disabled_team, experiment_precomputation_enabled=False)

        assert api.list_precomputation_enabled_team_ids() == {self.team.id, enabled_team.id}
        assert api.list_precomputation_enabled_team_ids([self.team.id, disabled_team.id, unconfigured_team.id]) == {
            self.team.id
        }

    @parameterized.expand([("turns_off_an_auto_enrollment", True, False), ("creates_the_missing_row", False, True)])
    def test_setting_precomputation_marks_it_as_a_manual_decision(
        self, _name: str, auto_enrolled: bool, enabled: bool
    ) -> None:
        if auto_enrolled:
            TeamExperimentsConfig.objects.create(
                team=self.team,
                experiment_precomputation_enabled=True,
                precomputation_enabled_set_by=TeamExperimentsConfig.PrecomputationEnabledSetBy.AUTO,
            )

        api.set_precomputation_enabled(team_id=self.team.id, enabled=enabled)

        config = TeamExperimentsConfig.objects.get(team=self.team)
        assert (config.experiment_precomputation_enabled, config.precomputation_enabled_set_by) == (
            enabled,
            TeamExperimentsConfig.PrecomputationEnabledSetBy.MANUAL,
        )


def _github_with_repositories(*full_names: str) -> MagicMock:
    return MagicMock(
        return_value=SimpleNamespace(
            list_all_cached_repositories=lambda max_repos: [{"full_name": full_name} for full_name in full_names]
        )
    )


class TestTeamExperimentsSettings(BaseTest):
    def test_reads_every_setting(self) -> None:
        TeamExperimentsConfig.objects.create(
            team=self.team,
            experiment_recalculation_times=["02:00:00", "14:00:00"],
            default_experiment_confidence_level=Decimal("0.90"),
            default_experiment_stats_method="frequentist",
            experiment_precomputation_enabled=False,
            default_only_count_matured_users=True,
            default_cuped_enabled=False,
            default_cuped_lookback_days=14,
            default_minimum_detectable_effect=7,
            default_sequential_testing_enabled=True,
            default_sequential_tuning_parameter=5000,
            flag_cleanup_repository="posthog/posthog",
        )

        with self.assertNumQueries(1), capture_db_queries() as queries:
            settings = api.get_team_experiments_settings(self.team.id)

        # A team join must keep the deprecated taxonomy columns deferred, as `TeamManager` does.
        selected = " ".join(query["sql"] for query in queries.captured_queries)
        assert [attr for attr in DEPRECATED_ATTRS if f'"{attr}"' in selected] == []
        assert settings == TeamExperimentsSettings(
            experiment_recalculation_times=("02:00:00", "14:00:00"),
            default_experiment_confidence_level=Decimal("0.90"),
            default_experiment_stats_method="frequentist",
            experiment_precomputation_enabled=False,
            default_only_count_matured_users=True,
            default_cuped_enabled=False,
            default_cuped_lookback_days=14,
            default_minimum_detectable_effect=7,
            default_sequential_testing_enabled=True,
            default_sequential_tuning_parameter=5000,
            flag_cleanup_repository="posthog/posthog",
        )

    def test_update_changes_only_the_settings_it_sets(self) -> None:
        TeamExperimentsConfig.objects.create(
            team=self.team,
            experiment_recalculation_times=["02:00:00"],
            default_cuped_lookback_days=14,
            default_minimum_detectable_effect=7,
        )

        with patch(
            "products.tasks.backend.facade.repo_selection.resolve_team_github_integration",
            _github_with_repositories("PostHog/posthog"),
        ):
            updated = api.update_team_experiments_settings(
                team_id=self.team.id,
                update=TeamExperimentsSettingsUpdate(
                    experiment_recalculation_times=("14:00:00", "02:00:00"),
                    default_experiment_confidence_level=Decimal("0.90"),
                    default_cuped_lookback_days=None,
                    flag_cleanup_repository="PostHog/PostHog",
                ),
            )

        stored = api.get_team_experiments_settings(self.team.id)
        assert updated == stored
        assert (
            stored.experiment_recalculation_times,
            stored.default_experiment_confidence_level,
            stored.default_cuped_lookback_days,
            stored.default_minimum_detectable_effect,
            stored.flag_cleanup_repository,
        ) == (("14:00:00", "02:00:00"), Decimal("0.90"), None, 7, "posthog/posthog")

    @parameterized.expand(
        [
            (
                "recalculation_times_too_close",
                {"experiment_recalculation_times": ("08:00:00", "09:00:00")},
                "experiment_recalculation_times",
                "Recalculation times must be at least 6 hours apart.",
            ),
            (
                "recalculation_times_empty",
                {"experiment_recalculation_times": ()},
                "experiment_recalculation_times",
                "Recalculation times must be a non-empty list of 'HH:00:00' strings.",
            ),
            (
                "confidence_level_of_one",
                {"default_experiment_confidence_level": Decimal("1.00")},
                "default_experiment_confidence_level",
                "Ensure this value is less than or equal to 0.99.",
            ),
            (
                "unknown_stats_method",
                {"default_experiment_stats_method": "magic"},
                "default_experiment_stats_method",
                "Value 'magic' is not a valid choice.",
            ),
            (
                "cuped_lookback_too_long",
                {"default_cuped_lookback_days": 31},
                "default_cuped_lookback_days",
                "Ensure this value is less than or equal to 30.",
            ),
            (
                "malformed_repository",
                {"flag_cleanup_repository": "not-a-repo"},
                "flag_cleanup_repository",
                "Repository must be in the format organization/repository",
            ),
            (
                "repository_outside_the_installation",
                {"flag_cleanup_repository": "other/repo"},
                "flag_cleanup_repository",
                "This repository is not connected to the project's GitHub integration.",
            ),
        ]
    )
    def test_update_refuses_an_invalid_setting_and_saves_nothing(
        self, _name: str, invalid: dict[str, Any], field: str, message: str
    ) -> None:
        before = api.get_team_experiments_settings(self.team.id)

        with (
            patch(
                "products.tasks.backend.facade.repo_selection.resolve_team_github_integration",
                _github_with_repositories("PostHog/posthog"),
            ),
            pytest.raises(ExperimentValidationError) as raised,
        ):
            api.update_team_experiments_settings(
                team_id=self.team.id, update=TeamExperimentsSettingsUpdate(default_cuped_enabled=True, **invalid)
            )

        assert (raised.value.field, str(raised.value)) == (field, message)
        assert api.get_team_experiments_settings(self.team.id) == before
