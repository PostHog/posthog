from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from posthog.models.user import User

from products.actions.backend.models.action import Action
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow


class TestHogFlow(TestCase):
    def setUp(self):
        super().setUp()
        org, team, user = User.objects.bootstrap("Test org", "ben@posthog.com", None)
        self.team = team
        self.user = user
        self.org = org

    @patch("products.workflows.backend.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_hog_flow_saved_receiver(self, mock_reload):
        hog_flow = HogFlow.objects.create(name="Test Flow", team=self.team)
        mock_reload.assert_called_once_with(team_id=self.team.id, hog_flow_ids=[str(hog_flow.id)])

    @patch("products.workflows.backend.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_draft_only_save_skips_worker_reload(self, mock_reload):
        hog_flow = HogFlow.objects.create(name="Test Flow", team=self.team)
        mock_reload.reset_mock()

        hog_flow.draft = {"name": "Draft name"}
        hog_flow.save(update_fields=["draft", "draft_updated_at"])
        mock_reload.assert_not_called()

        hog_flow.save(update_fields=["draft", "name"])
        mock_reload.assert_called_once_with(team_id=self.team.id, hog_flow_ids=[str(hog_flow.id)])

    @patch("products.workflows.backend.tasks.hog_flows.refresh_affected_hog_flows.delay")
    def test_action_saved_receiver(self, mock_refresh):
        action = Action.objects.create(team=self.team, name="Test Action")
        mock_refresh.assert_called_once_with(action_id=action.id)

    @patch("products.workflows.backend.tasks.hog_flows.refresh_affected_hog_flows.delay")
    def test_team_saved_receiver(self, mock_refresh):
        self.team.save()
        mock_refresh.assert_called_once_with(team_id=self.team.id)

    @patch("products.workflows.backend.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_backfill_conversion_filters_to_events_command(self, _mock_reload):
        # Event-based conversion stored in the wrong slot (the legacy shape we're fixing).
        event_obj = {
            "events": [{"id": "purchase", "name": "purchase", "type": "events", "order": 0}],
            "source": "events",
        }
        bad = HogFlow.objects.create(
            name="bad",
            team=self.team,
            conversion={"window_minutes": 60, "filters": event_obj, "bytecode": ["_H", 1, 29]},
        )
        # Correctly-shaped property conversion — must be left untouched.
        good_filters = [{"key": "plan", "type": "person", "value": ["growth"], "operator": "exact"}]
        good = HogFlow.objects.create(
            name="good",
            team=self.team,
            conversion={"window_minutes": 30, "filters": good_filters, "bytecode": ["_H", 1, 1]},
        )

        # Dry-run (the default) must not change anything.
        call_command("backfill_conversion_filters_to_events")
        bad.refresh_from_db()
        assert bad.conversion is not None and isinstance(bad.conversion["filters"], dict)

        # Live-run relocates the bad shape and leaves the good one untouched.
        call_command("backfill_conversion_filters_to_events", "--live-run")

        bad.refresh_from_db()
        bad_conversion = bad.conversion
        assert bad_conversion is not None
        assert bad_conversion["filters"] == []
        assert bad_conversion["bytecode"] == []
        assert bad_conversion["events"] == [{"filters": event_obj}]

        good.refresh_from_db()
        good_conversion = good.conversion
        assert good_conversion is not None
        assert good_conversion["filters"] == good_filters
        assert not good_conversion.get("events")

        # Idempotent: a second live-run must not double-move or change anything.
        call_command("backfill_conversion_filters_to_events", "--live-run")
        bad.refresh_from_db()
        bad_conversion = bad.conversion
        assert bad_conversion is not None
        assert bad_conversion["filters"] == []
        assert bad_conversion["events"] == [{"filters": event_obj}]

    @staticmethod
    def _email_action(action_id: str, from_value: dict) -> dict:
        return {
            "id": action_id,
            "type": "function_email",
            "config": {
                "template_id": "template-email",
                "inputs": {"email": {"value": {"from": from_value, "to": "a@b.com", "subject": "hi", "text": "hi"}}},
            },
        }

    @patch("products.workflows.backend.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_strip_placeholder_sender_dry_run_changes_nothing(self, _mock_reload):
        flow = HogFlow.objects.create(
            team=self.team,
            name="legacy",
            actions=[self._email_action("a1", {"integrationId": 1, "email": "default@example.com"})],
        )

        call_command("strip_placeholder_sender_overrides")

        flow.refresh_from_db()
        assert flow.actions[0]["config"]["inputs"]["email"]["value"]["from"]["email"] == "default@example.com"

    @patch(
        "products.workflows.backend.management.commands.strip_placeholder_sender_overrides.reload_hog_flows_on_workers"
    )
    @patch("products.workflows.backend.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_strip_placeholder_sender_live_run(self, _mock_model_reload, mock_command_reload):
        # The old sender picker wrote email: 'default@example.com' into from on every sender pick.
        # The live-run must remove exactly that key, everywhere it sits (live actions and the draft
        # blob), keep every other from key, and never touch an address a customer actually typed.
        placeholder_from = {
            "integrationId": 1,
            "integrationIds": [1, 2],
            "name": "Support",
            "email": "default@example.com",
        }
        custom_from = {"integrationId": 1, "email": "team@customer.com"}
        affected = HogFlow.objects.create(
            team=self.team,
            name="legacy",
            actions=[
                self._email_action("a1", dict(placeholder_from)),
                self._email_action("a2", dict(custom_from)),
            ],
            draft={"actions": [self._email_action("a1", dict(placeholder_from))]},
        )
        draft_only = HogFlow.objects.create(
            team=self.team,
            name="draft only",
            actions=[self._email_action("a1", dict(custom_from))],
            draft={"actions": [self._email_action("a1", dict(placeholder_from))]},
        )

        call_command("strip_placeholder_sender_overrides", "--live-run")

        affected.refresh_from_db()
        cleaned_from = affected.actions[0]["config"]["inputs"]["email"]["value"]["from"]
        assert cleaned_from == {"integrationId": 1, "integrationIds": [1, 2], "name": "Support"}
        assert affected.actions[1]["config"]["inputs"]["email"]["value"]["from"] == custom_from
        affected_draft = affected.draft
        assert affected_draft is not None
        assert affected_draft["actions"][0]["config"]["inputs"]["email"]["value"]["from"] == {
            "integrationId": 1,
            "integrationIds": [1, 2],
            "name": "Support",
        }

        draft_only.refresh_from_db()
        assert draft_only.actions[0]["config"]["inputs"]["email"]["value"]["from"] == custom_from
        draft_only_draft = draft_only.draft
        assert draft_only_draft is not None
        assert "email" not in draft_only_draft["actions"][0]["config"]["inputs"]["email"]["value"]["from"]

        # Workers cache the live flow config, so a flow whose live actions changed must be
        # reloaded; a draft-only change runs nothing and must not be.
        mock_command_reload.assert_called_once_with(team_id=self.team.id, hog_flow_ids=[str(affected.id)])

        # Idempotent: a second live-run finds nothing to strip.
        mock_command_reload.reset_mock()
        call_command("strip_placeholder_sender_overrides", "--live-run")
        mock_command_reload.assert_not_called()
