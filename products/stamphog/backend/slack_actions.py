"""Clicks on the buttons of the Broadcast request card in Slack.

The slack_app product serves the PostHog Slack app's interactivity URL and forwards the click to the
region that owns the card. It reaches stamphog through ``posthog.slack.block_actions``, because a
direct import of stamphog would make a dependency cycle.
"""

from __future__ import annotations

from typing import Any

from posthog.slack.block_actions import register_block_action_handler

from products.stamphog.backend.logic.broadcast_request_slack import ACTION_ID_PREFIX, parse_look_click


def handle_card_click(payload: dict[str, Any], action: dict[str, Any]) -> None:
    # Deferred, because connect() runs in AppConfig.ready() and must not load the GitHub client and Celery tasks there.
    from products.stamphog.backend.logic.broadcast_requests import record_look  # noqa: PLC0415
    from products.stamphog.backend.tasks.broadcast_requests import queue_broadcast_request_refresh  # noqa: PLC0415

    click = parse_look_click(payload, action)
    if click is not None and record_look(click):
        queue_broadcast_request_refresh(click.team_id, click.broadcast_request_id)


def connect() -> None:
    register_block_action_handler(ACTION_ID_PREFIX, handle_card_click)
