import json
from urllib.parse import parse_qs, urlparse

import pytest
from unittest.mock import patch

from django.core import signing

from posthog.models.integration import Integration

from products.mcp_store.backend.facade.contracts import UnconnectedTeamTool
from products.slack_app.backend.api import _handle_connect_tool_skip
from products.slack_app.backend.logic.connect_tool import (
    CONNECT_TOOL_SKIP_ACTION_ID,
    offer_tool_connections,
    read_connected_state,
)
from products.slack_app.backend.services.workspace_integrations import require_workspace_integration
from products.slack_app.backend.tests.conftest import SLACK_TEAM_ID, SLACK_USER_ID
from products.slack_app.backend.tests.helpers import action_ids

CONNECT_TOOL = "products.slack_app.backend.logic.connect_tool"
TEAM_TOOLS = [
    UnconnectedTeamTool(template_id="t-linear", name="Linear", connects_with_oauth=True),
    UnconnectedTeamTool(template_id="t-notion", name="Notion", connects_with_oauth=True),
    UnconnectedTeamTool(template_id="t-jira", name="Jira", connects_with_oauth=False),
]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "flag_on, text, offered_tools",
    [
        (True, "summarize the open Linear issues and the jira backlog", ["Linear"]),
        (True, "why did signups drop last week?", []),
        (False, "summarize the open Linear issues", []),
    ],
)
def test_offers_a_connect_link_only_for_named_tools_the_person_can_connect(
    flag_on: bool, text: str, offered_tools: list[str], org_team_user
) -> None:
    _, team, user = org_team_user
    row = Integration.objects.create(
        team=team, kind="slack", integration_id=SLACK_TEAM_ID, sensitive_config={"access_token": "xoxb-test"}
    )
    integration = require_workspace_integration(row.id, SLACK_TEAM_ID)

    with (
        patch(f"{CONNECT_TOOL}.is_slack_app_connect_tool_from_chat_enabled", return_value=flag_on),
        patch(f"{CONNECT_TOOL}.team_tools_not_connected", return_value=TEAM_TOOLS),
        patch(f"{CONNECT_TOOL}.capture_slack_event"),
        patch("posthog.models.integration.slack.WebClient") as web_client,
    ):
        offered = offer_tool_connections(
            integration,
            channel="C1",
            thread_ts="1.0",
            slack_user_id=SLACK_USER_ID,
            user_id=user.id,
            text=text,
            workflow_id="wf-1",
        )

    assert offered is bool(offered_tools)
    post = web_client.return_value.chat_postEphemeral
    if not offered_tools:
        post.assert_not_called()
        return
    blocks = post.call_args.kwargs["blocks"]
    buttons = blocks[1]["elements"]
    assert [button["text"]["text"] for button in buttons[:-1]] == [f"Connect {name}" for name in offered_tools]
    assert action_ids(blocks) == [CONNECT_TOOL_SKIP_ACTION_ID]
    connect = urlparse(buttons[0]["url"])
    assert connect.path == f"/api/projects/{team.id}/mcp_server_installations/authorize/"
    return_path = parse_qs(connect.query)["return_path"][0]
    state = read_connected_state(parse_qs(urlparse(return_path).query)["state"][0])
    assert state == {"workflow_id": "wf-1", "slack_team_id": SLACK_TEAM_ID, "channel": "C1"}


@pytest.mark.django_db
@pytest.mark.parametrize(
    "query, resumes, location",
    [
        ("oauth_complete=true", True, "https://slack.com/app_redirect?team=T1&channel=C1"),
        ("oauth_error=true", False, "https://slack.com/app_redirect?team=T1&channel=C1"),
        ("forged", False, "/"),
    ],
)
def test_the_connection_callback_resumes_only_a_connected_run(
    query: str, resumes: bool, location: str, client, org_team_user
) -> None:
    _, _, user = org_team_user
    client.force_login(user)
    state = signing.dumps(
        {"workflow_id": "wf-1", "slack_team_id": "T1", "channel": "C1"},
        salt="slack_app_connect_tool" if query != "forged" else "another_salt",
    )

    with patch("products.slack_app.backend.views.slack_tool_connected.resume_mention_workflow") as resume:
        response = client.get(f"/complete/slack-tool-connected/?state={state}&{query}")

    assert response.status_code == 302 and response["Location"] == location
    assert resume.called is resumes


def test_continue_without_the_tool_resumes_the_run_and_removes_the_offer() -> None:
    payload = {
        "response_url": "https://hooks.slack.example/response",
        "actions": [
            {
                "action_id": CONNECT_TOOL_SKIP_ACTION_ID,
                "value": json.dumps({"integration_id": 1, "workflow_id": "wf-1"}),
            }
        ],
    }

    with (
        patch("products.slack_app.backend.api.resume_mention_workflow") as resume,
        patch("products.slack_app.backend.api._delete_ephemeral_via_response_url") as delete,
    ):
        _handle_connect_tool_skip(payload)

    resume.assert_called_once_with("wf-1")
    delete.assert_called_once_with("https://hooks.slack.example/response")
