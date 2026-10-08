"""Data types other products exchange with Replay Vision through the facade."""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

RejectionKind = Literal["not_found", "consent", "invalid"]


@dataclass(frozen=True, kw_only=True)
class StartedObservationRequest:
    request_id: UUID
    # "completed" when nothing could start, so the caller has nothing to wait for.
    status: Literal["running", "completed"]
    # False when the idempotency key matched an earlier request and nothing new started.
    created: bool


class ObservationRequestRejected(Exception):
    def __init__(self, detail: str, kind: RejectionKind) -> None:
        super().__init__(detail)
        self.detail = detail
        self.kind = kind
