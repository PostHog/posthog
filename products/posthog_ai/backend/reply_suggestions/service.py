from typing import Literal

from django.core.cache import cache

import structlog

from posthog.dataclasses import frozen

from products.posthog_ai.backend.turn_suggestions.service import (
    MAX_TRANSCRIPT_LOG_BYTES,
    _history_is_whole,
    load_web_conversation_run,
)
from products.posthog_ai.backend.turn_suggestions.transcript import build_turn_transcript
from products.tasks.backend.facade.api import publish_task_run_stream_notification, read_task_run_history
from products.tasks.backend.facade.reply_suggestions import ReplySuggestionAttribution, suggest_replies

logger = structlog.get_logger(__name__)

REPLY_SUGGESTIONS_FLAG = "posthog-ai-reply-suggestions"
REPLY_SUGGESTIONS_METHOD = "_posthog/reply_suggestions"
REPLY_SUGGESTIONS_AI_PRODUCT = "posthog_ai"
REPLY_SUGGESTIONS_FEATURE = "reply_suggestions"
REPLY_SUGGESTIONS_REASONING_EFFORT = "none"
TURN_CLAIM_SECONDS = 60 * 60

OutcomeStatus = Literal["emitted", "skipped", "failed"]


@frozen
class ReplySuggestionsOutcome:
    status: OutcomeStatus
    reason: str


def _skipped(reason: str) -> ReplySuggestionsOutcome:
    return ReplySuggestionsOutcome(status="skipped", reason=reason)


def generate_reply_suggestions(run_id: str, team_id: int) -> ReplySuggestionsOutcome:
    loaded = load_web_conversation_run(run_id, team_id, flag=REPLY_SUGGESTIONS_FLAG)
    if isinstance(loaded, str):
        return _skipped(loaded)
    task_run, user = loaded.task_run, loaded.user
    task = task_run.task
    if not _history_is_whole(task_run):
        return _skipped("history_truncated")

    entries = read_task_run_history(task_run.id, task_run.task_id, task_run.team_id, max_bytes=MAX_TRANSCRIPT_LOG_BYTES)
    if entries is None:
        return _skipped("log_too_large")
    transcript = build_turn_transcript(entries, assistant_text_limit=None)
    if not transcript.human_messages:
        return _skipped("no_user_message")
    if not transcript.latest_turn_complete:
        return _skipped("turn_in_progress")
    if not transcript.assistant_text.strip():
        return _skipped("no_answer")
    turn_index = len(transcript.human_messages) - 1
    if not cache.add(f"posthog_ai_reply_suggestions:{task.id}:{turn_index}", True, timeout=TURN_CLAIM_SECONDS):
        return _skipped("turn_already_claimed")

    from ee.hogai.utils.feature_flags import is_privacy_mode_enabled  # noqa: PLC0415

    suggestions = suggest_replies(
        transcript.assistant_text,
        ReplySuggestionAttribution(
            ai_product=REPLY_SUGGESTIONS_AI_PRODUCT,
            properties={"posthog_ai_feature": REPLY_SUGGESTIONS_FEATURE},
            session_id=str(task.id),
            distinct_id=str(user.distinct_id),
            task_id=str(task.id),
            run_id=str(task_run.id),
            privacy_mode=is_privacy_mode_enabled(task_run.team),
        ),
        transcript.last_human_message,
        reasoning_effort=REPLY_SUGGESTIONS_REASONING_EFFORT,
    )
    if not suggestions:
        return _skipped("nothing_to_suggest")

    delivery = publish_task_run_stream_notification(
        task_run.id,
        task_run.task_id,
        task_run.team_id,
        REPLY_SUGGESTIONS_METHOD,
        {
            "turnIndex": turn_index,
            "suggestions": [{"label": s.label, "reply": s.reply} for s in suggestions],
        },
        persist=False,
    )
    if not delivery.live:
        return ReplySuggestionsOutcome(status="failed", reason="publish_failed")
    return ReplySuggestionsOutcome(status="emitted", reason=str(len(suggestions)))
