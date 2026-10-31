import json
import uuid
import asyncio
import datetime
import dataclasses
from typing import Any

import pytest
import time_machine
from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import override_settings

from parameterized import parameterized
from temporalio import activity
from temporalio.client import Client, ScheduleState
from temporalio.converter import DataConverter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.models import ActivityLog, FileSystemViewLog, Organization, Team, User
from posthog.models.file_system.file_system_representation import FileSystemRepresentation
from posthog.models.file_system.file_system_view_log import log_file_system_view

from products.signals.backend.activity_summary import (
    schedule as tick_schedule,
    tick,
)
from products.signals.backend.activity_summary.computed import MAX_OWNED, MAX_WATCHED
from products.signals.backend.activity_summary.config import ActivitySummaryConfig, SourceWeights, parse_config
from products.signals.backend.activity_summary.prompt import (
    MAX_HEADLINE_CHARS,
    MAX_LABEL_CHARS,
    MAX_THEMES,
    MODES,
    PROMPT_VERSION,
    system_prompt,
    user_message,
)
from products.signals.backend.activity_summary.queue import (
    ActivitySummaryPair,
    ActivitySummaryTierStats,
    DailyUsage,
    daily_usage,
    enrolled_team_ids,
    enrollment,
    feed_queue,
    is_team_enrolled_for_generation,
    is_team_enrolled_for_read,
    max_input_chars,
    max_update_cost_usd,
    organization_rollout_bucket,
    seed_queue,
    select_pairs,
)
from products.signals.backend.activity_summary.render import (
    DEFAULT_LIMITS,
    MAX_LIMITS,
    RENDER_VERSION,
    Product,
    RenderLimits,
)
from products.signals.backend.activity_summary.schedule import (
    ACTIVITY_SUMMARY_TICK_SCHEDULE_ID,
    create_activity_summary_tick_schedule,
)
from products.signals.backend.activity_summary.tick import (
    STOP_ERROR_RATE,
    STOP_GATEWAY_NOT_CONFIGURED,
    STOP_MAX_COST_USD_PER_DAY,
    STOP_MAX_ORG_SHARE,
    STOP_MAX_PAIRS_PER_DAY,
    STOP_MAX_PAIRS_PER_TICK,
    ActivitySummaryPairInput,
    ActivitySummaryPairResult,
    ActivitySummaryTickInput,
    ActivitySummaryTickPlan,
    ActivitySummaryTickResult,
    ActivitySummaryTickWorkflow,
    EnrollmentCounts,
    plan_tick,
    run_pair,
)
from products.signals.backend.models import SignalSourceConfig, UserActivitySummary, UserActivitySummaryQueueState
from products.signals.backend.test.test_activity_summary_render import FakeLLM
from products.tasks.backend.facade.user_task_summaries import UserTaskTime

NOW = datetime.datetime(2026, 10, 19, 12, tzinfo=datetime.UTC)
ANSWER = json.dumps(
    {
        "profile": "## Funnels\n- Builds the signup funnel.",
        "headline": "Builds the signup funnel.",
        "themes": [{"label": "Signup funnel", "mode": "building", "strength": "high", "refs": ["o1"]}],
        "modes": ["building"],
        "recent_shift": None,
    }
)
EMPTY_PROFILE_ANSWER = json.dumps({**json.loads(ANSWER), "profile": "", "themes": [], "modes": []})


_CONFIG_CASES: list[tuple[str, Any, ActivitySummaryConfig]] = [
    ("no payload", None, ActivitySummaryConfig()),
    ("not an object", "[1, 2]", ActivitySummaryConfig()),
    ("enabled is missing", {"organization_ids": ["a"]}, ActivitySummaryConfig()),
    ("enabled is not a bool", {"enabled": "true"}, ActivitySummaryConfig()),
    ("enabled with defaults", {"enabled": True}, ActivitySummaryConfig(enabled=True)),
    (
        "invalid fields fall back to the defaults",
        {
            "enabled": True,
            "organization_ids": ["org-a", 7, ""],
            "skip_team_ids": [3, "4", True],
            "max_pairs_per_tick": 0,
            "max_pairs_per_day": True,
            "max_cost_usd_per_day": -1,
            "max_concurrency": "8",
            "min_units": None,
            "min_update_interval_hours": 0,
            "max_versions": -3,
            "emit_embeddings": "no",
            "rebuild_before": "not a time",
            "max_org_share": 2,
            "rebuild_budget_share": 2,
            "max_error_rate": 0,
            "self_driving_organization_percentage": 101,
            "deny_organization_ids": "org-b",
            "source_weights": {"activity": -1, "tasks": 11, "new_views": True, "scene_views": "1"},
            "min_score": 0,
            "view_update_interval_hours": -5,
            "cold_start_min_active_days": 2.5,
        },
        ActivitySummaryConfig(enabled=True, organization_ids=("org-a",), skip_team_ids=(3,)),
    ),
    (
        "a boolean percentage falls back to the default",
        {"enabled": True, "self_driving_organization_percentage": True},
        ActivitySummaryConfig(enabled=True),
    ),
    (
        "valid fields",
        {
            "enabled": True,
            "max_pairs_per_tick": 5,
            "max_cost_usd_per_day": 1,
            "min_update_interval_hours": 12,
            "max_versions": 5,
            "capture_events": False,
            "rebuild_before": "2026-10-01T00:00:00",
            "enroll_all_approved": True,
            "count_views": True,
            "target_interval_days_free": 7,
            "max_org_share": 0.3,
            "self_driving_organization_percentage": 12.5,
            "deny_organization_ids": ["org-b", 4],
            "source_weights": {"new_views": 1, "repeat_view_days": 0.25},
            "min_score": 4.5,
            "view_update_interval_hours": 72,
            "cold_start_min_active_days": 5,
        },
        ActivitySummaryConfig(
            enabled=True,
            max_pairs_per_tick=5,
            max_cost_usd_per_day=1.0,
            min_update_interval_hours=12.0,
            max_versions=5,
            capture_events=False,
            rebuild_before=datetime.datetime(2026, 10, 1, tzinfo=datetime.UTC),
            enroll_all_approved=True,
            count_views=True,
            target_interval_days_free=7.0,
            max_org_share=0.3,
            self_driving_organization_percentage=12.5,
            deny_organization_ids=("org-b",),
            source_weights=SourceWeights(new_views=1.0, repeat_view_days=0.25),
            min_score=4.5,
            view_update_interval_hours=72.0,
            cold_start_min_active_days=5,
        ),
    ),
    (
        "limits fall back to the defaults when invalid and clamp when too large",
        {
            "enabled": True,
            "limits": {
                "task_lines": 20,
                "activity_lines": 0,
                "max_units_per_day": True,
                "sections_max_chars": "9000",
                "window_days": 10_000,
                "max_completion_tokens": 10_000_000,
            },
        },
        ActivitySummaryConfig(
            enabled=True, limits=RenderLimits(task_lines=20, window_days=90, max_completion_tokens=16000)
        ),
    ),
    ("limits that are not an object", {"enabled": True, "limits": [5]}, ActivitySummaryConfig(enabled=True)),
    (
        "a future rebuild_before waits",
        {"enabled": True, "rebuild_before": "2026-10-20T00:00:00+00:00"},
        ActivitySummaryConfig(enabled=True),
    ),
]


@parameterized.expand(_CONFIG_CASES)
@time_machine.travel(NOW, tick=False)
def test_parse_config(_name: str, payload: Any, expected: ActivitySummaryConfig) -> None:
    assert parse_config(payload) == expected


@parameterized.expand(
    [
        ("canonical", "0188f3a2-5b7c-7d1e-9f00-123456789abc", 3211),
        ("upper case without hyphens", "0188F3A25B7C7D1E9F00123456789ABC", 3211),
        ("other organization", "00000000-0000-0000-0000-000000000001", 8554),
    ]
)
def test_the_rollout_bucket_of_an_organization_does_not_change(_name: str, organization_id: str, bucket: int) -> None:
    assert organization_rollout_bucket(uuid.UUID(organization_id)) == bucket


@parameterized.expand([(10.0, 40.0), (40.0, 100.0)])
def test_a_higher_percentage_keeps_the_organizations_of_a_lower_one(lower: float, higher: float) -> None:
    organization_ids = [uuid.UUID(int=index * 7919) for index in range(500)]

    def members(percentage: float) -> set[uuid.UUID]:
        return {o for o in organization_ids if organization_rollout_bucket(o) < percentage * 100}

    assert members(lower) < members(higher)


@time_machine.travel(NOW, tick=False)
class TestActivitySummaryQueue(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        dispatch_config = patch.object(tick, "read_config", side_effect=lambda: self._config())
        dispatch_config.start()
        self.addCleanup(dispatch_config.stop)

    def _config(self, **overrides: Any) -> ActivitySummaryConfig:
        return ActivitySummaryConfig(enabled=True, organization_ids=(str(self.organization.id),), **overrides)

    def _user(self, email: str) -> User:
        return User.objects.create_and_join(self.organization, email, None)

    def _changes(self, user: User, count: int, *, days_ago: float = 1, team: Team | None = None, **fields: Any):
        for index in range(count):
            ActivityLog.objects.create(
                team_id=(team or self.team).id,
                organization_id=self.organization.id,
                user=user,
                scope="Insight",
                activity="created",
                item_id=str(index),
                detail={"name": f"Funnel {index}"},
                created_at=NOW - datetime.timedelta(days=days_ago + index / 100),
                **fields,
            )

    def _summary(self, user: User, **fields: Any) -> None:
        UserActivitySummary.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            user_id=user.id,
            status=UserActivitySummary.Status.OK,
            **({"prompt_version": PROMPT_VERSION, "render_version": RENDER_VERSION} | fields),
        )

    def _seed(self, config: ActivitySummaryConfig | None = None, tasks: list[UserTaskTime] | None = None) -> None:
        config = config or self._config()
        with patch("products.signals.backend.activity_summary.queue.list_user_task_times", return_value=tasks or []):
            seed_queue(config, enrolled_team_ids(config), NOW)

    def _select(
        self,
        config: ActivitySummaryConfig | None = None,
        tasks: list[UserTaskTime] | None = None,
        *,
        seed: bool = True,
        now: datetime.datetime = NOW,
    ):
        if seed:
            self._seed(config, tasks)
        return [(pair.team_id, pair.user_id) for pair in select_pairs(config or self._config(), now, 10).pairs]

    def test_ranks_by_new_units_times_staleness_with_a_cold_start_bonus(self) -> None:
        self.organization.has_active_subscription = True
        self.organization.save()
        cold, recent_busy, old_quiet, recent_quiet = (
            self._user(f"{name}@example.com") for name in ("cold", "recent_busy", "old_quiet", "recent_quiet")
        )
        for user, days, units in ((recent_busy, 1, 20), (old_quiet, 3, 1), (recent_quiet, 1, 2)):
            summarized = NOW - datetime.timedelta(days=days)
            self._summary(user, generated_at=summarized, input_watermark=summarized)
            self._changes(user, units, days_ago=0.5)
        self._changes(cold, 3, days_ago=0.5)

        assert self._select(self._config(min_score=1, max_org_share=1.0)) == [
            (self.team.id, cold.id),
            (self.team.id, recent_busy.id),
            (self.team.id, old_quiet.id),
            (self.team.id, recent_quiet.id),
        ]

    @parameterized.expand([("the whole tick", 1.0, 2, 1), ("half the tick", 0.5, 1, 1)])
    def test_paying_pairs_and_overdue_free_pairs_come_first_and_one_org_takes_at_most_its_share(
        self, _name: str, paying_budget_share: float, paying_picked: int, fresh_picked: int
    ) -> None:
        self.organization.has_active_subscription = True
        self.organization.save()
        free_org = Organization.objects.create(name="Free")
        free_team = Team.objects.create(organization=free_org, name="Free")
        paying_users = [self._user(f"paying{index}@example.com") for index in range(3)]
        overdue, *fresh = (
            User.objects.create_and_join(free_org, f"{name}@example.com", None)
            for name in ("overdue", "free1", "free2")
        )
        for user in paying_users:
            self._summary(user, generated_at=NOW - datetime.timedelta(hours=20))
            self._changes(user, 3, days_ago=0.1)
        for user, summarized, due in (
            (overdue, NOW - datetime.timedelta(days=20), NOW - datetime.timedelta(hours=10)),
            *((user, NOW - datetime.timedelta(days=2), None) for user in fresh),
        ):
            UserActivitySummary.objects.for_team(free_team.id).create(
                team_id=free_team.id,
                user_id=user.id,
                status=UserActivitySummary.Status.OK,
                generated_at=summarized,
                next_eligible_at=due,
            )
            self._changes(user, 3, days_ago=0.1, team=free_team)
        config = ActivitySummaryConfig(
            enabled=True, enroll_all_approved=True, max_org_share=0.5, paying_budget_share=paying_budget_share
        )
        self._seed(config)

        selection = select_pairs(config, NOW, 4)

        assert [(pair.team_id, pair.user_id) for pair in selection.pairs] == [
            (free_team.id, overdue.id),
            *((self.team.id, user.id) for user in paying_users[:paying_picked]),
            *((free_team.id, user.id) for user in fresh[:fresh_picked]),
        ]
        assert selection.due_pairs == 6
        assert [
            (tier.tier, tier.due_pairs, round(tier.oldest_due_hours or 0, 3), round(tier.fresh_share or 0, 3))
            for tier in selection.tiers
        ] == [("paying", 3, 0.0, 1.0), ("free", 3, 10.0, round(2 / 3, 3))]

    @parameterized.expand([("every stale pair fits the share", 0.3, 2), ("the share caps the rebuilds", 0.1, 1)])
    def test_a_stale_summary_is_due_without_new_rows_and_ranks_with_cold_starts(
        self, _name: str, share: float, rebuilds: int
    ) -> None:
        current, old_version, before_rebuild, busy = (
            self._user(f"{name}@example.com") for name in ("current", "old", "rebuild", "busy")
        )
        summary_fields = {
            "generated_at": NOW - datetime.timedelta(days=2),
            "input_watermark": NOW - datetime.timedelta(days=2),
        }
        self._summary(current, **summary_fields)
        self._summary(old_version, **(summary_fields | {"prompt_version": PROMPT_VERSION - 1}))
        self._summary(before_rebuild, **(summary_fields | {"generated_at": NOW - datetime.timedelta(days=3)}))
        self._summary(busy, **summary_fields)
        for user in (current, old_version, before_rebuild):
            self._changes(user, 1, days_ago=5)
        self._changes(busy, 3)

        config = self._config(
            rebuild_before=NOW - datetime.timedelta(days=2, hours=12), rebuild_budget_share=share, max_org_share=1
        )
        assert self._select(config) == [
            *[(self.team.id, before_rebuild.id), (self.team.id, old_version.id)][:rebuilds],
            (self.team.id, busy.id),
        ]

    def test_leaves_out_pairs_that_are_not_due_or_not_enrolled(self) -> None:
        waiting, scout_only, impersonated, skipped_team = (
            self._user(f"{name}@example.com") for name in ("waiting", "scout", "impersonated", "skipped")
        )
        due = self._user("due@example.com")
        self._summary(waiting, next_eligible_at=NOW + datetime.timedelta(hours=1))
        self._changes(waiting, 3)
        self._changes(scout_only, 3, client="scout:product-analytics")
        self._changes(impersonated, 3, was_impersonated=True)
        other_team = Team.objects.create(organization=self.organization, name="Skipped")
        self._changes(skipped_team, 3, team=other_team)
        self._changes(due, 3)
        other_org = Organization.objects.create(name="Not enrolled")
        self._changes(due, 3, team=Team.objects.create(organization=other_org, name="Other"))

        assert self._select(self._config(skip_team_ids=(other_team.id,))) == [(self.team.id, due.id)]

    def test_enroll_all_approved_enrolls_every_approved_organization(self) -> None:
        user = self._user("member@example.com")
        approved = Team.objects.create(organization=Organization.objects.create(name="Approved"), name="Approved")
        not_approved = Team.objects.create(
            organization=Organization.objects.create(name="Not approved", is_ai_data_processing_approved=False),
            name="Not approved",
        )
        skipped = Team.objects.create(organization=approved.organization, name="Skipped")
        for team in (self.team, approved, not_approved, skipped):
            self._changes(user, 3, team=team)
        config = ActivitySummaryConfig(enabled=True, enroll_all_approved=True, skip_team_ids=(skipped.id,))

        assert sorted(self._select(config)) == sorted([(self.team.id, user.id), (approved.id, user.id)])

    def test_selects_nothing_without_ai_data_processing_approval(self) -> None:
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()
        self._changes(self.user, 3)

        assert self._select() == []

    @parameterized.expand(
        [
            ("listed", {}, True, False, True, True),
            ("disabled", {"enabled": False}, True, False, False, False),
            ("not_listed", {"organization_ids": ("00000000-0000-0000-0000-000000000001",)}, True, False, False, False),
            ("invalid_listed_id", {"organization_ids": ("not-a-uuid",)}, True, False, False, False),
            ("team_skipped", {"skip_team_ids": ("own",)}, True, False, False, False),
            ("not_approved", {}, False, False, False, False),
            ("all_approved", {"organization_ids": (), "enroll_all_approved": True}, True, False, True, True),
            (
                "all_approved_not_approved",
                {"organization_ids": (), "enroll_all_approved": True},
                False,
                False,
                False,
                False,
            ),
            (
                "all_approved_team_skipped",
                {"enroll_all_approved": True, "skip_team_ids": ("own",)},
                True,
                False,
                False,
                False,
            ),
            ("listed_and_denied", {"deny_organization_ids": ("own",)}, True, True, True, False),
            (
                "all_approved_and_denied",
                {"enroll_all_approved": True, "deny_organization_ids": ("own",)},
                True,
                True,
                True,
                False,
            ),
            (
                "rollout",
                {"organization_ids": (), "self_driving_organization_percentage": 100.0},
                True,
                True,
                False,
                True,
            ),
            (
                "rollout_without_source",
                {"organization_ids": (), "self_driving_organization_percentage": 100.0},
                True,
                False,
                False,
                False,
            ),
            (
                "rollout_at_zero",
                {"organization_ids": (), "self_driving_organization_percentage": 0.0},
                True,
                True,
                False,
                False,
            ),
            (
                "rollout_disabled",
                {"enabled": False, "organization_ids": (), "self_driving_organization_percentage": 100.0},
                True,
                True,
                False,
                False,
            ),
            (
                "rollout_denied",
                {
                    "organization_ids": (),
                    "self_driving_organization_percentage": 100.0,
                    "deny_organization_ids": ("own",),
                },
                True,
                True,
                False,
                False,
            ),
            (
                "rollout_team_skipped",
                {"organization_ids": (), "self_driving_organization_percentage": 100.0, "skip_team_ids": ("own",)},
                True,
                True,
                False,
                False,
            ),
            (
                "rollout_not_approved",
                {"organization_ids": (), "self_driving_organization_percentage": 100.0},
                False,
                True,
                False,
                False,
            ),
        ]
    )
    def test_read_and_generation_checks(
        self,
        _name: str,
        overrides: dict[str, Any],
        approved: bool,
        has_source: bool,
        readable: bool,
        generated: bool,
    ) -> None:
        self.organization.is_ai_data_processing_approved = approved
        self.organization.save()
        if overrides.get("skip_team_ids") == ("own",):
            overrides = {**overrides, "skip_team_ids": (self.team.id,)}
        if overrides.get("deny_organization_ids") == ("own",):
            overrides = {**overrides, "deny_organization_ids": (str(self.organization.id).upper(),)}
        if has_source:
            SignalSourceConfig.objects.create(
                team=self.team, source_product="error_tracking", source_type="issue_created", enabled=True
            )
        sourceless = Team.objects.create(organization=self.organization, name="No source")
        config = dataclasses.replace(self._config(), **overrides)
        team = Team.objects.get(id=self.team.id)

        assert is_team_enrolled_for_read(config, team) is readable
        assert is_team_enrolled_for_generation(config, team) is generated
        assert (self.team.id in enrolled_team_ids(config)) is generated
        if config.self_driving_organization_percentage and not config.organization_ids:
            assert sourceless.id not in enrolled_team_ids(config)

    @parameterized.expand([("percentage_0", 0.0, 0), ("percentage_100", 100.0, 1)])
    def test_enrollment_counts_qualifying_organizations_apart_from_enrolled_ones(
        self, _name: str, percentage: float, enrolled: int
    ) -> None:
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        SignalSourceConfig.objects.create(
            team=self.team, source_product="error_tracking", source_type="issue_created", enabled=True
        )
        Team.objects.create(organization=self.organization, name="No source")
        sourceless_organization = Organization.objects.create(name="No source", is_ai_data_processing_approved=True)
        Team.objects.create(organization=sourceless_organization, name="No source")

        result = enrollment(
            dataclasses.replace(self._config(), organization_ids=(), self_driving_organization_percentage=percentage)
        )

        assert result.qualifying_organization_ids == [self.organization.id]
        assert result.organization_ids == [self.organization.id][:enrolled]
        assert result.team_ids == [self.team.id][:enrolled]

    def test_a_pair_is_not_updated_when_the_team_leaves_the_enrollment_before_dispatch(self) -> None:
        self._changes(self.user, 3)
        assert self._select() == [(self.team.id, self.user.id)]
        denied = self._config(deny_organization_ids=(str(self.organization.id),))

        with (
            patch.object(tick, "read_config", return_value=denied),
            patch("products.signals.backend.activity_summary.logic.gateway_client") as gateway,
        ):
            result = run_pair(
                ActivitySummaryPairInput(
                    team_id=self.team.id,
                    user_id=self.user.id,
                    min_units=3,
                    min_update_interval_hours=24,
                    emit_embeddings=True,
                    capture_events=True,
                )
            )

        assert (result.status, result.called_model) == ("skipped_not_enrolled", False)
        gateway.assert_not_called()
        assert not UserActivitySummary.objects.for_team(self.team.id).exists()

    def test_daily_usage_counts_model_calls_and_prices_a_missing_cost_at_the_bound(self) -> None:
        priced, unpriced, skipped = (self._user(f"{name}@example.com") for name in ("priced", "unpriced", "skipped"))
        self._summary(priced, cost_usd=0.25)
        UserActivitySummary.objects.for_team(self.team.id).create(
            team_id=self.team.id, user_id=unpriced.id, status=UserActivitySummary.Status.FAILED
        )
        UserActivitySummary.objects.for_team(self.team.id).create(
            team_id=self.team.id, user_id=skipped.id, status=UserActivitySummary.Status.SKIPPED
        )

        usage = daily_usage(NOW)

        assert usage.updates == 2
        assert usage.cost_usd == pytest.approx(0.25 + max_update_cost_usd(MAX_LIMITS))
        with time_machine.travel(NOW + datetime.timedelta(days=1, minutes=1), tick=False):
            assert daily_usage(NOW + datetime.timedelta(days=1, minutes=1)).updates == 0

    @parameterized.expand(
        [
            ("the tick cap", {"max_pairs_per_tick": 1}, "phs_test", STOP_MAX_PAIRS_PER_TICK, 1),
            ("the daily pair cap", {"max_pairs_per_day": 1}, "phs_test", STOP_MAX_PAIRS_PER_DAY, 0),
            ("the daily cost cap", {"max_cost_usd_per_day": 0.1}, "phs_test", STOP_MAX_COST_USD_PER_DAY, 0),
            ("the org share", {"max_pairs_per_tick": 2, "max_org_share": 0.5}, "phs_test", STOP_MAX_ORG_SHARE, 1),
            ("no cap", {}, "phs_test", None, 2),
            ("no gateway", {}, "", STOP_GATEWAY_NOT_CONFIGURED, 0),
        ]
    )
    def test_plan_names_the_cap_that_stops_it(
        self, _name: str, overrides: dict[str, Any], gateway_key: str, stop_reason: str | None, pairs: int
    ) -> None:
        self._changes(self._user("a@example.com"), 3)
        self._changes(self._user("b@example.com"), 3)
        self._summary(self.user, cost_usd=0.1)
        self._seed()

        with (
            override_settings(
                AI_GATEWAY_URL="https://ai-gateway.example/v1" if gateway_key else "",
                AI_GATEWAY_API_KEY=gateway_key,
                LLM_GATEWAY_URL="",
                LLM_GATEWAY_API_KEY="",
            ),
            patch.object(tick, "read_config", return_value=self._config(**overrides)),
            patch("products.signals.backend.activity_summary.queue.list_user_task_times", return_value=[]),
        ):
            plan = plan_tick(None, NOW)

        assert (plan.stop_reason, len(plan.pairs), plan.enabled) == (stop_reason, pairs, bool(gateway_key))

    @parameterized.expand(
        [
            ("too few units", 2, {"return_value": FakeLLM([ANSWER])}, False, "skipped_too_few_units", False),
            (
                "an exception before the model call",
                3,
                {"side_effect": RuntimeError("no gateway")},
                False,
                "failed",
                False,
            ),
            ("an exception after the model call", 3, {"return_value": FakeLLM([ANSWER])}, True, "failed", True),
            (
                "an empty first profile",
                3,
                {"return_value": FakeLLM([EMPTY_PROFILE_ANSWER])},
                False,
                "skipped_empty_profile",
                True,
            ),
        ]
    )
    def test_a_pair_that_raised_or_skipped_does_not_come_back_on_the_next_tick(
        self, _name: str, changes: int, gateway: dict[str, Any], store_fails: bool, status: str, called_model: bool
    ) -> None:
        self._changes(self.user, changes)
        pair_input = ActivitySummaryPairInput(
            team_id=self.team.id,
            user_id=self.user.id,
            min_units=3,
            min_update_interval_hours=24,
            emit_embeddings=True,
            capture_events=True,
        )
        # The queue picks a pair with fewer rows than the update's `min_units`, so the update skips it.
        config = self._config(min_score=1)
        assert self._select(config) == [(self.team.id, self.user.id)]

        with (
            patch("products.signals.backend.activity_summary.logic.gateway_client", **gateway),
            patch(
                "products.signals.backend.activity_summary.logic.summary_text",
                side_effect=RuntimeError("store failed") if store_fails else None,
                return_value="summary",
            ),
        ):
            result = run_pair(pair_input)

        assert (result.status, result.called_model) == (status, called_model)
        assert self._select(config, seed=False) == []
        if called_model:
            assert result.cost_usd
            usage = daily_usage(NOW)
            assert usage.updates == 1
            assert usage.cost_usd == pytest.approx(result.cost_usd)
        else:
            assert daily_usage(NOW) == DailyUsage(updates=0, cost_usd=0.0)

    def test_an_exception_before_the_model_call_keeps_an_earlier_paid_update_in_the_daily_caps(self) -> None:
        self._changes(self.user, 3)
        UserActivitySummary.objects.for_team(self.team.id).create(
            team_id=self.team.id, user_id=self.user.id, status=UserActivitySummary.Status.FAILED, cost_usd=0.25
        )

        with patch(
            "products.signals.backend.activity_summary.logic.gateway_client", side_effect=RuntimeError("no gateway")
        ):
            result = run_pair(
                ActivitySummaryPairInput(
                    team_id=self.team.id,
                    user_id=self.user.id,
                    min_units=3,
                    min_update_interval_hours=24,
                    emit_embeddings=True,
                    capture_events=True,
                )
            )

        assert (result.status, result.called_model) == ("failed", False)
        assert self._select(seed=False) == []
        assert daily_usage(NOW) == DailyUsage(updates=1, cost_usd=0.25)

    def _view(self, ref: str, *days_ago: int, view_type: str = "insight") -> None:
        days = sorted({(NOW - datetime.timedelta(days=ago)).date() for ago in days_ago})
        FileSystemViewLog.objects.create(
            team=self.team,
            user=self.user,
            type=view_type,
            ref=ref,
            viewed_at=NOW - datetime.timedelta(days=min(days_ago), hours=1),
            view_days=days,
        )

    @parameterized.expand(
        [
            ("known objects reopened every day", True, True, [("a", [5, 2, 1, 0]), ("b", [5, 2, 1, 0])], None),
            ("known scenes reopened every day", True, True, [("scene:a", [5, 2, 1, 0])], None),
            ("too few new objects", True, True, [(str(index), [1]) for index in range(5)], None),
            ("enough new objects", True, True, [(str(index), [1]) for index in range(6)], "views"),
            ("new objects when views do not count", False, True, [(str(index), [1]) for index in range(6)], None),
            (
                "no summary and views on three days",
                True,
                False,
                [("a", [3]), ("b", [2]), ("c", [1])],
                "cold_start_views",
            ),
            ("no summary and views on two days", True, False, [("a", [2]), ("b", [1, 2])], None),
            ("no summary and views on three days when views do not count", False, False, [("a", [3, 2, 1])], None),
        ]
    )
    def test_views_make_a_pair_due_by_weighted_score_or_on_active_days(
        self,
        _name: str,
        count_views: bool,
        summarized: bool,
        views: list[tuple[str, list[int]]],
        trigger: str | None,
    ) -> None:
        if summarized:
            watermark = NOW - datetime.timedelta(days=4)
            self._summary(self.user, generated_at=watermark, input_watermark=watermark)
        for ref, days_ago in views:
            name = ref.removeprefix("scene:")
            self._view(name, *days_ago, view_type="scene" if ref.startswith("scene:") else "insight")
        config = self._config(count_views=count_views)
        self._seed(config)

        selection = select_pairs(config, NOW, 10)

        assert [(pair.user_id, pair.trigger) for pair in selection.pairs] == [(self.user.id, trigger)][: bool(trigger)]
        assert selection.due_by_trigger == {
            name: int(name == trigger) for name in ("activity", "views", "cold_start_views", "stale")
        }

    def test_the_feed_counts_one_repeat_day_for_many_reopens_of_a_known_object_in_a_day(self) -> None:
        watermark = NOW - datetime.timedelta(days=2)
        self._summary(self.user, generated_at=watermark, input_watermark=watermark)
        insight = FileSystemRepresentation(
            base_folder="Unfiled/Insights", type="insight", ref="1", name="Funnel", href="/insights/1", meta={}
        )
        log_file_system_view(
            user=self.user, obj=insight, team_id=self.team.id, viewed_at=NOW - datetime.timedelta(days=3)
        )
        config = self._config(count_views=True, source_weights=SourceWeights(repeat_view_days=1.0))
        feed_queue(config, NOW - datetime.timedelta(hours=3))
        for hours_ago in (2.5, 2, 1.5, 1):
            log_file_system_view(
                user=self.user, obj=insight, team_id=self.team.id, viewed_at=NOW - datetime.timedelta(hours=hours_ago)
            )
            with patch("products.signals.backend.activity_summary.queue.list_user_task_times", return_value=[]):
                feed_queue(config, NOW - datetime.timedelta(hours=hours_ago) + datetime.timedelta(minutes=10))

        state = UserActivitySummaryQueueState.objects.for_team(self.team.id).get(user_id=self.user.id)
        assert (state.pending_score, state.pending_view_score, state.view_active_days) == (1.0, 1.0, 2)

    def test_the_feed_reads_each_row_once_and_an_ok_update_clears_the_pending_units(self) -> None:
        config = self._config()
        with patch("products.signals.backend.activity_summary.queue.list_user_task_times", return_value=[]):
            # The first feed only places the cursors. The backfill command seeds the earlier rows.
            feed_queue(config, NOW - datetime.timedelta(hours=1))
            self._changes(self.user, 3, days_ago=0.02)
            feed_queue(config, NOW)
            feed_queue(config, NOW)
        state = UserActivitySummaryQueueState.objects.for_team(self.team.id).get(user_id=self.user.id)
        assert state.pending_units == 3
        assert self._select(seed=False) == [(self.team.id, self.user.id)]

        with patch("products.signals.backend.activity_summary.logic.gateway_client", return_value=FakeLLM([ANSWER])):
            result = run_pair(
                ActivitySummaryPairInput(
                    team_id=self.team.id,
                    user_id=self.user.id,
                    min_units=3,
                    min_update_interval_hours=24,
                    emit_embeddings=False,
                    capture_events=False,
                )
            )

        assert result.status == "ok"
        later = NOW + datetime.timedelta(days=2)
        assert self._select(seed=False, now=later) == []
        with (
            time_machine.travel(later, tick=False),
            patch("products.signals.backend.activity_summary.queue.list_user_task_times", return_value=[]),
        ):
            self._changes(self.user, 3, days_ago=-0.1)
            feed_queue(config, later)
        assert self._select(seed=False, now=later) == [(self.team.id, self.user.id)]

    @parameterized.expand([("activity", 24), ("views", 168), ("cold_start_views", 168), (None, 24)])
    def test_an_ok_update_emits_the_embedding_and_an_event_without_the_summary(
        self, trigger: str | None, wait_hours: int
    ) -> None:
        self._changes(self.user, 3)
        capture = MagicMock()
        with (
            patch("products.signals.backend.activity_summary.logic.gateway_client", return_value=FakeLLM([ANSWER])),
            patch("posthog.api.embedding_worker.emit_embedding_request") as emit,
            patch.object(tick, "ph_background_capture", return_value=capture),
        ):
            result = run_pair(
                ActivitySummaryPairInput(
                    team_id=self.team.id,
                    user_id=self.user.id,
                    min_units=3,
                    min_update_interval_hours=24,
                    emit_embeddings=True,
                    capture_events=True,
                    trigger=trigger,
                    view_update_interval_hours=168,
                )
            )

        assert (result.status, result.called_model, result.new_summary) == ("ok", True, True)
        stored = UserActivitySummary.objects.for_team(self.team.id).get(user_id=self.user.id)
        assert stored.next_eligible_at == NOW + datetime.timedelta(hours=wait_hours)
        assert emit.call_args.kwargs["document_id"] == f"{self.user.id}:2026-10-19"
        assert emit.call_args.kwargs["content"] == "Builds the signup funnel.\nThemes: Signup funnel"
        event = capture.call_args.kwargs
        assert event["event"] == "activity summary generated"
        assert event["properties"]["trigger"] == trigger
        assert "signup funnel" not in json.dumps(event["properties"]).lower()


@pytest.mark.asyncio
async def test_an_update_keeps_an_operator_pause() -> None:
    client = MagicMock(spec=Client)
    state = ScheduleState(paused=True, note="Paused by an operator")
    client.get_schedule_handle.return_value.describe = AsyncMock(
        return_value=MagicMock(schedule=MagicMock(state=state))
    )
    with (
        patch.object(tick_schedule, "a_schedule_exists", return_value=True),
        patch.object(tick_schedule, "a_create_schedule") as create,
        patch.object(tick_schedule, "a_update_schedule") as update,
    ):
        await create_activity_summary_tick_schedule(client)

    create.assert_not_awaited()
    client.get_schedule_handle.assert_called_once_with(ACTIVITY_SUMMARY_TICK_SCHEDULE_ID)
    assert update.await_args is not None
    assert update.await_args.args[2].state == state


def _plan(pairs: int, **overrides: Any) -> ActivitySummaryTickPlan:
    fields: dict[str, Any] = {
        "enabled": True,
        "pairs": [ActivitySummaryPair(team_id=1, user_id=user_id, trigger="views") for user_id in range(pairs)],
        "candidates": pairs,
        "updates_left": 100,
        "cost_left_usd": 100.0,
        "max_update_cost_usd": 1.0,
        "max_concurrency": 2,
        "min_units": 3,
        "min_update_interval_hours": 24.0,
        "emit_embeddings": True,
        "capture_events": True,
        "limits": DEFAULT_LIMITS,
        "max_error_rate": 0.5,
        "tiers": [ActivitySummaryTierStats(tier="paying", due_pairs=pairs)],
        "enrollment": EnrollmentCounts(qualifying_organizations=3, enrolled_organizations=2, enrolled_teams=4),
        "due_by_trigger": {"activity": 1, "views": pairs - 1},
        "stop_reason": None,
    }
    return ActivitySummaryTickPlan(**{**fields, **overrides})


async def _run_tick(
    plan: ActivitySummaryTickPlan, pair_cost: float | None, pair_status: str = "ok"
) -> tuple[ActivitySummaryTickResult, int, list[ActivitySummaryTickResult], list[ActivitySummaryPairInput]]:
    running = peak = 0
    captured: list[ActivitySummaryTickResult] = []
    pair_inputs: list[ActivitySummaryPairInput] = []

    @activity.defn(name="plan_activity_summary_tick_activity")
    async def fake_plan(input: ActivitySummaryTickInput) -> ActivitySummaryTickPlan:
        return plan

    @activity.defn(name="update_activity_summary_pair_activity")
    async def fake_pair(input: ActivitySummaryPairInput) -> ActivitySummaryPairResult:
        nonlocal running, peak
        pair_inputs.append(input)
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1
        return ActivitySummaryPairResult(
            status=pair_status, cost_usd=pair_cost, called_model=True, new_summary=input.user_id % 2 == 0
        )

    @activity.defn(name="capture_activity_summary_tick_activity")
    async def fake_capture(result: ActivitySummaryTickResult) -> None:
        captured.append(result)

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="activity-summary-tick-test",
            workflows=[ActivitySummaryTickWorkflow],
            activities=[fake_plan, fake_pair, fake_capture],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                ActivitySummaryTickWorkflow.run,
                ActivitySummaryTickInput(),
                id=f"activity-summary-tick-{uuid.uuid4()}",
                task_queue="activity-summary-tick-test",
            )
    return result, peak, captured, pair_inputs


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "plan,pair_cost,pair_status,picked,stop_reason,builds",
    [
        (_plan(5), 0.01, "ok", 5, None, (3, 2)),
        (_plan(5, updates_left=3), 0.01, "ok", 3, STOP_MAX_PAIRS_PER_DAY, (2, 1)),
        # A missing cost counts at the bound, so the second wave spends the last of the budget.
        (_plan(6, cost_left_usd=3.0), None, "ok", 4, STOP_MAX_COST_USD_PER_DAY, (2, 2)),
        # The breaker waits for a sample of 10 model calls, which is five waves.
        (_plan(20), 0.01, "failed", 10, STOP_ERROR_RATE, (0, 0)),
        (_plan(20), 0.01, "skipped_empty_profile", 20, None, (0, 0)),
    ],
)
async def test_the_tick_bounds_concurrency_and_stops_at_the_daily_caps_and_the_error_rate(
    plan: ActivitySummaryTickPlan,
    pair_cost: float | None,
    pair_status: str,
    picked: int,
    stop_reason: str | None,
    builds: tuple[int, int],
) -> None:
    result, peak, captured, pair_inputs = await _run_tick(plan, pair_cost, pair_status)

    assert peak <= plan.max_concurrency
    assert {(pair.trigger, pair.view_update_interval_hours) for pair in pair_inputs} == {("views", 168.0)}
    assert result.due_by_trigger == plan.due_by_trigger
    assert (result.picked, result.statuses, result.stop_reason) == (picked, {pair_status: picked}, stop_reason)
    assert result.tiers == plan.tiers
    assert (result.new_builds, result.refresh_builds) == builds
    assert result.enrollment == plan.enrollment
    assert captured == [result]


@pytest.mark.asyncio
async def test_a_disabled_tick_runs_no_pair() -> None:
    result, peak, captured, _ = await _run_tick(_plan(0, enabled=False), 0.01)

    assert (result, peak, captured) == (ActivitySummaryTickResult(), 0, [])


@parameterized.expand(
    [
        ("tick plan", ActivitySummaryTickPlan, lambda: _plan(1)),
        (
            "pair input",
            ActivitySummaryPairInput,
            lambda: ActivitySummaryPairInput(
                team_id=1,
                user_id=2,
                min_units=3,
                min_update_interval_hours=24.0,
                emit_embeddings=True,
                capture_events=True,
            ),
        ),
    ]
)
def test_a_payload_recorded_before_limits_existed_decodes_with_the_default_limits(
    _name: str, cls: type, build: Any
) -> None:
    converter = DataConverter.default.payload_converter
    recorded = {key: value for key, value in dataclasses.asdict(build()).items() if key != "limits"}

    [decoded] = converter.from_payloads(converter.to_payloads([recorded]), [cls])

    assert decoded == build()
    assert decoded.limits == DEFAULT_LIMITS


def _longest_computed() -> dict[str, Any]:
    long_text = "x" * 500
    products = [str(product) for product in Product]
    owned = {"type": long_text, "id": long_text, "name": long_text, "edit_days": 28, "last_at": "2026-10-18"}
    watched = {"type": long_text, "id": long_text, "name": long_text, "open_days": 28, "last_at": "2026-10-18"}
    return {
        "schema_version": 1,
        "owned": [{"ref": f"o{index}", **owned, "created": True} for index in range(1, MAX_OWNED + 1)],
        "watched": [{"ref": f"o{index}", **watched, "not_theirs": True} for index in range(1, MAX_WATCHED + 1)],
        "pages": [
            {"ref": f"p{index}", "product": product, "open_days": 28, "last_at": "2026-10-18"}
            for index, product in enumerate(products, start=1)
        ],
        "products": {"works_in": products, "visits": products},
        "task_count": 200,
    }


@parameterized.expand(
    [
        ("default limits", DEFAULT_LIMITS),
        ("reduced limits", RenderLimits(sections_max_chars=500, profile_max_chars=500)),
        ("largest limits", MAX_LIMITS),
    ]
)
def test_the_cost_bound_covers_the_longest_input(_name: str, limits: RenderLimits) -> None:
    previous = {
        "headline": "h" * MAX_HEADLINE_CHARS,
        "profile": "p" * limits.profile_max_chars,
        "themes": [
            {"label": "l" * MAX_LABEL_CHARS, "mode": "investigating", "strength": "medium", "last_seen": "2026-10-18"}
        ]
        * MAX_THEMES,
        "modes": list(MODES),
    }
    message = user_message(
        "r" * limits.sections_max_chars,
        previous,
        datetime.date(2026, 10, 18),
        limits.profile_max_chars,
        _longest_computed(),
    )

    assert len(system_prompt(limits.profile_max_chars)) + len(message) <= max_input_chars(limits)
