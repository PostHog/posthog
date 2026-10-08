"""Data types other products exchange with Replay Vision through the facade."""

from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

RejectionKind = Literal["not_found", "consent", "invalid", "forbidden"]

# The longest session recording id a scan accepts.
MAX_SESSION_ID_LENGTH = 128


@dataclass(frozen=True, kw_only=True)
class StartedObservationRequest:
    request_id: UUID
    # "completed" when every session already settled, for example because each one was scanned before.
    status: Literal["running", "completed"]
    # False when the idempotency key matched an earlier request and nothing new started.
    created: bool
    # The per-session answers, set only when the request already settled, so the caller has nothing to wait for.
    result: dict[str, Any] | None = None


class ObservationRequestRejected(Exception):
    def __init__(self, detail: str, kind: RejectionKind) -> None:
        super().__init__(detail)
        self.detail = detail
        self.kind = kind
