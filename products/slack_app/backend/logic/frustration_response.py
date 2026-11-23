"""A private apology under the answer when the person's message reads as unhappy with the assistant.

Behind the ``slack-app-frustration-response`` flag. When the flag is on and the decision model reads the
message as unhappy, the bot reacts to the message with ``FRUSTRATION_REACTION`` and posts a private message
with a button that opens the bad-rating modal. The flag payload can name GIFs, and the message then shows
one of them at random.
"""

from __future__ import annotations

import json
import random
from typing import TYPE_CHECKING, Any, Literal

import structlog

from posthog.dataclasses import frozen
from posthog.models.integration import SlackIntegration

from products.slack_app.backend.analytics import capture_slack_event
from products.slack_app.backend.feature_flags import slack_app_frustration_response_gate
from products.slack_app.backend.logic.interview_recruitment import is_unhappy
from products.slack_app.backend.services.slack_messages import (
    TURN_FEEDBACK_ACTION_ID,
    post_slack_ephemeral,
    section_block,
)
from products.slack_app.backend.services.turn_feedback import FRUSTRATION_RESPONSE_FEEDBACK_SOURCE
from products.slack_app.backend.services.workspace_integrations import WorkspaceIntegration

if TYPE_CHECKING:
    from posthog.models.user import User

logger = structlog.get_logger(__name__)

FRUSTRATION_REACTION = "bow"
APOLOGY_MESSAGE = "Sorry this didn't go well. Tell us what went wrong, and we'll use it to improve."
TELL_US_BUTTON_LABEL = "Tell us what went wrong"
GIF_ALT_TEXT = "A calming GIF"

# "skipped" means no verdict, because the flag is off or there is no message. "calm" includes a failed model
# call. "unhappy" means the person is unhappy but did not get the private message.
FrustrationOutcome = Literal["skipped", "calm", "unhappy", "responded"]


@frozen
class FrustrationResponseRequest:
    integration: WorkspaceIntegration
    slack_user_id: str
    posthog_user: User | None
    channel: str
    thread_ts: str
    person_message: str | None
    person_message_ts: str | None
    run_id: str | None
    trace_id: str | None


def frustration_response_blocks(
    integration_id: int, run_id: str | None, trace_id: str | None, gif_url: str | None
) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = [section_block(APOLOGY_MESSAGE)]
    if gif_url:
        blocks.append({"type": "image", "image_url": gif_url, "alt_text": GIF_ALT_TEXT})
    # The click handler finds the rated turn through the run, so a turn without a run gets no button.
    if run_id:
        value = {
            "integration_id": integration_id,
            "run_id": run_id,
            "trace_id": trace_id,
            "sentiment": "negative",
            "source": FRUSTRATION_RESPONSE_FEEDBACK_SOURCE,
        }
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "action_id": TURN_FEEDBACK_ACTION_ID,
                        "text": {"type": "plain_text", "text": TELL_US_BUTTON_LABEL},
                        "value": json.dumps({key: item for key, item in value.items() if item is not None}),
                    }
                ],
            }
        )
    return blocks


def respond_to_frustration(request: FrustrationResponseRequest) -> FrustrationOutcome:
    integration = request.integration
    distinct_id = request.posthog_user.distinct_id if request.posthog_user is not None else None
    if not request.person_message:
        return "skipped"
    gate = slack_app_frustration_response_gate(integration, distinct_id)
    if gate is None:
        return "skipped"
    if not is_unhappy(
        request.person_message,
        team_id=integration.team_id,
        distinct_id=distinct_id,
        trace_id=request.trace_id,
        classifier="frustration_response_sentiment",
    ):
        return "calm"

    client = SlackIntegration(integration).client
    reacted = False
    if request.person_message_ts:
        try:
            client.reactions_add(
                channel=request.channel, timestamp=request.person_message_ts, name=FRUSTRATION_REACTION
            )
            reacted = True
        except Exception:
            logger.warning("slack_app_frustration_reaction_failed", exc_info=True)
    gif_url = random.choice(gate.gif_urls) if gate.gif_urls else None
    try:
        post_slack_ephemeral(
            client,
            channel=request.channel,
            user=request.slack_user_id,
            thread_ts=request.thread_ts,
            text=APOLOGY_MESSAGE,
            blocks=frustration_response_blocks(integration.id, request.run_id, request.trace_id, gif_url),
        )
    except Exception:
        logger.warning("slack_app_frustration_response_post_failed", exc_info=True)
        return "unhappy"
    capture_slack_event(
        integration,
        "slack app frustration response shown",
        slack_user_id=request.slack_user_id,
        posthog_user=request.posthog_user,
        reacted=reacted,
        gif_url=gif_url,
        task_run_id=request.run_id,
        ai_trace_id=request.trace_id,
    )
    return "responded"
