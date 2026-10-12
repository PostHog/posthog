"""Decides which follow-up, if any, a finished PostHog AI turn gets, and builds the offer.

Two steps. Jev judges the turn in one fast request (see ``judgment.py``), and the policy below turns
those probabilities into at most one offer. Only a scout or a notebook then needs generated text,
which a language model writes in a second call (see ``drafter.py``). Alerts, subscriptions and error
alerts are built from the judgment alone, so those turns never wait on a language model.
"""

from datetime import date

import structlog

from posthog.dataclasses import frozen

from products.posthog_ai.backend.turn_suggestions.drafter import draft_notebook, draft_scout
from products.posthog_ai.backend.turn_suggestions.judgment import TurnJudgment, judge_turn
from products.posthog_ai.backend.turn_suggestions.transcript import TurnTranscript
from products.posthog_ai.backend.turn_suggestions.verdict import (
    AlertDirection,
    AlertDraft,
    Draft,
    ErrorAlertDraft,
    NotebookDraft,
    OfferKind,
    ScoutCadence,
    ScoutDraft,
    ScoutMode,
    SubscriptionDraft,
    TurnVerdict,
)

logger = structlog.get_logger(__name__)

# Starting points to tune from the `posthog ai turn suggestion classified` events, which record the
# probabilities behind every decision.
SHOW_THRESHOLD = 0.5
ISSUE_RESOLVED_THRESHOLD = 0.5


@frozen
class CardCopy:
    title: str
    description: str


def pick_offer(
    judgment: TurnJudgment, available: frozenset[OfferKind], *, show_threshold: float = SHOW_THRESHOLD
) -> OfferKind:
    """The offer the judgment supports, or ``NONE`` when it does not clear the bar for showing one."""
    offer = judgment.offer
    if judgment.show_probability < show_threshold or offer not in available:
        return OfferKind.NONE
    match offer:
        case OfferKind.ALERT if judgment.insight is None or not judgment.insight.alertable:
            return OfferKind.NONE
        case OfferKind.SUBSCRIPTION if judgment.insight is None:
            return OfferKind.NONE
        # The alert fires on a reopen, so it only means something for an issue that is resolved.
        case OfferKind.ERROR_ALERT if (
            judgment.error_issue is None or judgment.issue_resolved_probability < ISSUE_RESOLVED_THRESHOLD
        ):
            return OfferKind.NONE
    return offer


def build_draft(
    offer: OfferKind, judgment: TurnJudgment, transcript: TurnTranscript, *, team_id: int, today: date
) -> Draft | None:
    match offer:
        case OfferKind.SCOUT:
            return draft_scout(
                transcript, team_id=team_id, today=today, mode=judgment.scout_mode, cadence=judgment.cadence
            )
        case OfferKind.NOTEBOOK:
            return draft_notebook(transcript, team_id=team_id, today=today, template=judgment.notebook_template)
        case OfferKind.ALERT if judgment.insight is not None:
            return AlertDraft(
                insight=judgment.insight,
                direction=judgment.alert_direction,
                change_percent=judgment.alert_change_percent,
            )
        case OfferKind.SUBSCRIPTION if judgment.insight is not None:
            return SubscriptionDraft(insight=judgment.insight, cadence=judgment.cadence)
        case OfferKind.ERROR_ALERT if judgment.error_issue is not None:
            return ErrorAlertDraft(issue=judgment.error_issue)
        case _:
            return None


def _every(cadence: ScoutCadence) -> str:
    return "every day" if cadence == ScoutCadence.DAILY else "every week"


def card_copy(draft: Draft) -> CardCopy:
    match draft:
        case ScoutDraft(mode=ScoutMode.WATCH, cadence=cadence):
            return CardCopy(
                title="Get a Slack message when this changes",
                description=f"A scout checks this {_every(cadence)}. It posts only when the number crosses a threshold.",
            )
        case ScoutDraft(mode=ScoutMode.INVESTIGATE, cadence=cadence):
            return CardCopy(
                title="Rerun this investigation when the metric drops",
                description=f"A scout checks the metric {_every(cadence)}. When it drops, the scout repeats these steps and posts what it finds.",
            )
        case ScoutDraft(mode=ScoutMode.DIGEST, cadence=cadence):
            return CardCopy(
                title="Get these metrics in one Slack post",
                description=f"A scout posts the metrics from this conversation to Slack {_every(cadence)}.",
            )
        case ScoutDraft(cadence=cadence):
            return CardCopy(
                title=f"Get this in Slack {_every(cadence)}",
                description=f"A scout runs this analysis again {_every(cadence)} and posts the results to Slack.",
            )
        case NotebookDraft(incident=None):
            return CardCopy(
                title="Save this conversation as a notebook",
                description="The notebook keeps the messages, and each query becomes a cell you can run again.",
            )
        case NotebookDraft():
            return CardCopy(
                title="Save this as an incident report",
                description="The notebook starts with the timeline, cause and fix, followed by the conversation and its queries.",
            )
        case AlertDraft(direction=direction):
            verb = "drops" if direction == AlertDirection.DECREASE else "rises"
            return CardCopy(
                title=f"Get an alert when this {verb}",
                description="The alert checks once a day, compares with the day before, and posts to Slack.",
            )
        case SubscriptionDraft(cadence=cadence):
            schedule = "every day at 9:00" if cadence == ScoutCadence.DAILY else "every Monday at 9:00"
            return CardCopy(
                title=f"Send this chart to Slack {_every(cadence)}",
                description=f"The chart posts to a Slack channel {schedule}.",
            )
        case ErrorAlertDraft():
            return CardCopy(
                title="Get an alert if this error comes back",
                description="Slack gets a message if this issue reopens after it was resolved.",
            )


def classify_turn(
    transcript: TurnTranscript, *, team_id: int, today: date, available: frozenset[OfferKind]
) -> TurnVerdict | None:
    """``None`` means the judgment failed. A verdict whose draft is ``None`` offers nothing, either
    because the policy picked nothing or because drafting the picked offer failed."""
    judgment = judge_turn(transcript, available=available, team_id=team_id)
    if judgment is None:
        return None
    picked = pick_offer(judgment, available)
    draft = build_draft(picked, judgment, transcript, team_id=team_id, today=today)
    return TurnVerdict(
        intent=judgment.intent,
        show_probability=judgment.show_probability,
        picked=picked,
        offer_probabilities=judgment.offer_probabilities,
        draft=draft,
    )
