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
