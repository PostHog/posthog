from typing import TYPE_CHECKING, Literal

from django.core.cache import cache

import structlog

from posthog.dataclasses import frozen
from posthog.ph_client import feature_enabled_or_false

from products.posthog_ai.backend.turn_suggestions.service import MAX_TRANSCRIPT_LOG_BYTES, _history_is_whole
from products.posthog_ai.backend.turn_suggestions.transcript import build_turn_transcript
from products.tasks.backend.facade.api import (
    TaskClientProvenance,
    publish_task_run_stream_notification,
    read_task_run_history,
)
from products.tasks.backend.facade.reply_suggestions import ReplySuggestionAttribution, suggest_replies
from products.tasks.backend.models import Task, TaskRun

if TYPE_CHECKING:
    from posthog.models.user import User

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


def _enabled(task_run: TaskRun, user: "User") -> bool:
    organization_id = str(task_run.team.organization_id)
    return feature_enabled_or_false(
        REPLY_SUGGESTIONS_FLAG,
        str(user.distinct_id),
        groups={"organization": organization_id},
        group_properties={"organization": {"id": organization_id}},
        send_feature_flag_events=False,
    )


def generate_reply_suggestions(run_id: str, team_id: int) -> ReplySuggestionsOutcome:
    try:
        task_run = TaskRun.objects.select_related("task__created_by", "team__organization").get(
            id=run_id, team_id=team_id
        )
    except TaskRun.DoesNotExist:
        return _skipped("run_missing")

    task = task_run.task
    if task.origin_product != Task.OriginProduct.POSTHOG_AI or task_run.mode != "interactive":
        return _skipped("not_posthog_ai_conversation")
    if task.client_provenance == TaskClientProvenance.POSTHOG_DESKTOP:
        return _skipped("not_started_in_web")
    user = task.created_by
    if user is None:
        return _skipped("no_user")
    if task_run.team.organization.is_ai_data_processing_approved is not True:
        return _skipped("ai_data_processing_not_approved")
    if not _enabled(task_run, user):
        return _skipped("flag_off")
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
