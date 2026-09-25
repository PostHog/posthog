"""Builds the end-of-turn suggestion for a sandbox PostHog AI conversation.

Runs off the request path once a turn completes. It checks the cheap gates first, reads the run's
stream, asks the classifier, and publishes a ``_posthog/turn_suggestion`` frame into the same
stream the thread renders from, so the card appears under the answer without the frontend polling.
"""

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

import structlog

from posthog.dataclasses import frozen
from posthog.ph_client import feature_enabled_or_false, ph_scoped_capture

from products.posthog_ai.backend.turn_suggestions.classifier import card_copy, classify_turn
from products.posthog_ai.backend.turn_suggestions.drafter import DRAFT_MODEL
from products.posthog_ai.backend.turn_suggestions.judgment import JUDGE_MODEL, judge_configured
from products.posthog_ai.backend.turn_suggestions.offer_ledger import (
    TurnSuggestionResolution,
    claim_turn,
    note_turn,
    read_ledger,
    record_offer,
    resolve_offer,
    withdraw_offer,
)
from products.posthog_ai.backend.turn_suggestions.transcript import TurnTranscript, build_turn_transcript
from products.posthog_ai.backend.turn_suggestions.verdict import OfferKind, TurnVerdict
from products.signals.backend.facade.api import scout_creation_available
from products.tasks.backend.facade.api import (
    TaskClientProvenance,
    get_latest_run_by_task,
    publish_task_run_stream_notification,
    read_task_run_history,
)
from products.tasks.backend.models import Task, TaskRun

if TYPE_CHECKING:
    from posthog.models.user import User

logger = structlog.get_logger(__name__)

TURN_SUGGESTIONS_FLAG = "posthog-ai-turn-suggestions"
TURN_SUGGESTION_METHOD = "_posthog/turn_suggestion"
TURN_SUGGESTION_RESOLVED_METHOD = "_posthog/turn_suggestion_resolved"

# Past this many log bytes the conversation gets no card: the fold holds every log in worker memory.
MAX_TRANSCRIPT_LOG_BYTES = 16 * 1024 * 1024

# The offers whose text a language model writes after the judgment picks them.
_DRAFTED_OFFERS = frozenset({OfferKind.SCOUT, OfferKind.NOTEBOOK})

OutcomeStatus = Literal["emitted", "skipped", "failed"]


@frozen
class TurnSuggestionOutcome:
    status: OutcomeStatus
    reason: str


def _skipped(reason: str) -> TurnSuggestionOutcome:
    return TurnSuggestionOutcome(status="skipped", reason=reason)


def _turn_suggestions_enabled(task_run: TaskRun, user: "User") -> bool:
    organization_id = str(task_run.team.organization_id)
    return feature_enabled_or_false(
        TURN_SUGGESTIONS_FLAG,
        str(user.distinct_id),
        groups={"organization": organization_id},
        group_properties={"organization": {"id": organization_id}},
        send_feature_flag_events=False,
    )


def _history_is_whole(task_run: TaskRun) -> bool:
    """Whether the resume chain the history reads reaches the conversation's first run.

    The chain walk stops after a fixed depth, and the thread reads the same chain. Past that depth
    turn indexes slide with every new run, so they no longer name one turn in the ledger.
    """
    oldest = task_run.get_resume_chain()[0]
    return not (oldest.state or {}).get("resume_from_run_id")


def _load_transcript(task_run: TaskRun) -> TurnTranscript | None:
    """Fold the whole resume chain, because the thread counts turns across it. Returns ``None``
    when the logs are over ``MAX_TRANSCRIPT_LOG_BYTES``."""
    entries = read_task_run_history(task_run.id, task_run.task_id, task_run.team_id, max_bytes=MAX_TRANSCRIPT_LOG_BYTES)
    return None if entries is None else build_turn_transcript(entries)


def _turn_has_substance(transcript: TurnTranscript) -> bool:
    """A notebook is only worth saving when the assistant actually queried something and answered."""
    return bool(transcript.tool_calls) and bool(transcript.assistant_text)


def available_offers(transcript: TurnTranscript, *, scouts_available: bool) -> frozenset[OfferKind]:
    """The offers this turn and project can act on. The classifier picks one of these, or shows nothing."""
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


def _suggestion_params(verdict: TurnVerdict, turn_index: int) -> dict | None:
    if verdict.draft is None:
        return None
    copy = card_copy(verdict.draft)
    return {
        "turnIndex": turn_index,
        "kind": verdict.picked.value,
        "intent": verdict.intent.value,
        "confidence": verdict.show_probability,
        "title": copy.title,
        "description": copy.description,
        verdict.draft.WIRE_KEY: verdict.draft.to_params(),
    }


def _capture_classified(
    task_run: TaskRun, user: "User", verdict: TurnVerdict | None, *, emitted: bool, turn_index: int
) -> None:
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
                    "offer": verdict.picked.value if verdict and verdict.draft else None,
                    "emitted": emitted,
                },
            )
    except Exception:
        # Analytics must not change the outcome of a suggestion that already reached the thread.
        logger.warning("posthog_ai_turn_suggestion_capture_failed", run_id=str(task_run.id), exc_info=True)


def generate_turn_suggestion(run_id: str, team_id: int) -> TurnSuggestionOutcome:
    try:
        task_run = TaskRun.objects.select_related("task__created_by", "team__organization").get(
            id=run_id, team_id=team_id
        )
    except TaskRun.DoesNotExist:
        return _skipped("run_missing")

    task = task_run.task
    if task.origin_product != Task.OriginProduct.POSTHOG_AI or task_run.mode != "interactive":
        return _skipped("not_posthog_ai_conversation")
    # Cards render only in the PostHog AI web app. Slack conversations carry the Slack origin and
    # fail the check above; PostHog Desktop ones carry the Desktop client provenance.
    if task.client_provenance == TaskClientProvenance.POSTHOG_DESKTOP:
        return _skipped("not_started_in_web")
    user = task.created_by
    if user is None:
        return _skipped("no_user")
    # The judgment and the drafter send conversation text to third-party AI services.
    if task_run.team.organization.is_ai_data_processing_approved is not True:
        return _skipped("ai_data_processing_not_approved")
    if not _turn_suggestions_enabled(task_run, user):
        return _skipped("flag_off")
    if not judge_configured():
        return _skipped("judge_not_configured")
    early_refusal = read_ledger(task.id, task_run.team_id).refusal()
    if early_refusal is not None:
        return _skipped(early_refusal.value)
    if not _history_is_whole(task_run):
        return _skipped("history_truncated")

    transcript = _load_transcript(task_run)
    if transcript is None:
        return _skipped("log_too_large")
    if not transcript.human_messages:
        return _skipped("no_user_message")
    turn_index = len(transcript.human_messages) - 1
    if not transcript.assistant_text and not transcript.tool_calls:
        # A follow-up sent during the settle wait shows here as an empty latest turn. Its own
        # completion classifies it, so it is only noted: a card still drafting for the previous
        # turn must not land under it.
        note_turn(task.id, task_run.team_id, turn_index)
        return _skipped("empty_turn")
    # Claimed before the turn can bail out, so a card still drafting for the previous turn sees
    # that the thread moved past it even when this turn offers nothing.
    refusal = claim_turn(task.id, task_run.team_id, turn_index)
    if refusal is not None:
        return _skipped(refusal.value)
    available = available_offers(
        transcript, scouts_available=scout_creation_available(team_id=task_run.team_id, user_id=user.id)
    )
    if not available:
        return _skipped("no_offers_available")

    verdict = classify_turn(transcript, team_id=task_run.team_id, today=datetime.now(UTC).date(), available=available)
    if verdict is None:
        _capture_classified(task_run, user, None, emitted=False, turn_index=turn_index)
        return TurnSuggestionOutcome(status="failed", reason="classifier_failed")

    params = _suggestion_params(verdict, turn_index)
    if params is None:
        _capture_classified(task_run, user, verdict, emitted=False, turn_index=turn_index)
        if verdict.picked != OfferKind.NONE:
            return TurnSuggestionOutcome(status="failed", reason="draft_failed")
        return _skipped(f"no_offer:{verdict.intent.value}")

    offer = verdict.picked.value
    # Record before publishing, so a next turn that completes while the frame is in flight already sees the card.
    record_refusal = record_offer(task.id, task_run.team_id, run_id=task_run.id, turn_index=turn_index, kind=offer)
    if record_refusal is not None:
        _capture_classified(task_run, user, verdict, emitted=False, turn_index=turn_index)
        return _skipped(record_refusal.value)
    # Publishing also appends to the run's S3 log, a rewrite of the whole log; the offer ledger is
    # what keeps that to a couple of times per conversation. Only a card in the log counts, because
    # the log is what a reload replays it from.
    emitted = publish_task_run_stream_notification(
        task_run.id, task_run.task_id, task_run.team_id, TURN_SUGGESTION_METHOD, params
    ).persisted
    _capture_classified(task_run, user, verdict, emitted=emitted, turn_index=turn_index)
    if not emitted:
        withdraw_offer(task.id, task_run.team_id, turn_index=turn_index)
        return TurnSuggestionOutcome(status="failed", reason="publish_failed")
    return TurnSuggestionOutcome(status="emitted", reason=offer)


def resolve_turn_suggestion(
    task_id: str, team_id: int, *, turn_index: int, resolution: TurnSuggestionResolution
) -> bool:
    """Record a dismissed or accepted card, and tell the conversation's other open tabs.

    The ledger is the one stored outcome: a reloaded thread reads it through
    ``turn_suggestion_state``. Returns ``False`` when that turn got no card or its card was already
    resolved.
    """
    offer = resolve_offer(task_id, team_id, turn_index=turn_index, resolution=resolution)
    if offer is None:
        return False
    # A warmed successor run can start before the next message, so a tab may stream a newer run
    # than the one that carried the card.
    latest_run = get_latest_run_by_task([task_id]).get(str(task_id))
    run_ids = {str(offer.run_id)} | ({str(latest_run.id)} if latest_run is not None else set())
    for run_id in sorted(run_ids):
        publish_task_run_stream_notification(
            run_id,
            task_id,
            team_id,
            TURN_SUGGESTION_RESOLVED_METHOD,
            {"turnIndex": turn_index, "outcome": resolution.value},
            persist=False,
        )
    return True


@frozen
class TurnSuggestionState:
    muted: bool
    resolved_turns: tuple[int, ...]


def turn_suggestion_state(task_id: str, team_id: int) -> TurnSuggestionState:
    ledger = read_ledger(task_id, team_id)
    return TurnSuggestionState(muted=ledger.muted, resolved_turns=ledger.resolved_turns)
