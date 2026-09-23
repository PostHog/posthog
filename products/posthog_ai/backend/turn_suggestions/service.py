"""Builds the end-of-turn suggestion for a sandbox PostHog AI conversation.

Runs off the request path once a turn completes. It checks the cheap gates first, reads the run's
stream, asks the classifier, and publishes a ``_posthog/turn_suggestion`` frame into the same
stream the thread renders from, so the card appears under the answer without the frontend polling.
"""

from datetime import UTC, datetime
from typing import Literal

import structlog

from posthog.dataclasses import frozen
from posthog.ph_client import feature_enabled_or_false, ph_scoped_capture

from products.posthog_ai.backend.turn_suggestions.classifier import classify_turn
from products.posthog_ai.backend.turn_suggestions.drafter import DRAFT_MODEL
from products.posthog_ai.backend.turn_suggestions.judgment import JUDGE_MODEL, judge_configured
from products.posthog_ai.backend.turn_suggestions.offer_ledger import (
    TurnSuggestionResolution,
    claim_turn,
    read_ledger,
    record_offer,
    resolve_offer,
)
from products.posthog_ai.backend.turn_suggestions.transcript import TurnTranscript, build_turn_transcript
from products.posthog_ai.backend.turn_suggestions.verdict import OfferKind, TurnVerdict
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
TURN_SUGGESTION_RESOLVED_METHOD = "_posthog/turn_suggestion_resolved"

# The offers whose text a language model writes after the judgment picks them.
_DRAFTED_OFFERS = frozenset({OfferKind.SCOUT, OfferKind.NOTEBOOK})

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


def available_offers(transcript: TurnTranscript, *, scouts_available: bool) -> frozenset[OfferKind]:
    """The offers this turn and project can act on; the classifier picks among these or none."""
    offers = set()
    if _turn_has_substance(transcript):
        offers.add(OfferKind.NOTEBOOK)
    if transcript.saved_insights:
        offers.add(OfferKind.SUBSCRIPTION)
        if any(ref.alertable for ref in transcript.saved_insights):
            offers.add(OfferKind.ALERT)
    if transcript.error_issues:
        offers.add(OfferKind.ERROR_ALERT)
    if scouts_available:
        offers.add(OfferKind.SCOUT)
    return frozenset(offers)


def _available_offers(task_run: TaskRun, transcript: TurnTranscript) -> frozenset[OfferKind]:
    user = task_run.task.created_by
    scouts_available = user is not None and scout_creation_available(team=task_run.team, user=user)
    return available_offers(transcript, scouts_available=scouts_available)


def _suggestion_params(verdict: TurnVerdict, turn_index: int) -> dict | None:
    if verdict.draft is None:
        return None
    return {
        "turnIndex": turn_index,
        "kind": verdict.offer.value,
        "intent": verdict.intent.value,
        "confidence": verdict.show_probability,
        "title": verdict.title,
        "description": verdict.description,
        verdict.draft.WIRE_KEY: verdict.draft.to_params(),
    }


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
                    "model": JUDGE_MODEL,
                    "draft_model": DRAFT_MODEL if verdict and verdict.picked in _DRAFTED_OFFERS else None,
                    "intent": verdict.intent.value if verdict else None,
                    "picked": verdict.picked.value if verdict else None,
                    "show_probability": verdict.show_probability if verdict else None,
                    "offer_probabilities": dict(verdict.offer_probabilities) if verdict else None,
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
    # Cards render only in the PostHog AI web app. Slack conversations carry the Slack origin and
    # fail the check above; PostHog Desktop ones carry a client provenance.
    if task.client_provenance:
        return _skipped("not_started_in_web")
    if task.created_by is None:
        return _skipped("no_user")
    if not _turn_suggestions_enabled(task_run):
        return _skipped("flag_off")
    if not judge_configured():
        return _skipped("judge_not_configured")
    early_refusal = read_ledger(task.id, task_run.team_id).refusal()
    if early_refusal is not None:
        return _skipped(early_refusal.value)

    transcript = _load_transcript(task_run)
    if not transcript.human_messages:
        return _skipped("no_user_message")
    turn_index = len(transcript.human_messages) - 1
    if not transcript.assistant_text and not transcript.tool_calls:
        return _skipped("empty_turn")
    available = _available_offers(task_run, transcript)
    if not available:
        return _skipped("no_offers_available")
    refusal = claim_turn(task.id, task_run.team_id, turn_index)
    if refusal is not None:
        return _skipped(refusal.value)

    verdict = classify_turn(transcript, team_id=task_run.team_id, today=datetime.now(UTC).date(), available=available)
    if verdict is None:
        _capture_classified(task_run, None, offer=None, emitted=False, turn_index=turn_index)
        return TurnSuggestionOutcome(status="failed", reason="classifier_failed")

    params = _suggestion_params(verdict, turn_index)
    offer = verdict.offer.value if params is not None else None
    # Publishing also appends to the run's S3 log, a rewrite of the whole log; the offer ledger is
    # what keeps that to a couple of times per conversation.
    emitted = params is not None and publish_task_run_stream_notification(
        task_run.id, task_run.task_id, task_run.team_id, TURN_SUGGESTION_METHOD, params
    )
    _capture_classified(task_run, verdict, offer=offer, emitted=emitted, turn_index=turn_index)
    if params is None:
        if verdict.picked != OfferKind.NONE:
            return TurnSuggestionOutcome(status="failed", reason="draft_failed")
        return _skipped(f"no_offer:{verdict.intent.value}")
    if not emitted:
        return TurnSuggestionOutcome(status="failed", reason="publish_failed")
    record_offer(task.id, task_run.team_id, run_id=task_run.id, turn_index=turn_index, kind=verdict.offer.value)
    return TurnSuggestionOutcome(status="emitted", reason=verdict.offer.value)


def resolve_turn_suggestion(
    task_id: str, team_id: int, *, turn_index: int, resolution: TurnSuggestionResolution
) -> bool:
    """Record a dismissed or accepted card and write the outcome into its run's stream.

    The stream frame is also appended to the run's log, so a reloaded thread replays it after the
    card frame and keeps the card hidden. Returns ``False`` when that turn got no card.
    """
    offer = resolve_offer(task_id, team_id, turn_index=turn_index, resolution=resolution)
    if offer is None:
        return False
    publish_task_run_stream_notification(
        offer.run_id,
        task_id,
        team_id,
        TURN_SUGGESTION_RESOLVED_METHOD,
        {"turnIndex": turn_index, "outcome": resolution.value},
    )
    return True
