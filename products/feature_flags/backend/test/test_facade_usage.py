from datetime import datetime, timedelta
from typing import Any

from posthog.test.base import (
    BaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_flag_evaluations,
    _create_person,
    flush_persons_and_events,
)

from django.utils import timezone

from parameterized import parameterized

from posthog.models.team import Team

from products.experiments.backend.facade.testing import create_experiment
from products.feature_flags.backend.facade.enums import FlagEvaluationsMode
from products.feature_flags.backend.facade.usage import FlagCalls, list_flags_created_by, summarize_flag_calls
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.models.organization_feature_flags_config import OrganizationFeatureFlagsConfig
from products.feature_flags.backend.models.scheduled_change import ScheduledChange


class TestListFlagsCreatedBy(BaseTest):
    def test_lists_only_the_live_flags_the_person_created_in_this_project(self) -> None:
        mine = FeatureFlag.objects.create(team=self.team, key="checkout", created_by=self.user)
        in_experiment = FeatureFlag.objects.create(team=self.team, key="pricing-test", created_by=self.user)
        create_experiment(team_id=self.team.id, feature_flag_id=in_experiment.id, name="Pricing")
        remote = FeatureFlag.objects.create(
            team=self.team, key="app-settings", created_by=self.user, is_remote_configuration=True
        )
        now = timezone.now()
        schedules: dict[str, dict[str, Any]] = {
            "pending-change": {"scheduled_at": now + timedelta(days=1)},
            "recurring-change": {"scheduled_at": now - timedelta(days=1), "executed_at": now, "is_recurring": True},
            "done-change": {"scheduled_at": now - timedelta(days=2), "executed_at": now - timedelta(days=1)},
            "ended-recurring-change": {
                "scheduled_at": now - timedelta(days=9),
                "executed_at": now - timedelta(days=8),
                "is_recurring": True,
                "end_date": now - timedelta(days=1),
            },
        }
        scheduled = {}
        for key, fields in schedules.items():
            scheduled[key] = FeatureFlag.objects.create(team=self.team, key=key, created_by=self.user)
            ScheduledChange.objects.create(
                team=self.team,
                record_id=str(scheduled[key].id),
                model_name=ScheduledChange.AllowedModels.FEATURE_FLAG,
                **fields,
            )
        FeatureFlag.objects.create(team=self.team, key="deleted", created_by=self.user, deleted=True)
        FeatureFlag.objects.create(team=self.team, key="archived", created_by=self.user, archived=True, active=False)
        FeatureFlag.objects.create(team=self.team, key="theirs", created_by=self._create_user("other@example.com"))
        FeatureFlag.objects.create(
            team=Team.objects.create(organization=self.organization), key="elsewhere", created_by=self.user
        )

        flags = list_flags_created_by(self.team.id, self.user.id, limit=10)

        self.assertEqual(
            [(f.id, f.removal_blocked, f.remote_configuration) for f in flags],
            [
                (mine.id, False, False),
                (in_experiment.id, True, False),
                (remote.id, False, True),
                (scheduled["pending-change"].id, True, False),
                (scheduled["recurring-change"].id, True, False),
                (scheduled["done-change"].id, False, False),
                (scheduled["ended-recurring-change"].id, False, False),
            ],
        )


class TestSummarizeFlagCalls(ClickhouseTestMixin, BaseTest):
    def _ago(self, days: int) -> datetime:
        return timezone.now() - timedelta(days=days)

    @parameterized.expand(
        [
            ("events in events mode", FlagEvaluationsMode.EVENTS, "events", True),
            (
                "flag evaluations in flag evaluations mode",
                FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY,
                "flag_evaluations",
                True,
            ),
            ("events in flag evaluations mode", FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY, "events", False),
        ]
    )
    def test_counts_calls_where_the_organization_reads_them(
        self, _name: str, mode: FlagEvaluationsMode, written_to: str, counted: bool
    ) -> None:
        OrganizationFeatureFlagsConfig.objects.update_or_create(
            organization=self.organization, defaults={"flag_evaluations_mode": mode}
        )
        for distinct_id, days in [("user-1", 2), ("user-2", 3), ("user-3", 10)]:
            person = _create_person(team=self.team, distinct_ids=[distinct_id])
            if written_to == "events":
                _create_event(
                    team=self.team,
                    event="$feature_flag_called",
                    distinct_id=distinct_id,
                    properties={"$feature_flag": "checkout", "$feature_flag_response": True},
                    timestamp=self._ago(days),
                )
            else:
                _create_flag_evaluations(
                    self.team.id, "checkout", timestamp=self._ago(days), distinct_id=distinct_id, person_id=person.uuid
                )
        flush_persons_and_events()

        summary = summarize_flag_calls(self.team, self.user)

        expected = FlagCalls(
            people_this_week=2,
            people_last_week=1,
            calls_this_week=2,
            calls=3,
            values_this_week=1,
            value_this_week="true",
        )
        self.assertEqual(
            (dict(summary.by_key), summary.complete, summary.covers_all_environments),
            ({"checkout": expected} if counted else {}, True, True),
        )

    def test_a_call_without_a_readable_flag_key_marks_the_summary_incomplete(self) -> None:
        _create_person(team=self.team, distinct_ids=["user-1"])
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="user-1",
            properties={"$feature_flag_response": True},
            timestamp=self._ago(2),
        )
        flush_persons_and_events()

        summary = summarize_flag_calls(self.team, self.user)

        self.assertEqual((dict(summary.by_key), summary.complete), ({}, False))

    def test_a_project_with_another_environment_is_not_fully_covered(self) -> None:
        Team.objects.create(organization=self.organization, project=self.project, parent_team=self.team, name="Staging")

        self.assertFalse(summarize_flag_calls(self.team, self.user).covers_all_environments)
