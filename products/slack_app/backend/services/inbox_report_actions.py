"""Click handlers for the "I'm on it" and "Copy prompt" buttons of an inbox report notification."""

from __future__ import annotations

from typing import Literal

from django.http import HttpResponse

import structlog

from posthog.dataclasses import frozen
from posthog.models.user import User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.slack_app.backend.analytics import capture_slack_event
from products.slack_app.backend.logic.inbox_report_buttons import REPORT_CLAIM_ACTION_ID, report_action_integration_hint
from products.slack_app.backend.services.inbox_interactivity import post_response_url
from products.slack_app.backend.services.workspace_integrations import WorkspaceIntegration, get_workspace_integration

logger = structlog.get_logger(__name__)

_ReportAction = Literal["claim", "copy_prompt"]

_NO_PROJECT_ACCESS = (
    "Only members of this PostHog project can use this button. Ask a project admin to add you to the project."
)
_NO_TASK_EDITOR_ACCESS = "You need task editor access to claim this report. Ask a project admin for access."
_REPORT_NOT_LINKED = "This report is no longer linked to this Slack message. Open it in PostHog instead."
_NOT_CLAIMABLE = "This report is closed, so you cannot claim it. Open it in PostHog to see its status."
_COPY_PROMPT_INTRO = "Paste this prompt into your coding agent to work on the report."


@frozen
class _ReportActionClick:
    integration: WorkspaceIntegration
    posthog_user: User
    slack_user_id: str
    report_id: str
    response_url: str


def _post_private_note(response_url: str, text: str) -> None:
    post_response_url(response_url, {"response_type": "ephemeral", "replace_original": False, "text": text})


def _authorized_click(payload: dict, action: _ReportAction) -> _ReportActionClick | None:
    """Resolve the click to a project member and the report of the message, or tell the person why not."""
    from products.signals.backend.facade.api import (  # noqa: PLC0415 - keeps the signals model graph off the webhook import path
        report_id_for_slack_thread,
    )
    from products.slack_app.backend.api import (  # noqa: PLC0415 - api.py imports this module
        _can_access_team,
        _is_org_member,
    )

    integration_id = report_action_integration_hint(payload)
    slack_team_id = payload.get("team", {}).get("id", "")
    slack_user_id = payload.get("user", {}).get("id", "")
    response_url = payload.get("response_url", "")
    if not (integration_id and slack_team_id and slack_user_id):
        return None
    integration = get_workspace_integration(integration_id, slack_team_id)
    if integration is None:
        return None

    def refuse(outcome: str, text: str, posthog_user: User | None = None) -> None:
        capture_slack_event(
            integration,
            "slack app inbox report action clicked",
            slack_user_id=slack_user_id,
            posthog_user=posthog_user,
            action=action,
            outcome=outcome,
        )
        _post_private_note(response_url, text)

    # Anyone in the channel sees the buttons, so the click must clear the bar the web inbox sets.
    posthog_user = _is_org_member(integration, slack_user_id)
    if posthog_user is None or not _can_access_team(posthog_user, integration):
        refuse("no_project_access", _NO_PROJECT_ACCESS)
        return None
    if action == "claim" and not UserAccessControl(posthog_user, team=integration.team).check_access_level_for_resource(
        "task", "editor"
    ):
        refuse("no_task_editor_access", _NO_TASK_EDITOR_ACCESS, posthog_user)
        return None

    container = payload.get("container") or {}
    message = payload.get("message") or {}
    channel = container.get("channel_id") or (payload.get("channel") or {}).get("id")
    message_ts = container.get("message_ts") or message.get("ts")
    report_id = (
        report_id_for_slack_thread(
            team_id=integration.team_id, slack_workspace_id=slack_team_id, channel=channel, thread_ts=message_ts
        )
        if isinstance(channel, str) and isinstance(message_ts, str)
        else None
    )
    if report_id is None:
        refuse("report_not_linked", _REPORT_NOT_LINKED, posthog_user)
        return None
    return _ReportActionClick(
        integration=integration,
        posthog_user=posthog_user,
        slack_user_id=slack_user_id,
        report_id=report_id,
        response_url=response_url,
    )


def _capture_click(click: _ReportActionClick, action: _ReportAction, outcome: str) -> None:
    capture_slack_event(
        click.integration,
        "slack app inbox report action clicked",
        slack_user_id=click.slack_user_id,
        posthog_user=click.posthog_user,
        action=action,
        outcome=outcome,
        report_id=click.report_id,
    )


def _blocks_with_claimant(blocks: list[dict], slack_user_id: str) -> list[dict]:
    """The message with the claim button replaced by a line that names the person who took the report."""
    claimant = {
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": f"🙋 <@{slack_user_id}> is on it"}],
    }
    updated: list[dict] = []
    for block in blocks:
        if block.get("type") != "actions":
            updated.append(block)
            continue
        elements = block.get("elements") or []
        remaining = [element for element in elements if element.get("action_id") != REPORT_CLAIM_ACTION_ID]
        if len(remaining) != len(elements):
            updated.append(claimant)
        if remaining:
            updated.append({**block, "elements": remaining})
    return updated


def handle_report_claim(payload: dict) -> HttpResponse:
    from products.signals.backend.facade.api import (  # noqa: PLC0415 - keeps the signals model graph off the webhook import path
        claim_report_from_slack,
    )

    click = _authorized_click(payload, "claim")
    if click is None:
        return HttpResponse(status=200)

    outcome = claim_report_from_slack(click.integration.team_id, click.report_id, user_id=click.posthog_user.id)
    _capture_click(click, "claim", outcome.status)
    if outcome.status in ("claimed", "already_yours"):
        message = payload.get("message") or {}
        post_response_url(
            click.response_url,
            {
                "replace_original": True,
                "text": message.get("text") or "",
                "blocks": _blocks_with_claimant(message.get("blocks") or [], click.slack_user_id),
            },
        )
    elif outcome.status == "claimed_by_other":
        _post_private_note(
            click.response_url,
            f"{outcome.holder_name} is already working on this report. "
            "Open it in PostHog to see the work or to take it over.",
        )
    elif outcome.status == "not_claimable":
        _post_private_note(click.response_url, _NOT_CLAIMABLE)
    else:
        _post_private_note(click.response_url, _REPORT_NOT_LINKED)
    return HttpResponse(status=200)


def handle_report_copy_prompt(payload: dict) -> HttpResponse:
    from products.signals.backend.facade.api import (  # noqa: PLC0415 - keeps the signals model graph off the webhook import path
        report_implementation_prompt,
    )

    click = _authorized_click(payload, "copy_prompt")
    if click is None:
        return HttpResponse(status=200)

    prompt = report_implementation_prompt(click.integration.team_id, click.report_id)
    _capture_click(click, "copy_prompt", "prompt_shown")
    post_response_url(
        click.response_url,
        {
            "response_type": "ephemeral",
            "replace_original": False,
            "text": _COPY_PROMPT_INTRO,
            "blocks": [
                {"type": "section", "text": {"type": "mrkdwn", "text": _COPY_PROMPT_INTRO}},
                # Preformatted rich text shows the prompt as it is, so no mrkdwn escape is necessary.
                {
                    "type": "rich_text",
                    "elements": [{"type": "rich_text_preformatted", "elements": [{"type": "text", "text": prompt}]}],
                },
            ],
        },
    )
    return HttpResponse(status=200)
