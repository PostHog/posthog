"""The verdict a finished PostHog AI turn gets: which follow-up to offer, and the draft that offer needs."""

from collections.abc import Mapping
from enum import StrEnum
from typing import ClassVar

from posthog.dataclasses import frozen

from products.posthog_ai.backend.turn_suggestions.transcript import ErrorIssueRef, SavedInsightRef


class TurnIntent(StrEnum):
    METRIC_STATE = "metric_state"
    DIAGNOSTIC = "diagnostic"
    ACTION = "action"
    KNOWLEDGE = "knowledge"
    OTHER = "other"


class OfferKind(StrEnum):
    NONE = "none"
    SCOUT = "scout"
    NOTEBOOK = "notebook"
    ALERT = "alert"
    SUBSCRIPTION = "subscription"
    ERROR_ALERT = "error_alert"


class ScoutMode(StrEnum):
    REPORT = "report"
    WATCH = "watch"
    INVESTIGATE = "investigate"
    DIGEST = "digest"


class ScoutCadence(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"


class NotebookTemplate(StrEnum):
    CONVERSATION = "conversation"
    INCIDENT = "incident"


class AlertDirection(StrEnum):
    DECREASE = "decrease"
    INCREASE = "increase"


@frozen
class ScoutDraft:
    KIND: ClassVar[OfferKind] = OfferKind.SCOUT
    WIRE_KEY: ClassVar[str] = "scout"

    mode: ScoutMode
    display_name: str
    description: str
    body: str
    cadence: ScoutCadence

    def to_params(self) -> dict:
        return {
            "mode": self.mode.value,
            "displayName": self.display_name,
            "description": self.description,
            "body": self.body,
            "cadence": self.cadence.value,
        }


@frozen
class IncidentOutline:
    timeline: str
    cause: str
    fix: str


@frozen
class NotebookDraft:
    KIND: ClassVar[OfferKind] = OfferKind.NOTEBOOK
    WIRE_KEY: ClassVar[str] = "notebook"

    title: str
    summary: str
    incident: IncidentOutline | None

    def to_params(self) -> dict:
        incident = self.incident
        return {
            "title": self.title,
            "summary": self.summary,
            "incident": (
                {"timeline": incident.timeline, "cause": incident.cause, "fix": incident.fix} if incident else None
            ),
        }


@frozen
class AlertDraft:
    KIND: ClassVar[OfferKind] = OfferKind.ALERT
    WIRE_KEY: ClassVar[str] = "alert"

    insight: SavedInsightRef
    direction: AlertDirection
    change_percent: int

    def to_params(self) -> dict:
        return {**self.insight.to_params(), "direction": self.direction.value, "changePercent": self.change_percent}


@frozen
class SubscriptionDraft:
    KIND: ClassVar[OfferKind] = OfferKind.SUBSCRIPTION
    WIRE_KEY: ClassVar[str] = "subscription"

    insight: SavedInsightRef
    cadence: ScoutCadence

    def to_params(self) -> dict:
        return {**self.insight.to_params(), "cadence": self.cadence.value}


@frozen
class ErrorAlertDraft:
    KIND: ClassVar[OfferKind] = OfferKind.ERROR_ALERT
    WIRE_KEY: ClassVar[str] = "errorAlert"

    issue: ErrorIssueRef

    def to_params(self) -> dict:
        return {"issueId": self.issue.issue_id, "issueName": self.issue.name}


Draft = ScoutDraft | NotebookDraft | AlertDraft | SubscriptionDraft | ErrorAlertDraft


@frozen
class TurnVerdict:
    intent: TurnIntent
    show_probability: float
    picked: OfferKind
    offer_probabilities: Mapping[str, float]
    title: str
    description: str
    draft: Draft | None

    @property
    def offer(self) -> OfferKind:
        return self.draft.KIND if self.draft is not None else OfferKind.NONE
