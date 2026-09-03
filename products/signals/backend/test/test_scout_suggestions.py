import random
import asyncio
from datetime import timedelta

import pytest
from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import SimpleTestCase
from django.utils import timezone

import pytest_asyncio
from asgiref.sync import sync_to_async
from parameterized import parameterized
from rest_framework import status
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.constants import AvailableFeature
from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.models.integration import Integration
from posthog.models.scoping import team_scope
from posthog.sync import database_sync_to_async

from products.access_control.backend.models.access_control import AccessControl
from products.signals.backend.models import SignalScoutConfig, SignalScoutSuggestionSet, SignalSourceConfig
from products.signals.backend.scout_harness.suggestions import (
    ScoutSuggestionBatch,
    ScoutSuggestionItem,
    SuggestionSettings,
    dismiss_suggestion,
    mark_generation_failed,
    mark_suggestion_created,
    parse_suggestion_settings,
    persist_suggestion_batch,
    plan_suggestion_runs,
    visible_items,
)
from products.signals.backend.scout_harness.suggestions_runner import arun_scout_suggestions, validate_suggestion_items
from products.tasks.backend.models import Task

CANONICAL = {"signals-scout-general", "signals-scout-error-tracking"}


def _item(**overrides) -> ScoutSuggestionItem:
    base = {
        "kind": "canonical",
        "skill_name": "signals-scout-error-tracking",
        "title": "Watch new error spikes",
        "why_here": "The project ingests $exception events at volume.",
    }
    return ScoutSuggestionItem(**{**base, **overrides})


def _custom(**overrides) -> ScoutSuggestionItem:
    base = {
        "kind": "custom",
        "skill_name": "signals-scout-checkout-drop",
        "description": "Watches the checkout funnel.",
        "draft_body": "# Checkout drop\n\nCheck the checkout funnel daily.",
    }
    return _item(**{**base, **overrides})


class TestSuggestionSettings(SimpleTestCase):
    @parameterized.expand(
        [
            ("absent", None, False, 1, 10),
            ("enabled_string_is_off", {"enabled": "true", "eligibility_tier": 3}, False, 3, 10),
            ("tier_clamped", {"enabled": True, "eligibility_tier": 99, "max_children_per_tick": -5}, True, 4, 0),
            ("tier_zero_is_allowlist_only", {"enabled": True, "eligibility_tier": 0}, True, 0, 10),
            ("tier_below_zero_clamps_to_zero", {"enabled": True, "eligibility_tier": -3}, True, 0, 10),
            ("bool_is_not_int", {"enabled": True, "max_children_per_tick": True}, True, 1, 10),
        ]
    )
    def test_malformed_payload_degrades_to_safe_defaults(self, _name, payload, enabled, tier, cap):
        settings = parse_suggestion_settings(payload)
        self.assertEqual(
            (settings.enabled, settings.eligibility_tier, settings.max_children_per_tick), (enabled, tier, cap)
        )

    def test_allowlist_ignores_non_int_entries(self):
        settings = parse_suggestion_settings({"enabled": True, "team_allowlist": [2, "3", True, 4]})
        self.assertEqual(settings.team_allowlist, frozenset({2, 4}))


class TestValidateSuggestionItems(SimpleTestCase):
    @parameterized.expand(
        [
            ("unknown_canonical", _item(skill_name="signals-scout-nope")),
            ("already_enabled", _item(skill_name="signals-scout-general")),
            ("custom_shadows_canonical", _custom(skill_name="signals-scout-error-tracking")),
            ("custom_bad_slug", _custom(skill_name="scout-checkout")),
            ("custom_uppercase_slug", _custom(skill_name="signals-scout-Checkout")),
            ("custom_double_hyphen", _custom(skill_name="signals-scout--checkout")),
            ("six_field_cron", _item(proposed_config={"run_cron_schedule": "0 30 9 * * *"})),
            ("cron_under_30_min_gap", _item(proposed_config={"run_cron_schedule": "*/15 * * * *"})),
            ("custom_empty_body", _custom(draft_body="   ")),
            ("custom_no_description", _custom(description="")),
            ("custom_description_over_create_limit", _custom(description="x" * 4097)),
            ("bad_cron", _item(proposed_config={"run_cron_schedule": "every tuesday"})),
            # Syntactically valid but never occurs; croniter only raises on enumeration, which
            # must drop the item rather than fail the whole batch.
            ("impossible_calendar_cron", _item(proposed_config={"run_cron_schedule": "0 0 31 2 *"})),
            # Valid, hourly, and longer than the config API's column: Create would reject it.
            (
                "cron_over_create_length_limit",
                _item(
                    proposed_config={
                        "run_cron_schedule": f"0 {','.join(map(str, range(24)))} {','.join(map(str, range(1, 32)))} * *"
                    }
                ),
            ),
            ("interval_below_floor", _item(proposed_config={"run_interval_minutes": 5})),
            ("blank_title", _item(title="  ")),
            ("custom_reuses_a_stored_skill_name", _custom(skill_name="signals-scout-disabled-custom")),
        ]
    )
    def test_drops_items_create_could_not_apply(self, _name, item):
        kept = validate_suggestion_items(
            [item],
            enabled_skill_names={"signals-scout-general"},
            canonical_names=CANONICAL,
            reserved_names={"signals-scout-disabled-custom"},
        )
        self.assertEqual(kept, [])

    def test_blank_cron_normalizes_to_none(self):
        kept = validate_suggestion_items(
            [_item(proposed_config={"run_cron_schedule": "  "})], enabled_skill_names=set(), canonical_names=CANONICAL
        )
        self.assertIsNone(kept[0].proposed_config.run_cron_schedule)

    def test_keeps_valid_items_dedupes_and_caps_at_five(self):
        items = [_item(), _item(), _custom()] + [_custom(skill_name=f"signals-scout-extra-{i}") for i in range(5)]
        kept = validate_suggestion_items(items, enabled_skill_names=set(), canonical_names=CANONICAL)
        self.assertEqual(len(kept), 5)
        self.assertEqual(kept[0].skill_name, "signals-scout-error-tracking")
        self.assertEqual(kept[1].skill_name, "signals-scout-checkout-drop")
        self.assertEqual(len({item.skill_name for item in kept}), 5)


class TestSuggestionPersistence(BaseTest):
    def test_dismissal_survives_refresh_and_created_items_are_hidden(self):
        row = persist_suggestion_batch(
            self.team.id, [_item(), _custom()], task_run_id=None, model="m", fleet_snapshot=["signals-scout-general"]
        )
        first_id, custom_id = (record["id"] for record in row.items)
        self.assertIsNotNone(dismiss_suggestion(self.team.id, first_id, user_id=self.user.id))
        self.assertIsNotNone(mark_suggestion_created(self.team.id, custom_id, config_id="cfg-1"))
        row.refresh_from_db()
        self.assertEqual(visible_items(row), [])

        row = persist_suggestion_batch(
            self.team.id, [_item(), _custom(title="Renamed")], task_run_id=None, model="m", fleet_snapshot=[]
        )
        by_name = {record["skill_name"]: record for record in row.items}
        self.assertIsNotNone(by_name["signals-scout-error-tracking"]["dismissed_at"])
        self.assertEqual(by_name["signals-scout-error-tracking"]["id"], first_id)
        self.assertEqual(by_name["signals-scout-checkout-drop"]["created_config_id"], "cfg-1")
        self.assertEqual(row.status, SignalScoutSuggestionSet.Status.FRESH)
        self.assertEqual(row.consecutive_failures, 0)

    def test_dismissal_tombstone_survives_a_batch_that_omits_it(self):
        row = persist_suggestion_batch(
            self.team.id, [_item(), _custom()], task_run_id=None, model=None, fleet_snapshot=[]
        )
        dismiss_suggestion(self.team.id, row.items[0]["id"], user_id=self.user.id)
        persist_suggestion_batch(self.team.id, [_custom()], task_run_id=None, model=None, fleet_snapshot=[])
        row = persist_suggestion_batch(
            self.team.id, [_item(), _custom()], task_run_id=None, model=None, fleet_snapshot=[]
        )
        self.assertEqual([record["skill_name"] for record in visible_items(row)], ["signals-scout-checkout-drop"])

    def test_dismissing_a_compacted_tombstone_again_is_not_found(self):
        row = persist_suggestion_batch(self.team.id, [_custom()], task_run_id=None, model=None, fleet_snapshot=[])
        suggestion_id = row.items[0]["id"]
        dismiss_suggestion(self.team.id, suggestion_id, user_id=self.user.id)
        persist_suggestion_batch(self.team.id, [_item()], task_run_id=None, model=None, fleet_snapshot=[])
        # The tombstone keeps the id but has no item fields left to serialize.
        self.assertIsNone(dismiss_suggestion(self.team.id, suggestion_id, user_id=self.user.id))

    def test_omitted_tombstone_drops_the_draft_body_it_no_longer_needs(self):
        row = persist_suggestion_batch(
            self.team.id, [_custom(draft_body="b" * 5_000)], task_run_id=None, model=None, fleet_snapshot=[]
        )
        dismiss_suggestion(self.team.id, row.items[0]["id"], user_id=self.user.id)
        row = persist_suggestion_batch(self.team.id, [_item()], task_run_id=None, model=None, fleet_snapshot=[])
        tombstone = next(record for record in row.items if record["skill_name"] == "signals-scout-checkout-drop")
        self.assertIsNotNone(tombstone["dismissed_at"])
        self.assertNotIn("draft_body", tombstone)

    def test_batch_generated_against_a_moved_fleet_is_stored_stale(self):
        SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-general", enabled=True)
        row = persist_suggestion_batch(self.team.id, [_item()], task_run_id=None, model=None, fleet_snapshot=[])
        self.assertEqual(row.status, SignalScoutSuggestionSet.Status.STALE)

    def test_empty_batch_generated_against_a_moved_fleet_is_stale(self):
        SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-general", enabled=True)
        row = persist_suggestion_batch(self.team.id, [], task_run_id=None, model=None, fleet_snapshot=[])
        self.assertEqual(row.status, SignalScoutSuggestionSet.Status.STALE)

    def test_visible_items_hides_scouts_enabled_since_generation(self):
        row = persist_suggestion_batch(
            self.team.id, [_item(), _custom()], task_run_id=None, model=None, fleet_snapshot=[]
        )
        visible = visible_items(row, enabled_skill_names={"signals-scout-error-tracking"})
        self.assertEqual([record["skill_name"] for record in visible], ["signals-scout-checkout-drop"])

    def test_failed_generation_keeps_prior_items_and_counts_toward_breaker(self):
        persist_suggestion_batch(self.team.id, [_item()], task_run_id=None, model=None, fleet_snapshot=[])
        row = mark_generation_failed(self.team.id, task_run_id=None)
        row = mark_generation_failed(self.team.id, task_run_id=None)
        self.assertEqual(row.status, SignalScoutSuggestionSet.Status.FAILED)
        self.assertEqual(row.consecutive_failures, 2)
        self.assertEqual(len(visible_items(row)), 1)

    def test_dismissing_unknown_id_is_a_noop(self):
        persist_suggestion_batch(self.team.id, [_item()], task_run_id=None, model=None, fleet_snapshot=[])
        self.assertIsNone(dismiss_suggestion(self.team.id, "nope", user_id=None))

    def test_enabling_a_scout_marks_a_fresh_batch_stale(self):
        persist_suggestion_batch(self.team.id, [_item()], task_run_id=None, model=None, fleet_snapshot=[])
        SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-general", enabled=True)
        row = SignalScoutSuggestionSet.all_teams.get(team=self.team)
        self.assertEqual(row.status, SignalScoutSuggestionSet.Status.STALE)


class TestPlanSuggestionRuns(BaseTest):
    def setUp(self):
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        self.now = timezone.now()

    def _team(self, name: str, *, approved: bool = True) -> Team:
        organization = Organization.objects.create(name=name, is_ai_data_processing_approved=approved)
        return Team.objects.create(organization=organization, name=name)

    def _enable_scout(self, team: Team, *, engaged: bool) -> None:
        config = SignalScoutConfig.objects.create(team=team, skill_name="signals-scout-general", enabled=True)
        if engaged:
            config.status_changed_by = self.user
            config.save()
        else:
            # Push the touch outside the engagement window without a human attached to it.
            SignalScoutConfig.all_teams.filter(pk=config.pk).update(updated_at=self.now - timedelta(days=90))

    def test_disabled_payload_plans_nothing(self):
        self._enable_scout(self.team, engaged=True)
        self.assertEqual(plan_suggestion_runs(SuggestionSettings(enabled=False), self.now), [])

    def test_tier_one_then_never_generated_then_most_overdue(self):
        engaged_fresh = self.team
        self._enable_scout(engaged_fresh, engaged=True)
        engaged_overdue = self._team("overdue")
        self._enable_scout(engaged_overdue, engaged=True)
        quiet = self._team("quiet")
        self._enable_scout(quiet, engaged=False)
        unapproved = self._team("unapproved", approved=False)
        self._enable_scout(unapproved, engaged=True)
        self._team("no-signals-setup")

        SignalScoutSuggestionSet.all_teams.create(team=engaged_fresh, last_requested_at=self.now - timedelta(days=1))
        SignalScoutSuggestionSet.all_teams.create(team=engaged_overdue, last_requested_at=self.now - timedelta(days=30))

        planned = plan_suggestion_runs(SuggestionSettings(enabled=True, eligibility_tier=2), self.now)
        self.assertEqual([(run.team_id, run.tier) for run in planned], [(engaged_overdue.id, 1), (quiet.id, 2)])

        tier_one_only = plan_suggestion_runs(SuggestionSettings(enabled=True, eligibility_tier=1), self.now)
        self.assertEqual([run.team_id for run in tier_one_only], [engaged_overdue.id])

    def test_a_scout_a_person_created_counts_as_engagement(self):
        # Creation stamps `created_by` but no status transition, so `status_changed_by` stays
        # null; the project is still being actively managed and must not fall to tier 2.
        SignalScoutConfig.objects.create(
            team=self.team, skill_name="signals-scout-general", enabled=True, created_by=self.user
        )
        registered = self._team("coordinator-registered")
        SignalScoutConfig.objects.create(team=registered, skill_name="signals-scout-general", enabled=True)

        planned = plan_suggestion_runs(SuggestionSettings(enabled=True, eligibility_tier=2), self.now)
        self.assertEqual([(run.team_id, run.tier) for run in planned], [(self.team.id, 1), (registered.id, 2)])

    def test_cap_allowlist_blocklist_and_breaker(self):
        self._enable_scout(self.team, engaged=True)
        second = self._team("second")
        self._enable_scout(second, engaged=True)
        second_env = Team.objects.create(organization=second.organization, name="second-env", parent_team=second)
        broken = self._team("broken")
        self._enable_scout(broken, engaged=True)
        SignalScoutSuggestionSet.all_teams.create(
            team=broken,
            last_requested_at=self.now - timedelta(days=30),
            consecutive_failures=3,
            last_completed_at=self.now - timedelta(hours=1),
        )
        # Past the cooldown even though a dismissal just touched the row: the clock is the last attempt.
        recovered = self._team("recovered")
        self._enable_scout(recovered, engaged=True)
        SignalScoutSuggestionSet.all_teams.create(
            team=recovered,
            last_requested_at=self.now - timedelta(days=30),
            consecutive_failures=3,
            last_completed_at=self.now - timedelta(hours=25),
        )
        outsider = self._team("outsider")
        outsider_env = Team.objects.create(
            organization=outsider.organization, name="outsider-env", parent_team=outsider
        )

        # Flag lists name child environments; the plan lands on their canonical projects.
        planned = plan_suggestion_runs(
            SuggestionSettings(
                enabled=True,
                max_children_per_tick=3,
                team_allowlist=frozenset({outsider_env.id}),
                team_blocklist=frozenset({second_env.id}),
            ),
            self.now,
        )
        self.assertEqual([run.team_id for run in planned], [outsider.id, self.team.id, recovered.id])

        # Tier 0 drops every fleet tier: only the allowlist is planned.
        allowlist_only = plan_suggestion_runs(
            SuggestionSettings(
                enabled=True,
                eligibility_tier=0,
                max_children_per_tick=3,
                team_allowlist=frozenset({outsider_env.id}),
            ),
            self.now,
        )
        self.assertEqual([(run.team_id, run.tier) for run in allowlist_only], [(outsider.id, 0)])

    def test_breaker_backs_a_failing_project_off_past_its_refresh_window(self):
        # Both are long past the 24h cooldown and past a plain 7-day refresh, so only the
        # doubling breaker separates them.
        healthy = self._team("healthy")
        self._enable_scout(healthy, engaged=True)
        SignalScoutSuggestionSet.all_teams.create(
            team=healthy, last_requested_at=self.now - timedelta(days=8), last_completed_at=self.now - timedelta(days=8)
        )
        failing = self._team("failing")
        self._enable_scout(failing, engaged=True)
        SignalScoutSuggestionSet.all_teams.create(
            team=failing,
            last_requested_at=self.now - timedelta(days=8),
            last_completed_at=self.now - timedelta(days=8),
            consecutive_failures=3,
        )

        settings = SuggestionSettings(enabled=True)
        self.assertEqual([run.team_id for run in plan_suggestion_runs(settings, self.now)], [healthy.id])
        # Once it is overdue against the doubled window it comes back, so the breaker slows the
        # spend rather than parking the project forever.
        self.assertIn(failing.id, [run.team_id for run in plan_suggestion_runs(settings, self.now + timedelta(days=7))])

    def test_root_source_config_does_not_hide_wider_tiers(self):
        SignalSourceConfig.objects.create(team=self.team, source_product="error_tracking", source_type="issue_created")
        plain = self._team("plain")
        OrganizationMembership.objects.create(organization=plain.organization, user=self.user)
        self.user.last_login = self.now
        self.user.save()

        planned = plan_suggestion_runs(SuggestionSettings(enabled=True, eligibility_tier=3), self.now)
        self.assertIn((plain.id, 3), [(run.team_id, run.tier) for run in planned])

    def test_source_config_in_a_child_environment_makes_the_project_eligible(self):
        project = self._team("project")
        env = Team.objects.create(organization=project.organization, name="env", parent_team=project)
        SignalSourceConfig.objects.create(team=env, source_product="error_tracking", source_type="issue_created")

        planned = plan_suggestion_runs(SuggestionSettings(enabled=True, eligibility_tier=2), self.now)
        self.assertEqual([(run.team_id, run.tier) for run in planned], [(project.id, 2)])


class TestManualSuggestionsDispatch(BaseTest):
    def test_manual_dispatch_stamps_planner_state(self):
        from products.signals.backend.temporal.agentic.scout_suggestions import start_manual_scout_suggestions_run

        client = MagicMock()
        client.start_workflow = AsyncMock()
        with patch(
            "products.signals.backend.temporal.agentic.scout_suggestions.read_suggestion_settings",
            return_value=SuggestionSettings(enabled=True),
        ):
            start_manual_scout_suggestions_run(client, team_id=self.team.id)

        client.start_workflow.assert_awaited_once()
        row = SignalScoutSuggestionSet.all_teams.get(team=self.team)
        self.assertIsNotNone(row.last_requested_at)
        settings = SuggestionSettings(enabled=True, team_allowlist=frozenset({self.team.id}))
        self.assertEqual(plan_suggestion_runs(settings, timezone.now()), [])

    def test_manual_dispatch_survives_a_failed_stamp(self):
        from products.signals.backend.temporal.agentic.scout_suggestions import start_manual_scout_suggestions_run

        client = MagicMock()
        client.start_workflow = AsyncMock()
        with (
            patch(
                "products.signals.backend.temporal.agentic.scout_suggestions.read_suggestion_settings",
                return_value=SuggestionSettings(enabled=True),
            ),
            patch(
                "products.signals.backend.temporal.agentic.scout_suggestions.stamp_requested",
                side_effect=RuntimeError("db down"),
            ),
        ):
            workflow_id = start_manual_scout_suggestions_run(client, team_id=self.team.id)
        self.assertEqual(workflow_id, f"scout-suggestions-manual-run-{self.team.id}")


@pytest_asyncio.fixture
async def asuggestion_team():
    organization = await sync_to_async(Organization.objects.create)(
        name=f"ScoutSuggestionsOrg-{random.randint(1, 99999)}", is_ai_data_processing_approved=True
    )
    team = await sync_to_async(Team.objects.create)(
        organization=organization, name=f"ScoutSuggestionsTeam-{random.randint(1, 99999)}"
    )
    with team_scope(team.id, canonical=True):
        yield team
    await sync_to_async(team.delete)()
    await sync_to_async(organization.delete)()


def _fake_session() -> MagicMock:
    session = MagicMock()
    session.task_run.id = "11111111-1111-1111-1111-111111111111"
    session.end = AsyncMock()
    return session


_RUNNER = "products.signals.backend.scout_harness.suggestions_runner"


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_runner_persists_validated_batch(asuggestion_team):
    batch = ScoutSuggestionBatch(suggestions=[_custom(), _item(skill_name="signals-scout-not-canonical")])
    session = _fake_session()
    with (
        patch(f"{_RUNNER}.MultiTurnSession.start", new_callable=AsyncMock, return_value=(session, batch)) as start,
        patch(f"{_RUNNER}.get_or_create_signals_sandbox_env", return_value="env"),
        patch(f"{_RUNNER}.resolve_acting_user_id_for_team", return_value=42),
        patch("products.signals.backend.scout_harness.suggestions.discover_canonical_skills", return_value=()),
    ):
        result = await arun_scout_suggestions(asuggestion_team.id, acting_user_id=7)

    assert (result.status, result.suggestion_count) == ("completed", 1)
    row = await database_sync_to_async(SignalScoutSuggestionSet.all_teams.get)(team=asuggestion_team)
    assert [record["skill_name"] for record in visible_items(row)] == ["signals-scout-checkout-drop"]
    assert str(row.task_run_id) == "11111111-1111-1111-1111-111111111111"
    assert start.call_args.kwargs["context"].posthog_mcp_scopes == "read_only"
    # The manual caller's identity wins over the resolved team member (patched to 42 above).
    assert start.call_args.kwargs["context"].user_id == 7
    assert start.call_args.kwargs["fallback_from_text"] is None
    session.end.assert_awaited_once_with()


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.parametrize("failing_stage", ["unparseable_close_out", "sandbox_setup"])
async def test_runner_records_a_failure_anywhere_after_the_gates(asuggestion_team, failing_stage):
    session_error = ValueError("no json") if failing_stage == "unparseable_close_out" else None
    sandbox_error = RuntimeError("no sandbox") if failing_stage == "sandbox_setup" else None
    with (
        patch(f"{_RUNNER}.MultiTurnSession.start", new_callable=AsyncMock, side_effect=session_error),
        patch(f"{_RUNNER}.get_or_create_signals_sandbox_env", return_value="env", side_effect=sandbox_error),
        patch(f"{_RUNNER}.resolve_acting_user_id_for_team", return_value=42),
        patch("products.signals.backend.scout_harness.suggestions.discover_canonical_skills", return_value=()),
    ):
        result = await arun_scout_suggestions(asuggestion_team.id)

    assert result.status == "failed"
    row = await database_sync_to_async(SignalScoutSuggestionSet.all_teams.get)(team=asuggestion_team)
    assert (row.status, row.consecutive_failures) == (SignalScoutSuggestionSet.Status.FAILED, 1)


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_runner_fails_a_batch_that_validates_down_to_nothing(asuggestion_team):
    # Every suggestion names an unknown canonical scout, so validation drops the lot. Storing that
    # as an empty success would reset the breaker and buy a whole refresh window.
    batch = ScoutSuggestionBatch(suggestions=[_item(skill_name="signals-scout-not-canonical")])
    session = _fake_session()
    with (
        patch(f"{_RUNNER}.MultiTurnSession.start", new_callable=AsyncMock, return_value=(session, batch)),
        patch(f"{_RUNNER}.get_or_create_signals_sandbox_env", return_value="env"),
        patch(f"{_RUNNER}.resolve_acting_user_id_for_team", return_value=42),
        patch("products.signals.backend.scout_harness.suggestions.discover_canonical_skills", return_value=()),
    ):
        result = await arun_scout_suggestions(asuggestion_team.id)

    assert result.status == "failed"
    row = await database_sync_to_async(SignalScoutSuggestionSet.all_teams.get)(team=asuggestion_team)
    assert (row.status, row.consecutive_failures) == (SignalScoutSuggestionSet.Status.FAILED, 1)
    # The TaskRun must not read as completed when nothing was stored: triage reads its status.
    session.end.assert_awaited_once()
    assert session.end.await_args.kwargs["status"] == "failed"


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_runner_records_a_cancelled_scan_as_a_failure(asuggestion_team):
    # The activity deadline cancels with a BaseException, which the runner's `except Exception`
    # would miss; the coordinator has already stamped the request either way.
    with (
        patch(f"{_RUNNER}.MultiTurnSession.start", new_callable=AsyncMock, side_effect=asyncio.CancelledError()),
        patch(f"{_RUNNER}.get_or_create_signals_sandbox_env", return_value="env"),
        patch(f"{_RUNNER}.resolve_acting_user_id_for_team", return_value=42),
        patch("products.signals.backend.scout_harness.suggestions.discover_canonical_skills", return_value=()),
        pytest.raises(asyncio.CancelledError),
    ):
        await arun_scout_suggestions(asuggestion_team.id)

    row = await database_sync_to_async(SignalScoutSuggestionSet.all_teams.get)(team=asuggestion_team)
    assert (row.status, row.consecutive_failures) == (SignalScoutSuggestionSet.Status.FAILED, 1)


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_runner_skips_unapproved_org_before_any_spend(asuggestion_team):
    organization = asuggestion_team.organization
    organization.is_ai_data_processing_approved = False
    await sync_to_async(organization.save)()
    with patch(f"{_RUNNER}.MultiTurnSession.start", new_callable=AsyncMock) as start:
        result = await arun_scout_suggestions(asuggestion_team.id)

    assert (result.status, result.skip_reason) == ("skipped", "ai_data_processing_not_approved")
    start.assert_not_called()
    assert not await database_sync_to_async(SignalScoutSuggestionSet.all_teams.filter(team=asuggestion_team).exists)()


class TestScoutSuggestionsAPI(APIBaseTest):
    def test_list_before_first_generation_is_empty(self):
        response = self.client.get(f"/api/projects/{self.team.id}/signals/scout/suggestions/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(), {"status": "empty", "generated_at": None, "model": "", "fleet_snapshot": [], "items": []}
        )

    @parameterized.expand(
        [
            ("with_items", [_item()], SignalScoutSuggestionSet.Status.FRESH),
            ("nothing_to_suggest", [], SignalScoutSuggestionSet.Status.EMPTY),
        ]
    )
    def test_list_reports_an_aged_batch_as_stale(self, _name, items, stored_status):
        row = persist_suggestion_batch(self.team.id, items, task_run_id=None, model="m", fleet_snapshot=[])
        self.assertEqual(row.status, stored_status)
        SignalScoutSuggestionSet.all_teams.filter(pk=row.pk).update(generated_at=timezone.now() - timedelta(days=8))

        response = self.client.get(f"/api/projects/{self.team.id}/signals/scout/suggestions/")
        # Nothing writes STALE when a batch merely ages, so a fresh read has to derive it.
        self.assertEqual(response.json()["status"], "stale")

    def test_list_and_dismiss_round_trip(self):
        row = persist_suggestion_batch(
            self.team.id, [_item(), _custom()], task_run_id=None, model="m", fleet_snapshot=[]
        )
        suggestion_id = row.items[0]["id"]

        response = self.client.post(f"/api/projects/{self.team.id}/signals/scout/suggestions/{suggestion_id}/dismiss/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["skill_name"], "signals-scout-error-tracking")

        response = self.client.get(f"/api/projects/{self.team.id}/signals/scout/suggestions/")
        body = response.json()
        self.assertEqual(body["status"], "fresh")
        self.assertEqual([item["skill_name"] for item in body["items"]], ["signals-scout-checkout-drop"])
        self.assertEqual(
            body["items"][0]["proposed_config"], {"run_cron_schedule": None, "run_interval_minutes": None, "emit": True}
        )

        response = self.client.post(f"/api/projects/{self.team.id}/signals/scout/suggestions/nope/dismiss/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch("products.signals.backend.temporal.agentic.scout_suggestions.start_manual_scout_suggestions_run")
    def test_refresh_requires_ai_consent(self, mock_start):
        self.organization.is_ai_data_processing_approved = None
        self.organization.save()
        response = self.client.post(f"/api/projects/{self.team.id}/signals/scout/suggestions/refresh/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        mock_start.assert_not_called()

    def test_list_hides_a_suggestion_whose_scout_is_now_enabled(self):
        persist_suggestion_batch(self.team.id, [_item(), _custom()], task_run_id=None, model="m", fleet_snapshot=[])
        SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-error-tracking", enabled=True)

        body = self.client.get(f"/api/projects/{self.team.id}/signals/scout/suggestions/").json()
        self.assertEqual(body["status"], "stale")
        self.assertEqual([item["skill_name"] for item in body["items"]], ["signals-scout-checkout-drop"])

    def test_list_hides_a_custom_draft_whose_name_was_since_taken(self):
        persist_suggestion_batch(self.team.id, [_item(), _custom()], task_run_id=None, model="m", fleet_snapshot=[])
        # A disabled config now holds the draft's name, so Create would answer 409. The canonical
        # item keeps its disabled config visible — enabling it is exactly what that item offers.
        SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-checkout-drop", enabled=False)
        SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-error-tracking", enabled=False)

        body = self.client.get(f"/api/projects/{self.team.id}/signals/scout/suggestions/").json()
        self.assertEqual([item["skill_name"] for item in body["items"]], ["signals-scout-error-tracking"])

    @patch("products.signals.backend.scout_suggestions_api.sync_connect", return_value=MagicMock())
    @patch(
        "products.signals.backend.temporal.agentic.scout_suggestions.start_manual_scout_suggestions_run",
        return_value="wf-1",
    )
    @patch(
        "products.signals.backend.scout_suggestions_api.read_suggestion_settings",
        return_value=SuggestionSettings(enabled=True),
    )
    def test_refresh_dispatches_once_approved(self, _settings, mock_start, _connect):
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        response = self.client.post(f"/api/projects/{self.team.id}/signals/scout/suggestions/refresh/")
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(response.json(), {"workflow_id": "wf-1"})
        mock_start.assert_called_once()
        # The scan must act as the caller, not a resolved (possibly more privileged) member.
        self.assertEqual(mock_start.call_args.kwargs["acting_user_id"], self.user.pk)

    @patch("products.signals.backend.scout_suggestions_api.sync_connect", return_value=MagicMock())
    @patch("products.signals.backend.temporal.agentic.scout_suggestions.start_manual_scout_suggestions_run")
    @patch(
        "products.signals.backend.scout_suggestions_api.read_suggestion_settings",
        return_value=SuggestionSettings(enabled=True),
    )
    def test_refresh_conflicts_do_not_spend_the_daily_cap(self, _settings, mock_start, _connect):
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        mock_start.side_effect = [WorkflowAlreadyStartedError("wf", "run-scout-suggestions")] * 3 + ["wf-1"]
        url = f"/api/projects/{self.team.id}/signals/scout/suggestions/refresh/"
        for _ in range(3):
            self.assertEqual(self.client.post(url).status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(self.client.post(url).status_code, status.HTTP_202_ACCEPTED)

    @parameterized.expand(
        [
            ("flag_off", lambda team_id: SuggestionSettings(enabled=False)),
            ("blocklisted", lambda team_id: SuggestionSettings(enabled=True, team_blocklist=frozenset({team_id}))),
        ]
    )
    @patch("products.signals.backend.temporal.agentic.scout_suggestions.start_manual_scout_suggestions_run")
    def test_refresh_honors_the_kill_switch_and_blocklist(self, _name, settings_for, mock_start):
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        with patch(
            "products.signals.backend.scout_suggestions_api.read_suggestion_settings",
            return_value=settings_for(self.team.id),
        ):
            response = self.client.post(f"/api/projects/{self.team.id}/signals/scout/suggestions/refresh/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        mock_start.assert_not_called()


class TestScoutSuggestionsResourceLevelAccess(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        persist_suggestion_batch(self.team.id, [_item()], task_run_id=None, model="m", fleet_snapshot=[])
        config = SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-general", enabled=False)
        member = User.objects.create_and_join(self.organization, "scout-granted@posthog.com", "testtest")
        membership = OrganizationMembership.objects.get(user=member, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource="signal_scout",
            access_level="none",
            organization_member=membership,
        )
        # Editor on one scout clears has_any_specific_access_for_resource at both levels, so every
        # action below is turned away by requires_resource_level_access, not for a lesser reason.
        AccessControl.objects.create(
            team=self.team,
            resource="signal_scout",
            resource_id=str(config.id),
            access_level="editor",
            organization_member=membership,
        )
        self.client.force_login(member)

    @parameterized.expand([("list", "get", ""), ("dismiss", "post", "x/dismiss/"), ("refresh", "post", "refresh/")])
    def test_a_grant_on_one_scout_does_not_open_the_project_batch(self, _name, method, suffix):
        url = f"/api/projects/{self.team.id}/signals/scout/suggestions/{suffix}"
        response = self.client.get(url) if method == "get" else self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.content)

    @parameterized.expand([("list", "get", ""), ("dismiss", "post", "x/dismiss/"), ("refresh", "post", "refresh/")])
    def test_a_child_environment_grant_does_not_open_the_parent_batch(self, _name, method, suffix):
        # The batch is the parent project's row, so RBAC on the child environment's URL must
        # answer for the parent, where this member's `signal_scout` access is `none`.
        environment = Team.objects.create(
            organization=self.organization, project=self.team.project, parent_team=self.team, name="env"
        )
        membership = OrganizationMembership.objects.get(user__email="scout-granted@posthog.com")
        AccessControl.objects.create(
            team=environment, resource="signal_scout", access_level="editor", organization_member=membership
        )

        url = f"/api/projects/{environment.id}/signals/scout/suggestions/{suffix}"
        response = self.client.get(url) if method == "get" else self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.content)


class TestSuggestionScanGitHubPosture(BaseTest):
    @parameterized.expand(
        [
            ("suggestion_scan", Task.OriginProduct.SIGNALS_SCOUT_SUGGESTIONS, None),
            ("scout_run", Task.OriginProduct.SIGNALS_SCOUT, "posthog/posthog"),
        ]
    )
    def test_only_a_repo_less_suggestion_scan_gets_no_github_integration(self, _name, origin_product, expected_repo):
        # `github_read_access=False` downscopes nothing on its own: it selects the read-only branch
        # in credential refresh, so leaving the integration attached hands the scan the ordinary
        # write-capable token. The scan must carry no integration at all.
        Integration.objects.create(team=self.team, kind="github", config={}, sensitive_config={})

        task = Task.create_without_run(
            team=self.team,
            title="t",
            description="d",
            origin_product=origin_product,
            user_id=self.user.id,
            repository=expected_repo,
        )

        self.assertEqual(task.github_integration_id is None, expected_repo is None)

    def test_a_repo_less_suggestion_scan_never_resolves_a_personal_integration(self):
        # With no team integration, bot authorship falls back to the creator's personal GitHub
        # integration, and a repository-less lookup accepts any of them - so the resolution
        # itself must be bypassed, or the sandbox still gets a full personal token.
        with patch(
            "products.tasks.backend.temporal.process_task.utils.resolve_user_github_integration_for_task"
        ) as resolve:
            task = Task.create_without_run(
                team=self.team,
                title="t",
                description="d",
                origin_product=Task.OriginProduct.SIGNALS_SCOUT_SUGGESTIONS,
                user_id=self.user.id,
                repository=None,
            )

        resolve.assert_not_called()
        self.assertIsNone(task.github_user_integration_id)
