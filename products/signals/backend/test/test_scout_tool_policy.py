import dataclasses
from datetime import timedelta
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest import mock

from django.utils import timezone

from parameterized import parameterized

from posthog.mcp_tool_definitions import get_mcp_tool_definitions
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.permissions import SCOUT_TOOL_NOT_GRANTED_CODE

NOTE_CREATE = "POST /api/projects/{project_id}/conversations/tickets/{id}/notes/"
REPLY = "POST /api/projects/{project_id}/conversations/tickets/{id}/reply/"
EMIT_REPORT = "POST /api/projects/{project_id}/signals/scout/runs/{run_id}/emit-report/"
DASHBOARDS_LIST = "GET /api/projects/{project_id}/dashboards/"


def _definitions_with_operations() -> dict:
    operations = {
        "conversations-tickets-notes-create": (NOTE_CREATE,),
        "conversations-tickets-reply-create": (REPLY,),
        "scout-emit-report": (EMIT_REPORT,),
        "dashboards-get-all": (DASHBOARDS_LIST,),
    }
    return {
        name: dataclasses.replace(definition, operations=operations.get(name, definition.operations))
        for name, definition in get_mcp_tool_definitions().items()
    }


class TestScoutToolPolicy(APIBaseTest):
    def _client(self, *, sandbox_task_id):
        app = OAuthApplication.objects.create(
            name="Scout sandbox",
            client_id=f"scout-sandbox-{uuid4()}",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
            organization=self.organization,
            user=self.user,
        )
        token = OAuthAccessToken.objects.create(
            user=self.user,
            application=app,
            token=f"pha_scout_{uuid4().hex}",
            scope="ticket:write dashboard:read signal_scout_report:write",
            expires=timezone.now() + timedelta(hours=1),
            scoped_teams=[self.team.id],
            sandbox_task_id=sandbox_task_id,
        )
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")

    def _request(self, operation: str):
        ticket_id = uuid4()
        run_id = uuid4()
        path = {
            NOTE_CREATE: f"/api/projects/{self.team.id}/conversations/tickets/{ticket_id}/notes/",
            REPLY: f"/api/projects/{self.team.id}/conversations/tickets/{ticket_id}/reply/",
            EMIT_REPORT: f"/api/projects/{self.team.id}/signals/scout/runs/{run_id}/emit-report/",
            DASHBOARDS_LIST: f"/api/projects/{self.team.id}/dashboards/",
        }[operation]
        method = operation.split(" ", 1)[0].lower()
        return getattr(self.client, method)(path, {}, format="json")

    @parameterized.expand(
        [
            ("picked_note_tool_creates_note", ["conversations-tickets-notes-create"], True, NOTE_CREATE, False),
            ("picked_note_tool_refuses_reply", ["conversations-tickets-notes-create"], True, REPLY, True),
            (
                "picked_note_tool_refuses_dashboards",
                ["conversations-tickets-notes-create"],
                True,
                DASHBOARDS_LIST,
                True,
            ),
            ("run_context_tool_still_emits_report", ["conversations-tickets-notes-create"], True, EMIT_REPORT, False),
            ("malformed_list_fails_closed", [], True, NOTE_CREATE, True),
            ("null_list_keeps_access", None, True, REPLY, False),
            ("flag_off_keeps_access", ["conversations-tickets-notes-create"], False, REPLY, False),
        ]
    )
    def test_scout_tool_policy(self, _name, allowlist, flag_on, operation, refused):
        self._client(sandbox_task_id=uuid4())
        with (
            mock.patch(
                "products.signals.backend.facade.tool_access.tasks_facade.get_task_mcp_tool_allowlist",
                return_value=allowlist,
            ),
            mock.patch("products.signals.backend.facade.tool_access.scout_tool_access_enabled", return_value=flag_on),
            mock.patch(
                "products.signals.backend.scout_harness.tool_catalogue.get_mcp_tool_definitions",
                return_value=_definitions_with_operations(),
            ),
        ):
            response = self._request(operation)

        refused_by_policy = response.status_code == 403 and response.json().get("code") == SCOUT_TOOL_NOT_GRANTED_CODE
        assert refused_by_policy == refused, response.content

    def test_token_without_task_binding_keeps_access(self):
        self._client(sandbox_task_id=None)
        with mock.patch(
            "products.signals.backend.facade.tool_access.tasks_facade.get_task_mcp_tool_allowlist"
        ) as allowlist:
            response = self._request(REPLY)

        allowlist.assert_not_called()
        assert response.json().get("code") != SCOUT_TOOL_NOT_GRANTED_CODE
