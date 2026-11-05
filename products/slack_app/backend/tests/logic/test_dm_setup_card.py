from collections.abc import Iterator

import pytest
from unittest.mock import MagicMock, patch

from posthog.models.integration import Integration

from products.slack_app.backend.logic.dm_setup.card import refresh_dm_setup_card, show_dm_setup_card
from products.slack_app.backend.services.slack_settings import DmSetupCardState, resolve_dm_setup_card
from products.slack_app.backend.services.workspace_integrations import (
    WorkspaceIntegration,
    require_workspace_integration,
)
from products.slack_app.backend.tests.conftest import SLACK_TEAM_ID, SLACK_USER_ID

CARD = "products.slack_app.backend.logic.dm_setup.card"
LINK_SCOPES = "chat:write,users:read,users:read.email"


def _install(team, scope: str = LINK_SCOPES) -> WorkspaceIntegration:
    row = Integration.objects.create(
        team=team,
        kind="slack",
        integration_id=SLACK_TEAM_ID,
        config={"scope": scope},
        sensitive_config={"access_token": "xoxb-test"},
    )
    return require_workspace_integration(row.id, SLACK_TEAM_ID)


def _block_text(blocks: list[dict]) -> str:
    texts = [block.get("text", {}).get("text", "") for block in blocks]
    texts += [element.get("text", "") for block in blocks for element in block.get("elements", [])]
    return "\n".join(text for text in texts if isinstance(text, str))


def _button_urls(blocks: list[dict]) -> list[str]:
    return [element["url"] for block in blocks for element in block.get("elements", []) if "url" in element]


@pytest.fixture
def slack_client() -> Iterator[MagicMock]:
    with patch("posthog.models.integration.slack.WebClient") as web_client:
        client = web_client.return_value
        client.chat_postMessage.return_value = {"channel": "D1", "ts": "111.1"}
        yield client


@pytest.fixture
def capture() -> Iterator[MagicMock]:
    with patch(f"{CARD}.capture_slack_event") as mock_capture:
        yield mock_capture


@pytest.mark.django_db
def test_first_open_posts_the_card_once_and_later_opens_render_it_again(
    org_team_user, slack_client: MagicMock, capture: MagicMock
) -> None:
    _, team, _ = org_team_user
    integration = _install(team)

    with patch(f"{CARD}.is_slack_app_dm_setup_card_enabled", return_value=True):
        show_dm_setup_card(integration, SLACK_USER_ID)
        show_dm_setup_card(integration, SLACK_USER_ID)

    slack_client.chat_postMessage.assert_called_once()
    posted = slack_client.chat_postMessage.call_args.kwargs
    assert posted["channel"] == SLACK_USER_ID
    assert "Link your PostHog account" in _block_text(posted["blocks"])
    assert "/complete/slack-link/start/?state=" in _button_urls(posted["blocks"])[0]
    updated = slack_client.chat_update.call_args.kwargs
    assert (updated["channel"], updated["ts"]) == ("D1", "111.1")
    assert "/complete/slack-link/start/?state=" in _button_urls(updated["blocks"])[0]
    assert resolve_dm_setup_card(SLACK_TEAM_ID, SLACK_USER_ID) == DmSetupCardState(
        channel="D1", ts="111.1", completed=False
    )
    capture.assert_called_once_with(
        integration,
        "slack app dm setup card shown",
        slack_user_id=SLACK_USER_ID,
        pending_steps=["link_account"],
        step_count=1,
    )


@pytest.mark.django_db
@pytest.mark.parametrize("case", ["flag_off", "already_linked", "install_cannot_link"])
def test_no_card_when_there_is_nothing_to_set_up(
    case: str, org_team_user, link_user, slack_client: MagicMock, capture: MagicMock
) -> None:
    _, team, user = org_team_user
    integration = _install(team, scope="chat:write" if case == "install_cannot_link" else LINK_SCOPES)
    if case == "already_linked":
        link_user(user)

    with patch(f"{CARD}.is_slack_app_dm_setup_card_enabled", return_value=case != "flag_off"):
        show_dm_setup_card(integration, SLACK_USER_ID)

    slack_client.chat_postMessage.assert_not_called()
    assert resolve_dm_setup_card(SLACK_TEAM_ID, SLACK_USER_ID) is None
    capture.assert_not_called()


@pytest.mark.django_db
def test_linking_turns_the_card_into_ready_once(
    org_team_user, link_user, slack_client: MagicMock, capture: MagicMock
) -> None:
    _, team, user = org_team_user
    integration = _install(team)
    with patch(f"{CARD}.is_slack_app_dm_setup_card_enabled", return_value=True):
        show_dm_setup_card(integration, SLACK_USER_ID)
    capture.reset_mock()

    link_user(user)
    refresh_dm_setup_card(integration, SLACK_USER_ID)
    refresh_dm_setup_card(integration, SLACK_USER_ID)

    slack_client.chat_update.assert_called_once()
    ready_text = _block_text(slack_client.chat_update.call_args.kwargs["blocks"])
    assert "PostHog account linked" in ready_text
    assert "You're all set" in ready_text
    assert _button_urls(slack_client.chat_update.call_args.kwargs["blocks"]) == []
    assert resolve_dm_setup_card(SLACK_TEAM_ID, SLACK_USER_ID) == DmSetupCardState(
        channel="D1", ts="111.1", completed=True
    )
    capture.assert_called_once_with(
        integration, "slack app dm setup completed", slack_user_id=SLACK_USER_ID, step_count=1
    )
