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
# Only the unhappy states act, so only they need a bar. It applies to `not_happy` and `frustrated` together,
# because the model splits an angry message between the two, and the sum must exceed it: unhappy has to be
# likelier than not. Tuned in
# products/slack_app/evals/eval_message_sentiment.py.
SENTIMENT_UNHAPPY_MIN_PROBABILITY = 0.5
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
    Sentiment.HAPPY: "The person is sincerely pleased with an answer: thanks for it, praise, relief, or excitement. "
    "A message that complains about the answer is never happy, even when it opens with a praise word.",
    Sentiment.NEUTRAL: "The person asks, instructs, or reports something with no feeling about the assistant. "
    "A calm correction, an urgent request, or a problem in their own product is neutral. "
    "A short thanks that only opens the next request, such as 'thanks. can you also...', is neutral.",
    Sentiment.CONFUSED: "The person does not understand an answer and asks what it means or why, "
    "without blaming the assistant.",
    Sentiment.NOT_HAPPY: "The person is mildly dissatisfied: the answer is wrong, incomplete, or hard to use, "
    "or the PostHog app itself, not their own product, keeps failing them, and they say so, but they stay calm "
    "and keep working with the assistant.",
    Sentiment.FRUSTRATED: "The person is angry or out of patience: insults, shouting, a repeated request "
    "after earlier failures, a statement that the assistant is useless, or giving up on it. "
    "Sarcasm is frustrated even though it uses positive words: 'great', 'perfect' or 'love it' followed by a "
    "complaint about the answer, such as 'perfect, the wrong project again'.",
}


@frozen
class SentimentVerdict:
    choice: str
    confidence: float
    probabilities: Mapping[str, float]

    @property
    def sentiment(self) -> Sentiment:
        """Unhappy when the two unhappy options together pass the bar, as whichever of them is likelier, and
        a tie reads as the milder ``not_happy``. Otherwise the model's pick, which acts on nothing, unless that
        pick is an unhappy option below the bar, which reads as neutral."""
        not_happy = self._probability(Sentiment.NOT_HAPPY)
        frustrated = self._probability(Sentiment.FRUSTRATED)
        if not_happy + frustrated > SENTIMENT_UNHAPPY_MIN_PROBABILITY:
            return Sentiment.FRUSTRATED if frustrated > not_happy else Sentiment.NOT_HAPPY
        if self.choice in _SENTIMENT_VALUES and self.choice not in UNHAPPY_SENTIMENTS:
            return Sentiment(self.choice)
        return Sentiment.NEUTRAL

    def _probability(self, option: Sentiment) -> float:
        # An answer without the distribution still carries the pick's own confidence.
        fallback = self.confidence if self.choice == option else 0.0
        return self.probabilities.get(option, fallback)

    @property
    def is_unhappy(self) -> bool:
        return self.sentiment in UNHAPPY_SENTIMENTS


def classify_sentiment(
    message: str, *, team_id: int, distinct_id: str | None, trace_id: str | None, privacy_mode: bool = False
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
        privacy_mode=privacy_mode,
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


def is_unhappy(
    message: str, *, team_id: int, distinct_id: str | None, trace_id: str | None, privacy_mode: bool = False
) -> bool:
    """Whether the message reads as unhappy. Any failure reads as no, because a missed prompt costs little."""
    try:
        verdict = classify_sentiment(
            message, team_id=team_id, distinct_id=distinct_id, trace_id=trace_id, privacy_mode=privacy_mode
        )
    except Exception:
        logger.warning("slack_app_sentiment_classifier_failed", exc_info=True)
        return False
    return verdict is not None and verdict.is_unhappy


UNHAPPY_REACTION = "bow"
# Optional Slack calls under the relay's deadline. The client also drops slack_sdk's connection retries.
SLACK_CALL_TIMEOUT_SECONDS = 5
GIF_ALT_TEXT = "A calming GIF"
# Used when the GIF flag is on but its payload names no GIFs.
DEFAULT_FRUSTRATION_GIF_URLS: tuple[str, ...] = (
    "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExZnozMjJ4MzRiZjNtaTNvb3NoMTVlODFpaHZrZHM4MnExZms0Mm5xYiZlcD12MV9naWZzX3NlYXJjaCZjdD1n/CJZVh75FehozK/giphy.gif",
    "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExcXlheHR2dXZtY3l2Y3BzNDJyODFtdjk3YnpvNDlnYnVlY3EyY3VodiZlcD12MV9naWZzX3NlYXJjaCZjdD1n/3o6wNLivpQhzAEdYhq/giphy.gif",
    "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExN3psNG16cnlvbWtieDhlZjhlbTJjeHB2MnFlMDB6NG45OTQ3eXM1ZiZlcD12MV9naWZzX3NlYXJjaCZjdD1n/ijfxMxbdvLhM8PwHQF/giphy.gif",
    "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExZnozMjJ4MzRiZjNtaTNvb3NoMTVlODFpaHZrZHM4MnExZms0Mm5xYiZlcD12MV9naWZzX3NlYXJjaCZjdD1n/7OfNbBQHgxYVG/giphy.gif",
)


@frozen
class SentimentResult:
    # None when the model call failed or gave no choice, so a later step reads it as calm and does not call again.
    sentiment: Sentiment | None


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


def respond_to_sentiment(request: SentimentResponseRequest) -> SentimentResult | None:
    """React to how the person feels. ``None`` means no attempt, because the flag is off or there is no message."""
    # Deferred like the other ee imports in this product, so ee stays off the import path of every caller.
    from ee.hogai.utils.feature_flags import is_privacy_mode_enabled  # noqa: PLC0415

    integration = request.integration
    distinct_id = request.posthog_user.distinct_id if request.posthog_user is not None else None
    if not request.person_message or not is_slack_app_frustration_response_enabled(integration, distinct_id):
        return None
    try:
        verdict = classify_sentiment(
            request.person_message,
            team_id=integration.team_id,
            distinct_id=distinct_id,
            trace_id=request.trace_id,
            privacy_mode=is_privacy_mode_enabled(integration.team),
        )
    except Exception:
        logger.warning("slack_app_sentiment_classifier_failed", exc_info=True)
        return SentimentResult(sentiment=None)
    if verdict is None:
        return SentimentResult(sentiment=None)
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
        return SentimentResult(sentiment=sentiment)

    client = SlackIntegration(integration, timeout_seconds=SLACK_CALL_TIMEOUT_SECONDS).client
    if request.person_message_ts:
        try:
            client.reactions_add(channel=request.channel, timestamp=request.person_message_ts, name=UNHAPPY_REACTION)
        except Exception:
            logger.warning("slack_app_sentiment_reaction_failed", exc_info=True)
    if sentiment == Sentiment.FRUSTRATED:
        _send_gif(request, client, distinct_id)
    return SentimentResult(sentiment=sentiment)


def _send_gif(request: SentimentResponseRequest, client: WebClient, distinct_id: str | None) -> None:
    gif_urls = slack_app_frustration_gif_urls(request.integration, distinct_id)
    if gif_urls is None:
        return
    gif_url = random.choice(gif_urls or DEFAULT_FRUSTRATION_GIF_URLS)
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
