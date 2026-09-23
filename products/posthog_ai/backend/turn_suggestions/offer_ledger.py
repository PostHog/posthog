"""The record of the turn suggestions one conversation received, kept in the task's state.

It lives in Postgres rather than Redis because it decides whether a conversation gets another card
and whether a dismissed or accepted card stays hidden after a reload. An evicted Redis key would
quietly bring both back.
"""

from dataclasses import replace
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from django.db import models

from posthog.dataclasses import frozen

from products.tasks.backend.facade.api import read_task_state_entry, update_task_state_entry

STATE_KEY = "turn_suggestions"

# A second offer exists for the case where the first one was superseded by the next message.
MAX_OFFERS_PER_CONVERSATION = 2


class OfferStatus(models.TextChoices):
    OFFERED = "offered", "Offered"
    DISMISSED = "dismissed", "Dismissed"
    ACCEPTED = "accepted", "Accepted"


class TurnSuggestionResolution(models.TextChoices):
    DISMISSED = "dismissed", "Dismissed"
    ACCEPTED = "accepted", "Accepted"


class ClaimRefusal(StrEnum):
    MUTED = "dismissed"
    BUDGET_SPENT = "offer_budget_spent"
    FOLLOWS_AN_OFFER = "follows_an_offer"
    ALREADY_CLASSIFIED = "already_classified"
    SUPERSEDED = "superseded"
    TASK_MISSING = "task_missing"


@frozen
class OfferRecord:
    turn_index: int
    run_id: str
    kind: str
    status: OfferStatus

    def to_json(self) -> dict[str, Any]:
        return {"turn_index": self.turn_index, "run_id": self.run_id, "kind": self.kind, "status": self.status.value}

    @classmethod
    def from_json(cls, raw: Any) -> "OfferRecord | None":
        if not isinstance(raw, dict) or not isinstance(raw.get("turn_index"), int):
            return None
        run_id, kind, status = raw.get("run_id"), raw.get("kind"), raw.get("status")
        if not isinstance(run_id, str) or not isinstance(kind, str) or status not in OfferStatus.values:
            return None
        return cls(turn_index=raw["turn_index"], run_id=run_id, kind=kind, status=OfferStatus(status))


@frozen
class OfferLedger:
    offers: tuple[OfferRecord, ...] = ()
    last_classified_turn: int = -1

    @property
    def muted(self) -> bool:
        """A dismissed card mutes the rest of the conversation."""
        return any(offer.status == OfferStatus.DISMISSED for offer in self.offers)

    def offer_at(self, turn_index: int) -> OfferRecord | None:
        return next((offer for offer in self.offers if offer.turn_index == turn_index), None)

    def with_status(self, target: OfferRecord, status: OfferStatus) -> "tuple[OfferLedger, OfferRecord]":
        updated = replace(target, status=status)
        return replace(self, offers=tuple(updated if offer is target else offer for offer in self.offers)), updated

    @classmethod
    def from_json(cls, raw: Any) -> "OfferLedger":
        if not isinstance(raw, dict):
            return cls()
        raw_offers = raw.get("offers")
        parsed = (OfferRecord.from_json(entry) for entry in raw_offers) if isinstance(raw_offers, list) else ()
        offers = tuple(offer for offer in parsed if offer is not None)
        last_classified_turn = raw.get("last_classified_turn")
        return cls(
            offers=offers,
            last_classified_turn=last_classified_turn if isinstance(last_classified_turn, int) else -1,
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "offers": [offer.to_json() for offer in self.offers],
            "last_classified_turn": self.last_classified_turn,
        }

    def refusal(self, turn_index: int | None = None) -> ClaimRefusal | None:
        """Why the conversation gets no card, checked before ``turn_index`` is known when it is ``None``."""
        if self.muted:
            return ClaimRefusal.MUTED
        if len(self.offers) >= MAX_OFFERS_PER_CONVERSATION:
            return ClaimRefusal.BUDGET_SPENT
        if turn_index is None:
            return None
        if any(offer.turn_index == turn_index - 1 for offer in self.offers):
            return ClaimRefusal.FOLLOWS_AN_OFFER
        if turn_index <= self.last_classified_turn:
            return ClaimRefusal.ALREADY_CLASSIFIED
        return None


def read_ledger(task_id: UUID | str, team_id: int) -> OfferLedger:
    return OfferLedger.from_json(read_task_state_entry(task_id, team_id, STATE_KEY))


def claim_turn(task_id: UUID | str, team_id: int, turn_index: int) -> ClaimRefusal | None:
    """Claim ``turn_index`` for classification, or say why it gets no card.

    The check and the claim share one row lock, so two reports of the same turn end in one claim.
    """

    def claim(raw: Any) -> tuple[Any, ClaimRefusal | Literal[True]]:
        ledger = OfferLedger.from_json(raw)
        refusal = ledger.refusal(turn_index)
        if refusal is not None:
            return raw, refusal
        return replace(ledger, last_classified_turn=turn_index).to_json(), True

    result = update_task_state_entry(task_id, team_id, STATE_KEY, claim)
    if result is None:
        return ClaimRefusal.TASK_MISSING
    return None if result is True else result


def record_offer(
    task_id: UUID | str, team_id: int, *, run_id: UUID | str, turn_index: int, kind: str
) -> ClaimRefusal | None:
    """Record the card of ``turn_index`` before it is published, or say why it must not be.

    A later turn that claimed classification while this one was drafting supersedes it. The card
    would arrive under a turn the thread already moved past, and it must not hold back the card of
    the later turn. The check shares the row lock with ``claim_turn``, so of two consecutive turns
    only one gets a card. The mute and the cap are checked again, because a dismissal can land
    while this turn drafts.
    """
    offer = OfferRecord(turn_index=turn_index, run_id=str(run_id), kind=kind, status=OfferStatus.OFFERED)

    def append(raw: Any) -> tuple[Any, ClaimRefusal | Literal[True]]:
        ledger = OfferLedger.from_json(raw)
        if ledger.last_classified_turn != turn_index:
            return raw, ClaimRefusal.SUPERSEDED
        refusal = ledger.refusal()
        if refusal is not None:
            return raw, refusal
        return replace(ledger, offers=(*ledger.offers, offer)).to_json(), True

    result = update_task_state_entry(task_id, team_id, STATE_KEY, append)
    if result is None:
        return ClaimRefusal.TASK_MISSING
    return None if result is True else result


def withdraw_offer(task_id: UUID | str, team_id: int, *, turn_index: int) -> None:
    """Drop the recorded card of ``turn_index`` when it never reached the thread, so it spends no budget."""

    def remove(raw: Any) -> tuple[Any, None]:
        ledger = OfferLedger.from_json(raw)
        offers = tuple(offer for offer in ledger.offers if offer.turn_index != turn_index)
        if len(offers) == len(ledger.offers):
            return raw, None
        return replace(ledger, offers=offers).to_json(), None

    update_task_state_entry(task_id, team_id, STATE_KEY, remove)


def resolve_offer(
    task_id: UUID | str, team_id: int, *, turn_index: int, resolution: TurnSuggestionResolution
) -> OfferRecord | None:
    """Record what the user did with the card of ``turn_index``. A dismissal mutes the conversation.

    Returns the updated offer, or ``None`` when that turn got no card or its card was already
    resolved. The first outcome stands, so a dismissal from another tab cannot overwrite an accept.
    """
    status = OfferStatus(resolution.value)

    def resolve(raw: Any) -> tuple[Any, OfferRecord | None]:
        ledger = OfferLedger.from_json(raw)
        target = ledger.offer_at(turn_index)
        if target is None or target.status != OfferStatus.OFFERED:
            return raw, None
        resolved_ledger, resolved = ledger.with_status(target, status)
        return resolved_ledger.to_json(), resolved

    return update_task_state_entry(task_id, team_id, STATE_KEY, resolve)


def reopen_offer(task_id: UUID | str, team_id: int, *, turn_index: int) -> None:
    """Undo the resolution of the card of ``turn_index`` when its outcome never reached the run's log.

    A reload replays the card from the log, so the ledger must not keep the card hidden or the
    conversation muted when the log still shows the card as open.
    """

    def reopen(raw: Any) -> tuple[Any, None]:
        ledger = OfferLedger.from_json(raw)
        target = ledger.offer_at(turn_index)
        if target is None or target.status == OfferStatus.OFFERED:
            return raw, None
        return ledger.with_status(target, OfferStatus.OFFERED)[0].to_json(), None

    update_task_state_entry(task_id, team_id, STATE_KEY, reopen)
