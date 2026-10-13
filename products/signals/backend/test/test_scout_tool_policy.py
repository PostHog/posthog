from datetime import timedelta
from typing import Any
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.mcp_tool_definitions import get_mcp_tool_definitions
from posthog.mcp_tool_operations import resolve_api_operation
from posthog.models.oauth import OAuthAccessToken, OAuthApplication

from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Channel, Status
from products.signals.backend.scout_harness.tool_catalogue import get_scout_tool_catalogue
from products.signals.backend.scout_harness.tool_policy import SANDBOX_HARNESS_OPERATIONS
from products.tasks.backend.models import Task

DISPATCH = "products.tasks.backend.logic.services.workflow_dispatch.enqueue_or_start_workflow"
NOTES_ONLY = ["conversations-tickets-notes-create"]
TOKEN_SCOPES = "ticket:read ticket:write notebook:read notebook:write task:read task:write project:read query:read"
# Hand-written tools whose handlers only read with GET, or make no API call, so they list no endpoint.
GET_ONLY_TOOLS = frozenset(
    {
        "agent-feedback",
        "debug-mcp-ui-apps",
        "experiment-get-by-flag-key",
        "external-data-sources-jobs",
        "external-data-sync-logs",
        "feature-flag-get-definition-by-key",
        "generate-app-url",
        "llma-parser-recipe-reference",
        "organizations-get",
        "projects-get",
        "switch-organization",
        "switch-project",
        "tasks-artifacts-list",
        "tasks-comments-list",
        "tasks-comments-retrieve",
    }
)


class TestScoutToolPolicyAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.team.conversations_enabled = True
        self.team.save(update_fields=["conversations_enabled"])
        self.ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="synthetic-session",
            distinct_id="synthetic-user",
            status=Status.NEW,
        )

    def _scout_client(self, *, allowlist: Any, bound: bool = True) -> Task:
        with patch(DISPATCH):
            task = Task.create_and_run(
                team=self.team,
                title="Synthetic scout run",
                description="Synthetic scout run",
                origin_product=Task.OriginProduct.SIGNALS_SCOUT,
                user_id=self.user.id,
                mcp_builtin_agent_key="scout",
                mcp_tool_allowlist=allowlist if isinstance(allowlist, list) else None,
            )
        if allowlist is not None and not isinstance(allowlist, list):
            task.state = {**(task.state or {}), "mcp_tool_allowlist": allowlist}
            task.save(update_fields=["state"])
        app = OAuthApplication.objects.create(
            name="Synthetic scout sandbox",
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
            token="pha_synthetic_scout",
            scope=TOKEN_SCOPES,
            expires=timezone.now() + timedelta(hours=1),
            scoped_teams=[self.team.id],
            sandbox_task_id=task.id if bound else None,
        )
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")
        return task

    @parameterized.expand(
        [
            ("picked_note", NOTES_ONLY, True, "post", "ticket_notes", status.HTTP_201_CREATED),
            ("unpicked_reply", NOTES_ONLY, True, "post", "ticket_reply", status.HTTP_403_FORBIDDEN),
            ("unpicked_ticket_update", NOTES_ONLY, True, "patch", "ticket", status.HTTP_403_FORBIDDEN),
            ("unpicked_fleet_write", NOTES_ONLY, True, "post", "notebooks", status.HTTP_403_FORBIDDEN),
            ("reads_stay_on_scopes", NOTES_ONLY, True, "get", "notebooks", status.HTTP_200_OK),
            # The action changes the project behind a read scope, so the method has to trigger the check.
            ("read_scoped_mutation", NOTES_ONLY, True, "patch", "complete_onboarding", status.HTTP_403_FORBIDDEN),
            ("unpicked_post_read", NOTES_ONLY, True, "post", "query", status.HTTP_403_FORBIDDEN),
            ("picked_post_read", ["insight-query"], True, "post", "query", status.HTTP_200_OK),
            ("mcp_store_tool_call", NOTES_ONLY, True, "post", "mcp_call_tool", status.HTTP_403_FORBIDDEN),
            ("mcp_store_tool_approval", NOTES_ONLY, True, "patch", "mcp_tool_approval", status.HTTP_403_FORBIDDEN),
            ("harness_write", [], True, "patch", "run_summary", status.HTTP_200_OK),
            ("malformed_stamp_fails_closed", "conversations-tickets-notes-create", True, "post", "ticket_notes", 403),
            ("not_narrowed", None, True, "post", "ticket_reply", status.HTTP_201_CREATED),
            ("unbound_token", NOTES_ONLY, False, "post", "ticket_reply", status.HTTP_201_CREATED),
        ]
    )
    def test_narrowed_scout_writes_only_through_picked_tools(
        self, _name: str, allowlist: Any, bound: bool, method: str, target: str, expected_status: int
    ) -> None:
        task = self._scout_client(allowlist=allowlist, bound=bound)
        base = f"/api/projects/{self.team.id}"
        run = task.latest_run
        assert run is not None
        url, body = {
            "ticket": (f"{base}/conversations/tickets/{self.ticket.id}/", {"status": Status.PENDING}),
            "ticket_notes": (f"{base}/conversations/tickets/{self.ticket.id}/notes/", {"message": "Synthetic note"}),
            "ticket_reply": (f"{base}/conversations/tickets/{self.ticket.id}/reply/", {"message": "Synthetic reply"}),
            "notebooks": (f"{base}/notebooks/", {"title": "Synthetic notebook"}),
            "run_summary": (f"{base}/tasks/{task.id}/runs/{run.id}/set_summary/", {"summary": "Synthetic summary"}),
            "complete_onboarding": (f"{base}/complete_product_onboarding/", {"type": "product_analytics"}),
            "query": (f"{base}/query/", {"query": {"kind": "HogQLQuery", "query": "select 1"}}),
            "mcp_call_tool": (f"{base}/mcp_server_installations/{uuid4()}/call_tool/", {"tool_name": "synthetic"}),
            "mcp_tool_approval": (
                f"{base}/mcp_server_installations/{uuid4()}/tools/synthetic/",
                {"approval_state": "approved"},
            ),
        }[target]

        with patch("products.conversations.backend.api.tickets.transaction.on_commit"):
            response = getattr(self.client, method)(url, body if method != "get" else None, format="json")

        assert response.status_code == expected_status, response.json()
        if expected_status == status.HTTP_403_FORBIDDEN:
            assert response.json()["code"] == "scout_tool_not_granted"


class TestScoutToolOperations(SimpleTestCase):
    def test_every_catalogued_and_harness_operation_resolves_to_a_view(self) -> None:
        operations = {
            (name, operation)
            for name, definition in get_mcp_tool_definitions().items()
            for operation in definition.api_operations
        } | {("sandbox harness", operation) for operation in SANDBOX_HARNESS_OPERATIONS}

        unresolved = sorted(
            f"{name}: {operation.method} {operation.path}"
            for name, operation in operations
            if resolve_api_operation(operation) is None
        )

        assert unresolved == []

    def test_every_holdable_tool_names_its_endpoints_unless_it_only_reads_with_get(self) -> None:
        holdable = {
            entry.definition.name: entry.definition for entry in get_scout_tool_catalogue().tools if entry.holdable
        }

        missing = sorted(name for name, definition in holdable.items() if not definition.api_operations)

        assert missing == sorted(GET_ONLY_TOOLS & holdable.keys())
