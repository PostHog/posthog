import json
from typing import Any

from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.test.client import RequestFactory
from django.utils import timezone

from parameterized import parameterized
from rest_framework.test import APIClient

from posthog.models.integration import Integration
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User

from products.slack_app.backend.api import ROUTE_HANDLED_LOCALLY, SLACK_MENTION_DROPPED_EVENT
from products.slack_app.backend.models import SlackSettings, SlackUserProfileCache
from products.slack_app.backend.services.project_picker import PICKER_EXPIRED_MESSAGE
from products.slack_app.backend.services.slack_auth import write_auth_state_ok
from products.slack_app.backend.services.slack_scopes import REQUIRED_SLACK_SCOPES
from products.slack_app.backend.tests.helpers import sign_slack_request

WORKSPACE = "T12345"
MENTIONER = "U123"
SIGNING_SECRET = "posthog-code-test-secret"
RESPONSE_URL = "https://hooks.slack.example/response/abc"


class TestProjectPickerFlow(TestCase):
    def setUp(self):
        cache.clear()
        self.enterContext(patch("products.slack_app.backend.api.does_other_region_claim_workspace", return_value=False))
        self.enterContext(
            patch(
                "products.slack_app.backend.api.SlackIntegration.slack_config",
                return_value={"SLACK_APP_SIGNING_SECRET": SIGNING_SECRET},
            )
        )
        self.mock_start = self.enterContext(
            patch("products.slack_app.backend.api._start_mention_workflow", return_value=ROUTE_HANDLED_LOCALLY)
        )
        self.mock_response_url = self.enterContext(
            patch("products.slack_app.backend.services.inbox_interactivity.requests.post")
        )

        self.organization = Organization.objects.create(name="Acme")
        self.user = User.objects.create(email="dev@example.com", distinct_id="user-1")
        self.membership = OrganizationMembership.objects.create(organization=self.organization, user=self.user)
        self.production = self._connect_project("Production")
        self.staging = self._connect_project("Staging")
        self.event = {
            "type": "app_mention",
            "channel": "C001",
            "user": MENTIONER,
            "ts": "1234.5678",
            "text": "<@U0BOT> how many signups last week",
        }

    def _connect_project(self, name: str) -> Integration:
        team = Team.objects.create(organization=self.organization, name=name)
        integration = Integration.objects.create(
            team=team,
            kind="slack",
            integration_id=WORKSPACE,
            config={"scope": ",".join(sorted(REQUIRED_SLACK_SCOPES))},
            sensitive_config={"access_token": "xoxb-test"},
        )
        write_auth_state_ok(integration.id, bot_user_id="U0BOT")
        SlackUserProfileCache.objects.create(
            integration=integration,
            slack_user_id=MENTIONER,
            email="dev@example.com",
            display_name="Dev",
            real_name="Dev User",
            refreshed_at=timezone.now(),
        )
        return integration

    @override_settings(DEBUG=False, CLOUD_DEPLOYMENT="US")
    def _mention(
        self, *, picker_enabled: bool = True, post_fails: bool = False, is_ext_shared_channel: bool = False
    ) -> dict[str, Any]:
        from products.slack_app.backend.api import route_posthog_code_event_to_relevant_region

        request = RequestFactory().post("/slack/event-callback/", HTTP_HOST="us.posthog.com")
        with (
            patch("products.slack_app.backend.api.is_slack_app_project_picker_enabled", return_value=picker_enabled),
            patch(
                "products.slack_app.backend.api.post_slack_ephemeral",
                side_effect=RuntimeError("slack is down") if post_fails else None,
            ) as mock_picker,
            patch("products.slack_app.backend.api._post_slack_user_feedback", return_value=True) as mock_hint,
            patch("products.slack_app.backend.api.posthoganalytics.capture") as mock_capture,
        ):
            route_posthog_code_event_to_relevant_region(
                request, self.event, WORKSPACE, "Ev001", is_ext_shared_channel=is_ext_shared_channel
            )
        drops = [
            call.kwargs["properties"]
            for call in mock_capture.call_args_list
            if call.kwargs["event"] == SLACK_MENTION_DROPPED_EVENT
        ]
        return {
            "blocks": mock_picker.call_args.kwargs["blocks"] if mock_picker.called else None,
            "hint_posted": mock_hint.called,
            "drop": drops[0],
        }

    @override_settings(DEBUG=True)
    def _click(self, blocks: list[dict], *, project: Integration, slack_user_id: str = MENTIONER) -> None:
        actions_block = next(block for block in blocks if block["type"] == "actions")
        element = next(
            element
            for element in actions_block["elements"]
            if json.loads(element["value"])["integration_id"] == project.id
        )
        payload = {
            "type": "block_actions",
            "team": {"id": WORKSPACE},
            "user": {"id": slack_user_id},
            "response_url": RESPONSE_URL,
            "actions": [
                {"action_id": element["action_id"], "block_id": actions_block["block_id"], "value": element["value"]}
            ],
        }
        body = f"payload={json.dumps(payload)}"
        signed = sign_slack_request(body.encode(), SIGNING_SECRET)
        response = APIClient().post(
            "/slack/interactivity-callback/",
            data=body,
            content_type="application/x-www-form-urlencoded",
            headers={"x-slack-signature": signed.signature, "x-slack-request-timestamp": signed.timestamp},
        )
        assert response.status_code == 200

    def _saved_default(self) -> Integration | None:
        row = SlackSettings.objects.filter(slack_workspace_id=WORKSPACE, slack_user_id=MENTIONER).first()
        return row.default_integration if row else None

    @parameterized.expand(
        [
            ("picker_on", True, False, True),
            ("picker_off", False, False, False),
            ("picker_fails_to_post", True, True, False),
        ]
    )
    def test_mention_with_several_projects_gets_the_picker_or_the_hint(
        self, _name, picker_enabled, post_fails, expect_picker
    ):
        outcome = self._mention(picker_enabled=picker_enabled, post_fails=post_fails)

        assert outcome["hint_posted"] is not expect_picker
        assert outcome["drop"]["drop_reason"] == "multiple_projects"
        assert outcome["drop"]["picker_shown"] is expect_picker
        assert outcome["drop"]["replied"] is True
        self.mock_start.assert_not_called()

    def test_pick_runs_the_original_mention_and_saves_the_default(self):
        blocks = self._mention()["blocks"]

        self._click(blocks, project=self.staging)

        self.mock_start.assert_called_once()
        started = self.mock_start.call_args
        assert started.args[0] == self.event
        assert started.args[1].id == self.staging.id
        assert started.args[3] == "Ev001"
        assert self._saved_default() == self.staging
        assert "Acme · Staging" in self.mock_response_url.call_args.kwargs["json"]["text"]

    @parameterized.expand(
        [
            ("click_by_someone_else", "U_OTHER", False),
            ("access_removed_before_the_click", MENTIONER, True),
        ]
    )
    def test_rejected_pick_starts_nothing_and_saves_nothing(self, _name, clicker, remove_access):
        blocks = self._mention()["blocks"]
        if remove_access:
            self.membership.delete()

        self._click(blocks, project=self.staging, slack_user_id=clicker)

        self.mock_start.assert_not_called()
        assert self._saved_default() is None

    def test_second_click_does_not_start_a_second_run(self):
        blocks = self._mention()["blocks"]

        self._click(blocks, project=self.staging)
        self._click(blocks, project=self.production)

        self.mock_start.assert_called_once()
        assert self._saved_default() == self.staging

    def test_pick_in_an_unapproved_shared_channel_starts_nothing(self):
        blocks = self._mention(is_ext_shared_channel=True)["blocks"]

        with patch(
            "products.slack_app.backend.api._post_channel_approval_prompt", return_value=True
        ) as mock_approval_prompt:
            self._click(blocks, project=self.staging)

        mock_approval_prompt.assert_called_once()
        self.mock_start.assert_not_called()

    def test_click_after_the_picker_expired_tells_the_person(self):
        blocks = self._mention()["blocks"]
        cache.clear()

        self._click(blocks, project=self.staging)

        self.mock_start.assert_not_called()
        assert self.mock_response_url.call_args.kwargs["json"]["text"] == PICKER_EXPIRED_MESSAGE
