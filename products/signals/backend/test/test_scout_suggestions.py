import random
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

from posthog.models import Organization, Team
from posthog.models.scoping import team_scope
from posthog.sync import database_sync_to_async

from products.signals.backend.models import SignalScoutConfig, SignalScoutSuggestionSet
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
            ("bad_cron", _item(proposed_config={"run_cron_schedule": "every tuesday"})),
            ("interval_below_floor", _item(proposed_config={"run_interval_minutes": 5})),
            ("blank_title", _item(title="  ")),
        ]
    )
    def test_drops_items_create_could_not_apply(self, _name, item):
        kept = validate_suggestion_items(
            [item], enabled_skill_names={"signals-scout-general"}, canonical_names=CANONICAL
        )
        self.assertEqual(kept, [])

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

    def test_cap_allowlist_blocklist_and_breaker(self):
        self._enable_scout(self.team, engaged=True)
        second = self._team("second")
        self._enable_scout(second, engaged=True)
        broken = self._team("broken")
        self._enable_scout(broken, engaged=True)
        SignalScoutSuggestionSet.all_teams.create(
            team=broken, last_requested_at=self.now - timedelta(days=30), consecutive_failures=3
        )
        outsider = self._team("outsider")

        planned = plan_suggestion_runs(
            SuggestionSettings(
                enabled=True,
                max_children_per_tick=2,
                team_allowlist=frozenset({outsider.id}),
                team_blocklist=frozenset({second.id}),
            ),
            self.now,
        )
        self.assertEqual([run.team_id for run in planned], [outsider.id, self.team.id])


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
    with (
        patch(
            f"{_RUNNER}.MultiTurnSession.start", new_callable=AsyncMock, return_value=(_fake_session(), batch)
        ) as start,
        patch(f"{_RUNNER}.get_or_create_signals_sandbox_env", return_value="env"),
        patch(f"{_RUNNER}.resolve_acting_user_id_for_team", return_value=42),
        patch("products.signals.backend.scout_harness.suggestions.discover_canonical_skills", return_value=()),
    ):
        result = await arun_scout_suggestions(asuggestion_team.id)

    assert (result.status, result.suggestion_count) == ("completed", 1)
    row = await database_sync_to_async(SignalScoutSuggestionSet.all_teams.get)(team=asuggestion_team)
    assert [record["skill_name"] for record in visible_items(row)] == ["signals-scout-checkout-drop"]
    assert str(row.task_run_id) == "11111111-1111-1111-1111-111111111111"
    assert start.call_args.kwargs["context"].posthog_mcp_scopes == "read_only"
    assert start.call_args.kwargs["fallback_from_text"] is None


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_runner_unparseable_close_out_is_a_failed_generation(asuggestion_team):
    with (
        patch(f"{_RUNNER}.MultiTurnSession.start", new_callable=AsyncMock, side_effect=ValueError("no json")),
        patch(f"{_RUNNER}.get_or_create_signals_sandbox_env", return_value="env"),
        patch(f"{_RUNNER}.resolve_acting_user_id_for_team", return_value=42),
        patch("products.signals.backend.scout_harness.suggestions.discover_canonical_skills", return_value=()),
    ):
        result = await arun_scout_suggestions(asuggestion_team.id)

    assert result.status == "failed"
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

    def test_list_and_dismiss_round_trip(self):
        row = persist_suggestion_batch(
            self.team.id, [_item(), _custom()], task_run_id=None, model="m", fleet_snapshot=["signals-scout-general"]
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

    @patch("products.signals.backend.scout_suggestions_api.sync_connect", return_value=MagicMock())
    @patch(
        "products.signals.backend.temporal.agentic.scout_suggestions.start_manual_scout_suggestions_run",
        return_value="wf-1",
    )
    def test_refresh_dispatches_once_approved(self, mock_start, _connect):
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        response = self.client.post(f"/api/projects/{self.team.id}/signals/scout/suggestions/refresh/")
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(response.json(), {"workflow_id": "wf-1"})
        mock_start.assert_called_once()
