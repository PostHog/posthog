"""Tests for the App Home tab (project routing + OAuth account linking).

Block Kit renderer tests run as pure functions on dicts; handler tests
exercise the real Django flow with the Slack API client mocked out.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team

from products.slack_app.backend.models import SlackSettings
from products.slack_app.backend.services.slack_app_home import (
    ACTION_RESET_PROJECT_PERSONAL,
    ACTION_SET_PROJECT_PERSONAL,
    ACTION_SET_PROJECT_WORKSPACE,
    ACTION_UNLINK_ACCOUNT,
    AccountState,
    ProjectChoice,
    ProjectState,
    handle_app_home_opened,
    handle_home_block_action,
    render_home_view,
)

SLACK_WORKSPACE_ID = "T_HOME"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def slack_integration(db):
    organization = Organization.objects.create(name="Org")
    team = Team.objects.create(organization=organization, name="Team")
    return Integration.objects.create(
        team=team,
        kind="slack",
        integration_id=SLACK_WORKSPACE_ID,
        sensitive_config={"access_token": "xoxb"},
    )


@pytest.fixture
def mock_slack_client():
    fake_client = MagicMock()
    with patch("products.slack_app.backend.services.slack_app_home.SlackIntegration") as cls:
        instance = MagicMock()
        instance.client = fake_client
        cls.return_value = instance
        yield fake_client


@pytest.fixture
def flag_on():
    with patch(
        "products.slack_app.backend.feature_flags.posthoganalytics.feature_enabled",
        return_value=True,
    ):
        yield


@pytest.fixture
def admin_user():
    with patch(
        "products.slack_app.backend.services.slack_app_home.is_slack_workspace_admin",
        return_value=True,
    ):
        yield


@pytest.fixture
def non_admin_user():
    with patch(
        "products.slack_app.backend.services.slack_app_home.is_slack_workspace_admin",
        return_value=False,
    ):
        yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _action_ids(view: dict) -> list[str]:
    out: list[str] = []
    for block in view["blocks"]:
        for el in block.get("elements", []) or []:
            if "action_id" in el:
                out.append(el["action_id"])
    return out


def _all_text(view: dict) -> str:
    out: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            if "text" in node and isinstance(node["text"], str):
                out.append(node["text"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(view)
    return " ".join(out)


def _block_action_payload(*, action_id: str, slack_user_id: str, channel: str | None = None) -> dict:
    return {
        "type": "block_actions",
        "team": {"id": SLACK_WORKSPACE_ID},
        "user": {"id": slack_user_id},
        "channel": {"id": channel} if channel else None,
        "actions": [{"action_id": action_id}],
    }


# ---------------------------------------------------------------------------
# Renderer tests
# ---------------------------------------------------------------------------


class TestRenderHomeView:
    def test_renders_home_type(self):
        view = render_home_view(is_admin=False)
        assert view["type"] == "home"

    def test_hides_project_section_when_no_candidates_and_no_default(self):
        view = render_home_view(is_admin=False, project_state=ProjectState())
        assert "Project routing" not in _all_text(view)

    def test_shows_personal_picker_when_candidates_present(self):
        state = ProjectState(
            candidates=(ProjectChoice(team_id=1, label="Org · A"), ProjectChoice(team_id=2, label="Org · B")),
        )
        view = render_home_view(is_admin=False, project_state=state)
        assert ACTION_SET_PROJECT_PERSONAL in _action_ids(view)
        assert "Project routing" in _all_text(view)

    def test_personal_pick_renders_reset_button(self):
        state = ProjectState(
            candidates=(ProjectChoice(team_id=1, label="Org · A"), ProjectChoice(team_id=2, label="Org · B")),
            personal_team_id=1,
        )
        view = render_home_view(is_admin=False, project_state=state)
        assert ACTION_RESET_PROJECT_PERSONAL in _action_ids(view)

    def test_workspace_default_shows_to_non_admin_as_read_only(self):
        # Non-admin doesn't get the workspace picker but sees what's set.
        state = ProjectState(
            candidates=(ProjectChoice(team_id=1, label="Org · A"),),
            workspace_team_id=1,
            workspace_team_label="Org · A",
        )
        view = render_home_view(is_admin=False, project_state=state)
        assert ACTION_SET_PROJECT_WORKSPACE not in _action_ids(view)
        assert "Workspace default" in _all_text(view)
        assert "Org · A" in _all_text(view)

    def test_admin_sees_workspace_picker(self):
        state = ProjectState(
            candidates=(ProjectChoice(team_id=1, label="Org · A"), ProjectChoice(team_id=2, label="Org · B")),
        )
        view = render_home_view(is_admin=True, project_state=state)
        assert ACTION_SET_PROJECT_WORKSPACE in _action_ids(view)

    def test_admin_no_access_footnote_when_default_is_inaccessible(self):
        # workspace_team_id is set but not in candidates → admin sees footnote.
        state = ProjectState(
            candidates=(ProjectChoice(team_id=1, label="Org · A"),),
            workspace_team_id=42,
            workspace_team_label="Other Org · Secret",
        )
        view = render_home_view(is_admin=True, project_state=state)
        assert "no access" in _all_text(view)
        assert "Other Org · Secret" in _all_text(view)

    def test_account_section_hidden_when_disabled(self):
        view = render_home_view(is_admin=False, account_state=AccountState(enabled=False))
        assert "Linked PostHog account" not in _all_text(view)
        assert "Connect to PostHog" not in _all_text(view)

    def test_account_section_linked_shows_email_and_disconnect(self):
        view = render_home_view(
            is_admin=False,
            account_state=AccountState(enabled=True, linked_email="user@example.com"),
        )
        assert "user@example.com" in _all_text(view)
        assert ACTION_UNLINK_ACCOUNT in _action_ids(view)

    def test_account_section_unlinked_shows_connect_button(self):
        view = render_home_view(
            is_admin=False,
            account_state=AccountState(enabled=True, linked_email=None, link_url="https://example/auth"),
        )
        assert "Connect to PostHog" in _all_text(view)


# ---------------------------------------------------------------------------
# Handler tests — app_home_opened event
# ---------------------------------------------------------------------------


class TestHandleAppHomeOpened:
    def test_publishes_view_for_known_user(self, slack_integration, mock_slack_client, flag_on, admin_user):
        handle_app_home_opened({"user": "U001"}, SLACK_WORKSPACE_ID)
        assert mock_slack_client.views_publish.called
        kwargs = mock_slack_client.views_publish.call_args.kwargs
        assert kwargs["user_id"] == "U001"
        assert kwargs["view"]["type"] == "home"

    def test_noop_when_user_missing(self, slack_integration, mock_slack_client, flag_on):
        handle_app_home_opened({}, SLACK_WORKSPACE_ID)
        assert not mock_slack_client.views_publish.called

    def test_noop_when_integration_missing(self, db, mock_slack_client, flag_on):
        handle_app_home_opened({"user": "U001"}, "T_UNKNOWN")
        assert not mock_slack_client.views_publish.called


# ---------------------------------------------------------------------------
# Handler tests — block_actions
# ---------------------------------------------------------------------------


class TestResetProjectPersonal:
    def test_drops_row_when_reset(self, slack_integration, mock_slack_client, flag_on, admin_user):
        SlackSettings.objects.create(
            default_integration=slack_integration,
            slack_workspace_id=SLACK_WORKSPACE_ID,
            slack_user_id="U002",
        )
        payload = _block_action_payload(action_id=ACTION_RESET_PROJECT_PERSONAL, slack_user_id="U002")
        handle_home_block_action(payload, payload["actions"][0])

        assert not SlackSettings.objects.filter(slack_workspace_id=SLACK_WORKSPACE_ID, slack_user_id="U002").exists()
        assert mock_slack_client.views_publish.called

    def test_no_row_is_a_noop(self, slack_integration, mock_slack_client, flag_on, admin_user):
        payload = _block_action_payload(action_id=ACTION_RESET_PROJECT_PERSONAL, slack_user_id="U003")
        handle_home_block_action(payload, payload["actions"][0])
        # Nothing to clear — still republish so the view stays in sync.
        assert mock_slack_client.views_publish.called


class TestSetWorkspaceProjectAdminGate:
    def test_non_admin_blocked(self, slack_integration, mock_slack_client, flag_on, non_admin_user):
        payload = _block_action_payload(
            action_id=ACTION_SET_PROJECT_WORKSPACE,
            slack_user_id="U_NONADMIN",
            channel="C1",
        )
        # Payload doesn't pick a team, but the admin gate should short-circuit first.
        handle_home_block_action(payload, payload["actions"][0])
        assert not SlackSettings.objects.filter(slack_user_id__isnull=True).exists()
        # Non-admin notice goes via ephemeral or DM.
        assert mock_slack_client.chat_postEphemeral.called or mock_slack_client.chat_postMessage.called
