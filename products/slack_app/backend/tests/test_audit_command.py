import json
from typing import Any
from urllib.parse import urlencode

from unittest.mock import patch

from django.core import signing
from django.test import TestCase

from rest_framework.test import APIClient

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User

from products.slack_app.backend.audit_command import (
    AUDIT_CANCEL_ACTION_ID,
    AUDIT_CONFIRM_ACTION_ID,
    AUDIT_CONFIRM_TOKEN_SALT,
)
from products.slack_app.backend.tests.helpers import sign_slack_request

SLASH_COMMAND_URL = "/slack/slash-command/"
SIGNING_SECRET = "posthog-code-test-secret"
SLACK_TEAM_ID = "T_PHCODE"
SLACK_USER_ID = "U_STAFF"
DIFFERENT_SLACK_USER_ID = "U_OTHER"
CHANNEL_ID = "C_CUSTOMER"


class TestPostHogCodeSlashCommandHandler(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.organization = Organization.objects.create(name="Acme")
        self.team = Team.objects.create(organization=self.organization, name="Acme Production")
        self.staff_user = User.objects.create(email="staff@posthog.com", first_name="Staff", is_staff=True)
        self.non_staff_user = User.objects.create(email="customer@example.com", first_name="Customer", is_staff=False)
        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack-posthog-code",
            integration_id=SLACK_TEAM_ID,
            sensitive_config={"access_token": "xoxb-test"},
        )

    def _post(self, form: dict, secret: str = SIGNING_SECRET) -> Any:
        body = urlencode(form).encode()
        signature, ts = sign_slack_request(body, secret)
        return self.client.post(
            SLASH_COMMAND_URL,
            data=body,
            content_type="application/x-www-form-urlencoded",
            HTTP_X_SLACK_SIGNATURE=signature,
            HTTP_X_SLACK_REQUEST_TIMESTAMP=ts,
        )

    def _form(self, *, text: str, user_id: str = SLACK_USER_ID) -> dict:
        return {
            "command": "/ph-audit",
            "team_id": SLACK_TEAM_ID,
            "user_id": user_id,
            "channel_id": CHANNEL_ID,
            "text": text,
        }

    def test_method_not_allowed(self) -> None:
        response = self.client.get(SLASH_COMMAND_URL)
        assert response.status_code == 405

    @patch("products.slack_app.backend.audit_command.SlackIntegration.posthog_code_slack_config")
    def test_invalid_signature(self, mock_config) -> None:
        mock_config.return_value = {"SLACK_POSTHOG_CODE_SIGNING_SECRET": "wrong-secret"}
        response = self._post(self._form(text=f"{self.team.id} auditing-experiments-flags"))
        assert response.status_code == 403

    @patch("products.slack_app.backend.audit_command.SlackIntegration.posthog_code_slack_config")
    def test_unknown_command(self, mock_config) -> None:
        mock_config.return_value = {"SLACK_POSTHOG_CODE_SIGNING_SECRET": SIGNING_SECRET}
        response = self._post({**self._form(text=""), "command": "/unknown"})
        assert response.status_code == 200
        body = response.json()
        assert body["response_type"] == "ephemeral"
        assert "/unknown" in body["text"]

    @patch("products.slack_app.backend.audit_command.SlackIntegration.posthog_code_slack_config")
    def test_malformed_text(self, mock_config) -> None:
        mock_config.return_value = {"SLACK_POSTHOG_CODE_SIGNING_SECRET": SIGNING_SECRET}
        response = self._post(self._form(text="just-one-arg"))
        assert response.status_code == 200
        assert "Usage" in response.json()["text"]

    @patch("products.slack_app.backend.audit_command.SlackIntegration.posthog_code_slack_config")
    def test_non_integer_project_id(self, mock_config) -> None:
        mock_config.return_value = {"SLACK_POSTHOG_CODE_SIGNING_SECRET": SIGNING_SECRET}
        response = self._post(self._form(text="abc auditing-experiments-flags"))
        assert "isn't a valid project ID" in response.json()["text"]

    @patch("products.slack_app.backend.audit_command.SlackIntegration.posthog_code_slack_config")
    def test_skill_not_allowlisted(self, mock_config) -> None:
        mock_config.return_value = {"SLACK_POSTHOG_CODE_SIGNING_SECRET": SIGNING_SECRET}
        response = self._post(self._form(text=f"{self.team.id} write-everything-skill"))
        assert "isn't an allowed audit skill" in response.json()["text"]

    @patch("products.slack_app.backend.audit_command.SlackIntegration.posthog_code_slack_config")
    def test_no_integration_for_workspace(self, mock_config) -> None:
        mock_config.return_value = {"SLACK_POSTHOG_CODE_SIGNING_SECRET": SIGNING_SECRET}
        response = self._post({**self._form(text=f"{self.team.id} auditing-experiments-flags"), "team_id": "T_UNKNOWN"})
        assert "doesn't have a PostHog Code Slack integration" in response.json()["text"]

    @patch("products.slack_app.backend.audit_command._resolve_posthog_staff_user")
    @patch("products.slack_app.backend.audit_command.SlackIntegration.posthog_code_slack_config")
    def test_non_staff_user_rejected(self, mock_config, mock_resolve) -> None:
        mock_config.return_value = {"SLACK_POSTHOG_CODE_SIGNING_SECRET": SIGNING_SECRET}
        mock_resolve.return_value = None  # gate returns None for non-staff
        response = self._post(self._form(text=f"{self.team.id} auditing-experiments-flags"))
        assert "restricted to PostHog staff" in response.json()["text"]

    @patch("products.slack_app.backend.audit_command._resolve_posthog_staff_user")
    @patch("products.slack_app.backend.audit_command.SlackIntegration.posthog_code_slack_config")
    def test_project_not_found(self, mock_config, mock_resolve) -> None:
        mock_config.return_value = {"SLACK_POSTHOG_CODE_SIGNING_SECRET": SIGNING_SECRET}
        mock_resolve.return_value = self.staff_user
        response = self._post(self._form(text="999999999 auditing-experiments-flags"))
        assert "not found" in response.json()["text"]

    @patch("products.slack_app.backend.audit_command._resolve_posthog_staff_user")
    @patch("products.slack_app.backend.audit_command.SlackIntegration.posthog_code_slack_config")
    def test_happy_path_returns_confirm_blocks(self, mock_config, mock_resolve) -> None:
        mock_config.return_value = {"SLACK_POSTHOG_CODE_SIGNING_SECRET": SIGNING_SECRET}
        mock_resolve.return_value = self.staff_user
        response = self._post(self._form(text=f"{self.team.id} auditing-experiments-flags"))
        body = response.json()
        assert body["response_type"] == "ephemeral"
        blocks = body["blocks"]
        # section + actions
        assert len(blocks) == 2
        assert blocks[0]["type"] == "section"
        assert self.team.name in blocks[0]["text"]["text"]
        assert self.organization.name in blocks[0]["text"]["text"]
        assert self.staff_user.email in blocks[0]["text"]["text"]
        assert blocks[1]["type"] == "actions"
        action_ids = [el["action_id"] for el in blocks[1]["elements"]]
        assert AUDIT_CONFIRM_ACTION_ID in action_ids
        assert AUDIT_CANCEL_ACTION_ID in action_ids
        # The block_id needs to start with the audit prefix so the interactivity
        # handler's region gate can recover the integration_id.
        assert blocks[1]["block_id"].startswith(f"posthog_code_audit_actions:{self.integration.id}:")


class TestAuditConfirmHandler(TestCase):
    def setUp(self) -> None:
        self.organization = Organization.objects.create(name="Acme")
        self.team = Team.objects.create(organization=self.organization, name="Acme Production")
        self.staff_user = User.objects.create(email="staff@posthog.com", first_name="Staff", is_staff=True)

    def _make_token(self, **overrides) -> str:
        payload = {
            "integration_id": 42,
            "team_id": self.team.id,
            "skill": "auditing-experiments-flags",
            "staff_user_id": self.staff_user.id,
            "slack_user_id": SLACK_USER_ID,
            "channel": CHANNEL_ID,
            **overrides,
        }
        return signing.dumps(payload, salt=AUDIT_CONFIRM_TOKEN_SALT)

    def _confirm_payload(self, *, token: str, clicking_user: str = SLACK_USER_ID) -> dict:
        return {
            "type": "block_actions",
            "user": {"id": clicking_user},
            "actions": [
                {
                    "action_id": AUDIT_CONFIRM_ACTION_ID,
                    "block_id": f"posthog_code_audit_actions:42:{SLACK_USER_ID}",
                    "value": token,
                }
            ],
        }

    def test_confirm_writes_activity_log_and_returns_in_channel(self) -> None:
        from products.slack_app.backend.audit_command import handle_audit_confirm

        before = ActivityLog.objects.count()
        response = handle_audit_confirm(self._confirm_payload(token=self._make_token()))
        assert response.status_code == 200
        body = json.loads(response.content)
        assert body["response_type"] == "in_channel"
        assert body["replace_original"] is True
        assert self.team.name in body["text"]
        assert self.staff_user.email in body["text"]

        assert ActivityLog.objects.count() == before + 1
        entry = ActivityLog.objects.latest("created_at")
        assert entry.scope == "Team"
        assert entry.team_id == self.team.id
        assert entry.organization_id == self.organization.id
        assert entry.activity == "external_audit_started"
        assert entry.user_id == self.staff_user.id
        assert entry.was_impersonated is False
        assert entry.detail["type"] == "auditing-experiments-flags"

    def test_confirm_rejects_token_from_different_slack_user(self) -> None:
        from products.slack_app.backend.audit_command import handle_audit_confirm

        before = ActivityLog.objects.count()
        response = handle_audit_confirm(
            self._confirm_payload(token=self._make_token(), clicking_user=DIFFERENT_SLACK_USER_ID)
        )
        body = json.loads(response.content)
        assert "Only the staff member who ran the slash command" in body["text"]
        assert ActivityLog.objects.count() == before

    def test_confirm_rejects_tampered_token(self) -> None:
        from products.slack_app.backend.audit_command import handle_audit_confirm

        before = ActivityLog.objects.count()
        response = handle_audit_confirm(self._confirm_payload(token="not-a-real-token"))
        body = json.loads(response.content)
        assert "expired" in body["text"]
        assert ActivityLog.objects.count() == before

    def test_confirm_aborts_if_staff_user_lost_is_staff(self) -> None:
        from products.slack_app.backend.audit_command import handle_audit_confirm

        self.staff_user.is_staff = False
        self.staff_user.save(update_fields=["is_staff"])

        before = ActivityLog.objects.count()
        response = handle_audit_confirm(self._confirm_payload(token=self._make_token()))
        body = json.loads(response.content)
        assert "Couldn't resolve" in body["text"]
        assert ActivityLog.objects.count() == before


class TestAuditCancelHandler(TestCase):
    def test_cancel_returns_replace_original(self) -> None:
        from products.slack_app.backend.audit_command import handle_audit_cancel

        response = handle_audit_cancel({"type": "block_actions"})
        body = json.loads(response.content)
        assert body["replace_original"] is True
        assert body["text"] == "Audit cancelled."


class TestExtractAuditHints(TestCase):
    def test_returns_none_for_non_audit_action(self) -> None:
        from products.slack_app.backend.audit_command import extract_audit_hints

        assert extract_audit_hints({"actions": [{"action_id": "other"}]}) == (None, None)

    def test_extracts_integration_id_and_slack_user(self) -> None:
        from products.slack_app.backend.audit_command import extract_audit_hints

        result = extract_audit_hints(
            {
                "actions": [
                    {
                        "action_id": AUDIT_CONFIRM_ACTION_ID,
                        "block_id": "posthog_code_audit_actions:42:U_STAFF",
                    }
                ]
            }
        )
        assert result == (42, "U_STAFF")

    def test_rejects_block_id_with_wrong_prefix(self) -> None:
        from products.slack_app.backend.audit_command import extract_audit_hints

        assert extract_audit_hints(
            {
                "actions": [
                    {
                        "action_id": AUDIT_CONFIRM_ACTION_ID,
                        "block_id": "something_else:42:U_STAFF",
                    }
                ]
            }
        ) == (None, None)
