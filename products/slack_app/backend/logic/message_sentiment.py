"""How a person feels about the PostHog assistant, read from the message an answer replies to.

Behind ``slack-app-frustration-response``, every answered message is classified, and each verdict is captured.
A ``not_happy`` or ``frustrated`` message gets ``UNHAPPY_REACTION``. A ``frustrated`` message also gets a private
GIF when ``slack-app-frustration-gif`` is on. The interview invitation reuses the verdict, so the model runs once
per answer.
"""

from __future__ import annotations

import random
from collections.abc import Mapping
from enum import StrEnum
from typing import TYPE_CHECKING

import structlog

from posthog.dataclasses import frozen
from posthog.llm.managed_decision_model import DEFAULT_DECISION_MODEL
from posthog.llm.system_one import ChoiceAnswer, ChoiceQuestion
from posthog.llm.system_one_client import build_system_one_client
from posthog.models.integration import SlackIntegration

from products.slack_app.backend.analytics import capture_slack_event
from products.slack_app.backend.feature_flags import (
    is_slack_app_frustration_response_enabled,
    slack_app_frustration_gif_urls,
)
from products.slack_app.backend.services.slack_messages import post_slack_ephemeral
from products.slack_app.backend.services.workspace_integrations import WorkspaceIntegration
from products.slack_app.backend.temporal.activities.classifiers import CLASSIFIER_PROPERTY

if TYPE_CHECKING:
    from slack_sdk import WebClient

    from posthog.models.user import User

logger = structlog.get_logger(__name__)


class Sentiment(StrEnum):
    HAPPY = "happy"
    NEUTRAL = "neutral"
    CONFUSED = "confused"
    NOT_HAPPY = "not_happy"
    FRUSTRATED = "frustrated"


UNHAPPY_SENTIMENTS: frozenset[Sentiment] = frozenset({Sentiment.NOT_HAPPY, Sentiment.FRUSTRATED})
_SENTIMENT_VALUES: frozenset[str] = frozenset(Sentiment)

# Not the `slack_app` product the other classifiers bill under: the verdict serves PostHog, so it must not
# spend the team's AI credits.
SENTIMENT_AI_PRODUCT = "slack_app_interview_recruitment"
# The answer is already in the thread. A slow call only drops the reaction and the invitation.
SENTIMENT_TIMEOUT_SECONDS = 5.0
# A reaction or an invitation to a calm person costs trust, and a missed one costs little, so the bar is high.
# Tuned in products/slack_app/evals/eval_message_sentiment.py.
SENTIMENT_MIN_CONFIDENCE = 0.7
SENTIMENT_QUESTION_ID = "sentiment"
# The model needs the tone, not the whole message. This also keeps pasted logs out of the call.
SENTIMENT_MESSAGE_MAX_CHARS = 500
SENTIMENT_INSTRUCTIONS = (
    "`message` is what a person wrote to the PostHog assistant in Slack. "
    "Decide how the person feels about the assistant, its answers, or PostHog. "
    "Judge the tone and the intent, in any language. Do not judge the topic: bad news about their own product, "
    "or annoyance with other people, is not a feeling about the assistant."
)
SENTIMENT_CRITERIA = {
    Sentiment.HAPPY: "The person is pleased with the assistant: thanks, praise, relief, or excitement about an answer.",
    Sentiment.NEUTRAL: "The person asks, instructs, or reports something with no feeling about the assistant. "
    "A calm correction, an urgent request, or a problem in their own product is neutral.",
    Sentiment.CONFUSED: "The person does not understand an answer and asks what it means or why, "
    "without blaming the assistant.",
    Sentiment.NOT_HAPPY: "The person is mildly dissatisfied: the answer is wrong, incomplete, or hard to use, "
    "and they say so, but they stay calm and keep working with the assistant.",
    Sentiment.FRUSTRATED: "The person is angry or out of patience: insults, sarcasm, shouting, a repeated request "
    "after earlier failures, a statement that the assistant is useless, or giving up on it.",
}


@frozen
class SentimentVerdict:
    choice: str
    confidence: float
    probabilities: Mapping[str, float]

    @property
    def sentiment(self) -> Sentiment:
        """The model's pick when it is sure. An unsure pick counts as neutral, except when the unhappy
        options together pass the bar: a split between ``not_happy`` and ``frustrated`` is still unhappy,
        so it reads as the milder of the two."""
        if self.choice in _SENTIMENT_VALUES and self.confidence >= SENTIMENT_MIN_CONFIDENCE:
            return Sentiment(self.choice)
        unhappy = sum(self.probabilities.get(option, 0.0) for option in UNHAPPY_SENTIMENTS)
        return Sentiment.NOT_HAPPY if unhappy >= SENTIMENT_MIN_CONFIDENCE else Sentiment.NEUTRAL

    @property
    def is_unhappy(self) -> bool:
        return self.sentiment in UNHAPPY_SENTIMENTS


def classify_sentiment(
    message: str, *, team_id: int, distinct_id: str | None, trace_id: str | None
) -> SentimentVerdict | None:
    """Ask the decision model how the person feels about the assistant. ``None`` means no verdict.

    Raises when no System One server is configured or the call fails, so the caller can tell an
    outage from a refusal.
    """
    text = message.strip()[:SENTIMENT_MESSAGE_MAX_CHARS]
    if not text:
        return None
    # No TypeSafe fallback: the message is customer text, and TypeSafe is a third party.
    client = build_system_one_client(
        model=DEFAULT_DECISION_MODEL,
        ai_product=SENTIMENT_AI_PRODUCT,
        team_id=team_id,
        distinct_id=distinct_id,
        trace_id=trace_id,
        properties={CLASSIFIER_PROPERTY: "message_sentiment"},
        timeout=SENTIMENT_TIMEOUT_SECONDS,
    )
    result = client.decide(
        state={"message": text},
        questions={
            SENTIMENT_QUESTION_ID: ChoiceQuestion(
                instructions=SENTIMENT_INSTRUCTIONS,
                criteria={str(option): criterion for option, criterion in SENTIMENT_CRITERIA.items()},
            )
        },
    )
    answer = result.answers.get(SENTIMENT_QUESTION_ID)
    if not isinstance(answer, ChoiceAnswer):
        return None
    return SentimentVerdict(
        choice=answer.choice, confidence=answer.confidence, probabilities=dict(answer.probabilities)
    )


def is_unhappy(message: str, *, team_id: int, distinct_id: str | None, trace_id: str | None) -> bool:
    """Whether the message reads as unhappy. Any failure reads as no, because a missed prompt costs little."""
    try:
        verdict = classify_sentiment(message, team_id=team_id, distinct_id=distinct_id, trace_id=trace_id)
    except Exception:
        logger.warning("slack_app_sentiment_classifier_failed", exc_info=True)
        return False
    return verdict is not None and verdict.is_unhappy


UNHAPPY_REACTION = "bow"
GIF_ALT_TEXT = "A calming GIF"


@frozen
class SentimentResponseRequest:
    integration: WorkspaceIntegration
    slack_user_id: str
    posthog_user: User | None
    channel: str
    thread_ts: str
    person_message: str | None
    person_message_ts: str | None
    run_id: str | None
    trace_id: str | None


def respond_to_sentiment(request: SentimentResponseRequest) -> Sentiment | None:
    """React to how the person feels. ``None`` means no verdict: the flag is off, there is no message, or
    the model call failed."""
    integration = request.integration
    distinct_id = request.posthog_user.distinct_id if request.posthog_user is not None else None
    if not request.person_message or not is_slack_app_frustration_response_enabled(integration, distinct_id):
        return None
    try:
        verdict = classify_sentiment(
            request.person_message, team_id=integration.team_id, distinct_id=distinct_id, trace_id=request.trace_id
        )
    except Exception:
        logger.warning("slack_app_sentiment_classifier_failed", exc_info=True)
        return None
    if verdict is None:
        return None
    sentiment = verdict.sentiment
    capture_slack_event(
        integration,
        "slack app message sentiment classified",
        slack_user_id=request.slack_user_id,
        posthog_user=request.posthog_user,
        sentiment=str(sentiment),
        model_choice=verdict.choice,
        confidence=verdict.confidence,
        task_run_id=request.run_id,
        ai_trace_id=request.trace_id,
    )
    if sentiment not in UNHAPPY_SENTIMENTS:
        return sentiment

    client = SlackIntegration(integration).client
    if request.person_message_ts:
        try:
            client.reactions_add(channel=request.channel, timestamp=request.person_message_ts, name=UNHAPPY_REACTION)
        except Exception:
            logger.warning("slack_app_sentiment_reaction_failed", exc_info=True)
    if sentiment == Sentiment.FRUSTRATED:
        _send_gif(request, client, distinct_id)
    return sentiment


def _send_gif(request: SentimentResponseRequest, client: WebClient, distinct_id: str | None) -> None:
    gif_urls = slack_app_frustration_gif_urls(request.integration, distinct_id)
    if not gif_urls:
        return
    gif_url = random.choice(gif_urls)
    try:
        post_slack_ephemeral(
            client,
            channel=request.channel,
            user=request.slack_user_id,
            thread_ts=request.thread_ts,
            text=GIF_ALT_TEXT,
            blocks=[{"type": "image", "image_url": gif_url, "alt_text": GIF_ALT_TEXT}],
        )
    except Exception:
        logger.warning("slack_app_frustration_gif_post_failed", exc_info=True)
        return
    capture_slack_event(
        request.integration,
        "slack app frustration gif shown",
        slack_user_id=request.slack_user_id,
        posthog_user=request.posthog_user,
        gif_url=gif_url,
        task_run_id=request.run_id,
        ai_trace_id=request.trace_id,
    )
