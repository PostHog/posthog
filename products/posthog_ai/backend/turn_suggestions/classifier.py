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
from products.posthog_ai.backend.turn_suggestions.transcript import TurnTranscript, truncate_text
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

_NAME_IN_COPY_LIMIT = 50


@frozen
class CardCopy:
    title: str
    description: str


def pick_offer(judgment: TurnJudgment, available: frozenset[OfferKind]) -> OfferKind:
    """The offer the judgment supports, or ``NONE`` when it does not clear the bar for showing one."""
    offer = judgment.offer
    if judgment.show_probability < SHOW_THRESHOLD or offer not in available:
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


def _build_draft(
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


def _named(name: str, fallback: str) -> str:
    return truncate_text(name, _NAME_IN_COPY_LIMIT) if name.strip() else fallback


def card_copy(draft: Draft) -> CardCopy:
    match draft:
        case ScoutDraft(mode=ScoutMode.WATCH, cadence=cadence):
            return CardCopy(
                title="Tell me when this changes",
                description=f"A scout checks this {_every(cadence)} and posts to Slack only when the number crosses a threshold.",
            )
        case ScoutDraft(mode=ScoutMode.INVESTIGATE, cadence=cadence):
            return CardCopy(
                title="Rerun this investigation if it happens again",
                description=f"A scout checks the metric {_every(cadence)} and repeats these steps when it dips.",
            )
        case ScoutDraft(mode=ScoutMode.DIGEST, cadence=cadence):
            return CardCopy(
                title="Get these metrics in one Slack post",
                description=f"A scout covers the metrics from this conversation in one post {_every(cadence)}.",
            )
        case ScoutDraft(cadence=cadence):
            return CardCopy(
                title=f"Get this {_every(cadence)} in Slack",
                description=f"A scout reruns this analysis {_every(cadence)} and posts the numbers and what changed.",
            )
        case NotebookDraft(incident=None):
            return CardCopy(
                title="Save this as a notebook",
                description="Keep this conversation and its queries as cells you can rerun.",
            )
        case NotebookDraft():
            return CardCopy(
                title="Save this as an incident writeup",
                description="Keep the timeline, cause and fix next to the queries that found them.",
            )
        case AlertDraft(insight=insight, direction=direction, change_percent=change_percent):
            verb = "drops" if direction == AlertDirection.DECREASE else "rises"
            return CardCopy(
                title=f"Alert me when this {verb}",
                description=f"Get a Slack message when {_named(insight.name, 'this insight')} {verb} by {change_percent}% or more.",
            )
        case SubscriptionDraft(insight=insight, cadence=cadence):
            return CardCopy(
                title=f"Send this chart to Slack {_every(cadence)}",
                description=f"Get {_named(insight.name, 'this chart')} in Slack {_every(cadence)}.",
            )
        case ErrorAlertDraft(issue=issue):
            return CardCopy(
                title="Tell me if this error comes back",
                description=f"Get a Slack message if {_named(issue.name, 'this issue')} reopens.",
            )


def classify_turn(
    transcript: TurnTranscript, *, team_id: int, today: date, available: frozenset[OfferKind]
) -> TurnVerdict | None:
    """``None`` means the judgment failed. A verdict whose draft is ``None`` offers nothing, either
    because the policy picked nothing or because drafting the picked offer failed."""
    judgment = judge_turn(transcript, available=available)
    if judgment is None:
        return None
    picked = pick_offer(judgment, available)
    draft = _build_draft(picked, judgment, transcript, team_id=team_id, today=today)
    copy = card_copy(draft) if draft is not None else CardCopy(title="", description="")
    return TurnVerdict(
        intent=judgment.intent,
        show_probability=judgment.show_probability,
        picked=picked,
        offer_probabilities=judgment.offer_probabilities,
        title=copy.title,
        description=copy.description,
        draft=draft,
    )
