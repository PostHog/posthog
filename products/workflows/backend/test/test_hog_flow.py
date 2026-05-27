from unittest.mock import patch

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
