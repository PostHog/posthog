"""The record of the turn suggestions one conversation received, kept in the task's state.

It lives in Postgres rather than Redis because it decides whether a conversation gets another card
and whether a dismissed or accepted card stays hidden after a reload. An evicted Redis key would
quietly bring both back.
"""

from collections.abc import Callable
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

    @property
    def resolved_turns(self) -> tuple[int, ...]:
        return tuple(offer.turn_index for offer in self.offers if offer.status != OfferStatus.OFFERED)

    def offer_at(self, turn_index: int) -> OfferRecord | None:
        return next((offer for offer in self.offers if offer.turn_index == turn_index), None)

    def with_status(self, target: OfferRecord, status: OfferStatus) -> "OfferLedger":
        updated = replace(target, status=status)
        return replace(self, offers=tuple(updated if offer is target else offer for offer in self.offers))

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


def _update_ledger[R](
    task_id: UUID | str, team_id: int, update: Callable[[OfferLedger], tuple[OfferLedger | None, R]]
) -> R | None:
    """Row-locked update of the ledger. ``update`` returns ``None`` in place of a ledger to skip the
    write. Returns ``None`` without calling ``update`` when the task does not exist."""

    def update_raw(raw: Any) -> tuple[Any, R]:
        ledger, result = update(OfferLedger.from_json(raw))
        return (raw if ledger is None else ledger.to_json()), result

    return update_task_state_entry(task_id, team_id, STATE_KEY, update_raw)


def _claim(
    task_id: UUID | str, team_id: int, decide: Callable[[OfferLedger], OfferLedger | ClaimRefusal]
) -> ClaimRefusal | None:
    """Store the ledger ``decide`` returns, or return the refusal it gives instead."""

    def update(ledger: OfferLedger) -> tuple[OfferLedger | None, ClaimRefusal | Literal[True]]:
        decision = decide(ledger)
        return (None, decision) if isinstance(decision, ClaimRefusal) else (decision, True)

    result = _update_ledger(task_id, team_id, update)
    if result is None:
        return ClaimRefusal.TASK_MISSING
    return None if result is True else result


def claim_turn(task_id: UUID | str, team_id: int, turn_index: int) -> ClaimRefusal | None:
    """Claim ``turn_index`` for classification, or say why it gets no card.

    The check and the claim share one row lock, so two reports of the same turn end in one claim.
    """

    def claim(ledger: OfferLedger) -> OfferLedger | ClaimRefusal:
        refusal = ledger.refusal(turn_index)
        if refusal is not None:
            return refusal
        return replace(ledger, last_classified_turn=turn_index)

    return _claim(task_id, team_id, claim)


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

    def append(ledger: OfferLedger) -> OfferLedger | ClaimRefusal:
        if ledger.last_classified_turn != turn_index:
            return ClaimRefusal.SUPERSEDED
        refusal = ledger.refusal()
        if refusal is not None:
            return refusal
        return replace(ledger, offers=(*ledger.offers, offer))

    return _claim(task_id, team_id, append)


def withdraw_offer(task_id: UUID | str, team_id: int, *, turn_index: int) -> None:
    """Drop the recorded card of ``turn_index`` when it never reached the thread, so it spends no budget."""

    def remove(ledger: OfferLedger) -> tuple[OfferLedger | None, None]:
        offers = tuple(offer for offer in ledger.offers if offer.turn_index != turn_index)
        if len(offers) == len(ledger.offers):
            return None, None
        return replace(ledger, offers=offers), None

    _update_ledger(task_id, team_id, remove)


def resolve_offer(
    task_id: UUID | str, team_id: int, *, turn_index: int, resolution: TurnSuggestionResolution
) -> OfferRecord | None:
    """Record what the user did with the card of ``turn_index``. A dismissal mutes the conversation.

    Returns the updated offer, or ``None`` when that turn got no card or its card was already
    resolved. The first outcome stands, so a dismissal from another tab cannot overwrite an accept.
    """
    status = OfferStatus(resolution.value)

    def resolve(ledger: OfferLedger) -> tuple[OfferLedger | None, OfferRecord | None]:
        target = ledger.offer_at(turn_index)
        if target is None or target.status != OfferStatus.OFFERED:
            return None, None
        resolved = ledger.with_status(target, status)
        return resolved, resolved.offer_at(turn_index)

    return _update_ledger(task_id, team_id, resolve)
