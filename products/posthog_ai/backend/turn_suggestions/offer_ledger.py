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
    TASK_MISSING = "task_missing"


@frozen
class OfferRecord:
    turn_index: int
    run_id: str
    kind: str
    status: OfferStatus

    def to_json(self) -> dict[str, Any]:
        return {"turn_index": self.turn_index, "run_id": self.run_id, "kind": self.kind, "status": self.status.value}


@frozen
class OfferLedger:
    offers: tuple[OfferRecord, ...] = ()
    muted: bool = False
    last_classified_turn: int = -1

    @classmethod
    def from_json(cls, raw: Any) -> "OfferLedger":
        if not isinstance(raw, dict):
            return cls()
        offers = tuple(
            OfferRecord(
                turn_index=entry["turn_index"],
                run_id=str(entry["run_id"]),
                kind=str(entry["kind"]),
                status=OfferStatus(entry["status"]),
            )
            for entry in raw.get("offers", [])
            if isinstance(entry, dict) and isinstance(entry.get("turn_index"), int)
        )
        last_classified_turn = raw.get("last_classified_turn")
        return cls(
            offers=offers,
            muted=raw.get("muted") is True,
            last_classified_turn=last_classified_turn if isinstance(last_classified_turn, int) else -1,
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "offers": [offer.to_json() for offer in self.offers],
            "muted": self.muted,
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
            return ledger.to_json(), refusal
        return replace(ledger, last_classified_turn=turn_index).to_json(), True

    result = update_task_state_entry(task_id, team_id, STATE_KEY, claim)
    if result is None:
        return ClaimRefusal.TASK_MISSING
    return None if result is True else result


def record_offer(task_id: UUID | str, team_id: int, *, run_id: UUID | str, turn_index: int, kind: str) -> None:
    offer = OfferRecord(turn_index=turn_index, run_id=str(run_id), kind=kind, status=OfferStatus.OFFERED)

    def append(raw: Any) -> tuple[Any, None]:
        ledger = OfferLedger.from_json(raw)
        return replace(ledger, offers=(*ledger.offers, offer)).to_json(), None

    update_task_state_entry(task_id, team_id, STATE_KEY, append)


def resolve_offer(
    task_id: UUID | str, team_id: int, *, turn_index: int, resolution: TurnSuggestionResolution
) -> OfferRecord | None:
    """Record what the user did with the card of ``turn_index``. A dismissal mutes the conversation.

    Returns the updated offer, or ``None`` when that turn got no card.
    """
    status = OfferStatus(resolution.value)

    def resolve(raw: Any) -> tuple[Any, OfferRecord | None]:
        ledger = OfferLedger.from_json(raw)
        target = next((offer for offer in ledger.offers if offer.turn_index == turn_index), None)
        if target is None:
            return ledger.to_json(), None
        resolved = replace(target, status=status)
        offers = tuple(resolved if offer is target else offer for offer in ledger.offers)
        muted = ledger.muted or status == OfferStatus.DISMISSED
        return replace(ledger, offers=offers, muted=muted).to_json(), resolved

    return update_task_state_entry(task_id, team_id, STATE_KEY, resolve)
