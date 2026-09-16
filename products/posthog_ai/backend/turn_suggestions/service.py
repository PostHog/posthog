"""Builds the end-of-turn suggestion for a sandbox PostHog AI conversation.

Runs off the request path once a turn completes. It reads the run's stream, keeps only first turns
of interactive PostHog AI runs whose project can create scouts, asks the classifier, and publishes
a ``_posthog/turn_suggestion`` frame into the same stream the thread renders from, so the card
appears under the answer without the frontend polling anything.
"""

from datetime import UTC, datetime
from typing import Literal

import structlog

from posthog.dataclasses import frozen
from posthog.ph_client import feature_enabled_or_false, ph_scoped_capture
from posthog.redis import get_client

from products.posthog_ai.backend.turn_suggestions.classifier import CLASSIFIER_MODEL, TurnVerdict, classify_turn
from products.posthog_ai.backend.turn_suggestions.transcript import TurnTranscript, build_turn_transcript
from products.signals.backend.facade.api import scout_creation_available
from products.tasks.backend.facade.api import (
    parse_task_run_log_entries,
    publish_task_run_stream_notification,
    read_task_run_logs,
    read_task_run_stream_entries,
)
from products.tasks.backend.models import Task, TaskRun

logger = structlog.get_logger(__name__)

TURN_SUGGESTIONS_FLAG = "posthog-ai-turn-suggestions"
TURN_SUGGESTION_METHOD = "_posthog/turn_suggestion"
# The proxy callback and the event-ingest path can both report the same turn end; one suggestion
# per (run, turn) is enough.
_DEDUPE_TTL_SECONDS = 24 * 60 * 60

OutcomeStatus = Literal["emitted", "skipped", "failed"]


@frozen
class TurnSuggestionOutcome:
    status: OutcomeStatus
    reason: str


def _skipped(reason: str) -> TurnSuggestionOutcome:
    return TurnSuggestionOutcome(status="skipped", reason=reason)


def _turn_suggestions_enabled(task_run: TaskRun) -> bool:
    user = task_run.task.created_by
    if user is None:
        return False
    organization_id = str(task_run.team.organization_id)
    return feature_enabled_or_false(
        TURN_SUGGESTIONS_FLAG,
        str(user.distinct_id),
        groups={"organization": organization_id},
        group_properties={"organization": {"id": organization_id}},
        send_feature_flag_events=False,
    )


def _load_transcript(task_run: TaskRun) -> TurnTranscript:
    """The live Redis stream has the whole current turn; the S3 log is the fallback once it expired."""
    entries = read_task_run_stream_entries(str(task_run.id))
    transcript = build_turn_transcript(entries)
    if transcript.human_messages:
        return transcript
    log_content = read_task_run_logs(task_run.id, task_run.task_id, task_run.team_id)
    if not log_content:
        return transcript
    return build_turn_transcript(parse_task_run_log_entries(log_content))


def _claim_turn(task_run: TaskRun, turn_index: int) -> bool:
    key = f"posthog_ai:turn_suggestion:{task_run.id}:{turn_index}"
    try:
        return bool(get_client().set(key, "1", nx=True, ex=_DEDUPE_TTL_SECONDS))
    except Exception:
        logger.warning("posthog_ai_turn_suggestion_dedupe_unavailable", run_id=str(task_run.id))
        return True


def _turn_has_substance(transcript: TurnTranscript) -> bool:
    """A notebook is only worth saving when the assistant actually queried something and answered."""
    return bool(transcript.tool_calls) and bool(transcript.assistant_text)


def _suggestion_params(verdict: TurnVerdict, transcript: TurnTranscript, turn_index: int) -> dict | None:
    base = {
        "turnIndex": turn_index,
        "intent": verdict.intent.value,
        "confidence": verdict.confidence,
        "title": verdict.title,
        "description": verdict.description,
    }
    if verdict.offers_scout and verdict.scout is not None:
        return {
            **base,
            "kind": "scout",
            "scout": {
                "displayName": verdict.scout.display_name,
                "description": verdict.scout.description,
                "body": verdict.scout.body,
                "cadence": verdict.scout.cadence.value,
            },
        }
    if verdict.offers_notebook and verdict.notebook is not None and _turn_has_substance(transcript):
        return {
            **base,
            "kind": "notebook",
            "notebook": {"title": verdict.notebook.title, "summary": verdict.notebook.summary},
        }
    return None


def _capture_classified(
    task_run: TaskRun, verdict: TurnVerdict | None, *, offer: str | None, emitted: bool, turn_index: int
) -> None:
    user = task_run.task.created_by
    if user is None:
        return
    with ph_scoped_capture() as capture:
        capture(
            distinct_id=str(user.distinct_id),
            event="posthog ai turn suggestion classified",
            properties={
                "team_id": task_run.team_id,
                "task_id": str(task_run.task_id),
                "run_id": str(task_run.id),
                "turn_index": turn_index,
                "model": CLASSIFIER_MODEL,
                "intent": verdict.intent.value if verdict else None,
                "recurring": verdict.recurring if verdict else None,
                "confidence": verdict.confidence if verdict else None,
                "offer": offer,
                "emitted": emitted,
            },
        )


def generate_turn_suggestion(run_id: str) -> TurnSuggestionOutcome:
    try:
        task_run = TaskRun.objects.select_related("task__created_by", "team").get(id=run_id)
    except TaskRun.DoesNotExist:
        return _skipped("run_missing")

    task = task_run.task
    if task.origin_product != Task.OriginProduct.POSTHOG_AI or task_run.mode != "interactive":
        return _skipped("not_posthog_ai_conversation")
    if task.created_by is None:
        return _skipped("no_user")
    if not _turn_suggestions_enabled(task_run):
        return _skipped("flag_off")

    transcript = _load_transcript(task_run)
    if len(transcript.human_messages) != 1:
        return _skipped("not_first_turn")
    turn_index = len(transcript.human_messages) - 1
    if not transcript.assistant_text and not transcript.tool_calls:
        return _skipped("empty_turn")
    if not scout_creation_available(team=task_run.team, user=task.created_by):
        return _skipped("scouts_unavailable")
    if not _claim_turn(task_run, turn_index):
        return _skipped("already_classified")

    verdict = classify_turn(transcript, team_id=task_run.team_id, today=datetime.now(UTC).date())
    if verdict is None:
        _capture_classified(task_run, None, offer=None, emitted=False, turn_index=turn_index)
        return TurnSuggestionOutcome(status="failed", reason="classifier_failed")

    params = _suggestion_params(verdict, transcript, turn_index)
    emitted = params is not None and publish_task_run_stream_notification(
        str(task_run.id), TURN_SUGGESTION_METHOD, params
    )
    offer = str(params["kind"]) if params is not None else None
    _capture_classified(task_run, verdict, offer=offer, emitted=emitted, turn_index=turn_index)
    if params is None:
        return _skipped(f"no_offer:{verdict.intent.value}")
    if not emitted:
        return TurnSuggestionOutcome(status="failed", reason="publish_failed")
    return TurnSuggestionOutcome(status="emitted", reason=offer or "unknown")
