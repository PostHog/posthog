"""Builds the end-of-turn suggestion for a sandbox PostHog AI conversation.

Runs off the request path once a turn completes. It checks the cheap gates first, reads the run's
stream, asks the classifier, and publishes a ``_posthog/turn_suggestion`` frame into the same
stream the thread renders from, so the card appears under the answer without the frontend polling.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal, TypeVar

import structlog
from redis import Redis

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

# A conversation gets a couple of offers at most, so a long investigation is not nudged on every
# turn. A second offer exists for the case where the first was superseded by the next message.
MAX_OFFERS_PER_CONVERSATION = 2
_OFFER_BUDGET_TTL_SECONDS = 7 * 24 * 60 * 60

OutcomeStatus = Literal["emitted", "skipped", "failed"]
T = TypeVar("T")


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


def _with_redis(task_run: TaskRun, operation: Callable[[Redis], T], fallback: T, event: str) -> T:
    """Redis keeps the nudge honest, not correct: when it is unreachable the call degrades to the fallback."""
    try:
        return operation(get_client())
    except Exception:
        logger.warning(event, run_id=str(task_run.id))
        return fallback


def _claim_turn(task_run: TaskRun, turn_index: int) -> bool:
    key = f"posthog_ai:turn_suggestion:{task_run.id}:{turn_index}"
    return _with_redis(
        task_run,
        lambda client: bool(client.set(key, "1", nx=True, ex=_DEDUPE_TTL_SECONDS)),
        True,
        "posthog_ai_turn_suggestion_dedupe_unavailable",
    )


def _offer_budget_key(task_run: TaskRun) -> str:
    return f"posthog_ai:turn_suggestion:offers:{task_run.task_id}"


def _offers_made(task_run: TaskRun) -> int:
    key = _offer_budget_key(task_run)
    return _with_redis(
        task_run, lambda client: int(client.get(key) or 0), 0, "posthog_ai_turn_suggestion_budget_unavailable"
    )


def _record_offer(task_run: TaskRun) -> None:
    key = _offer_budget_key(task_run)

    def increment(client: Redis) -> None:
        with client.pipeline() as pipeline:
            pipeline.incr(key)
            pipeline.expire(key, _OFFER_BUDGET_TTL_SECONDS)
            pipeline.execute()

    _with_redis(task_run, increment, None, "posthog_ai_turn_suggestion_budget_unavailable")


def _load_transcript(task_run: TaskRun) -> TurnTranscript:
    """The live Redis stream has the whole current turn; the S3 log is the fallback once it expired."""
    transcript = build_turn_transcript(read_task_run_stream_entries(task_run.id, task_run.task_id, task_run.team_id))
    if transcript.human_messages:
        return transcript
    log_content = read_task_run_logs(task_run.id, task_run.task_id, task_run.team_id)
    if not log_content:
        return transcript
    return build_turn_transcript(parse_task_run_log_entries(log_content))


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
    try:
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
    except Exception:
        # Analytics must not change the outcome of a suggestion that already reached the thread.
        logger.warning("posthog_ai_turn_suggestion_capture_failed", run_id=str(task_run.id), exc_info=True)


def generate_turn_suggestion(run_id: str, team_id: int) -> TurnSuggestionOutcome:
    try:
        task_run = TaskRun.objects.select_related("task__created_by", "team").get(id=run_id, team_id=team_id)
    except TaskRun.DoesNotExist:
        return _skipped("run_missing")

    task = task_run.task
    if task.origin_product != Task.OriginProduct.POSTHOG_AI or task_run.mode != "interactive":
        return _skipped("not_posthog_ai_conversation")
    if task.created_by is None:
        return _skipped("no_user")
    if not _turn_suggestions_enabled(task_run):
        return _skipped("flag_off")
    if _offers_made(task_run) >= MAX_OFFERS_PER_CONVERSATION:
        return _skipped("offer_budget_spent")
    if not scout_creation_available(team=task_run.team, user=task.created_by):
        return _skipped("scouts_unavailable")

    transcript = _load_transcript(task_run)
    if not transcript.human_messages:
        return _skipped("no_user_message")
    turn_index = len(transcript.human_messages) - 1
    if not transcript.assistant_text and not transcript.tool_calls:
        return _skipped("empty_turn")
    if not _claim_turn(task_run, turn_index):
        return _skipped("already_classified")

    verdict = classify_turn(transcript, team_id=task_run.team_id, today=datetime.now(UTC).date())
    if verdict is None:
        _capture_classified(task_run, None, offer=None, emitted=False, turn_index=turn_index)
        return TurnSuggestionOutcome(status="failed", reason="classifier_failed")

    params = _suggestion_params(verdict, transcript, turn_index)
    offer = str(params["kind"]) if params is not None else None
    # Publishing also appends to the run's S3 log, a rewrite of the whole log; the offer budget is
    # what keeps that to a couple of times per conversation.
    emitted = params is not None and publish_task_run_stream_notification(
        task_run.id, task_run.task_id, task_run.team_id, TURN_SUGGESTION_METHOD, params
    )
    _capture_classified(task_run, verdict, offer=offer, emitted=emitted, turn_index=turn_index)
    if params is None:
        return _skipped(f"no_offer:{verdict.intent.value}")
    if not emitted:
        return TurnSuggestionOutcome(status="failed", reason="publish_failed")
    _record_offer(task_run)
    return TurnSuggestionOutcome(status="emitted", reason=offer or "unknown")
