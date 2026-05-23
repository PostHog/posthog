"""Webhook adapter protocol — shared shape across all ingestion sources."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Protocol, runtime_checkable

if TYPE_CHECKING:
    from ...facade.contracts import CreateMentionInput
    from ...models import MentionSource


@runtime_checkable
class WebhookAdapter(Protocol):
    """Translates a source-specific webhook payload into CreateMentionInput records.

    Implementations must:
    - declare ``kind`` matching a ``SourceKind`` enum value
    - be stateless (instantiated per-request)
    - never raise on unknown / extra payload fields — degrade gracefully so
      a schema bump upstream doesn't take down ingestion

    Future adapters needing request-level verification (HMAC signature, etc.)
    can add a ``verify(self, request, source)`` hook here.
    """

    kind: ClassVar[str]

    def to_create_inputs(
        self,
        payload: dict,
        source: "MentionSource",
    ) -> list["CreateMentionInput"]: ...
