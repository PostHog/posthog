"""Public contracts for protected, server-mediated draft pull request publication."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from posthog.dataclasses import frozen


@frozen
class DraftPublicationRequest:
    team_id: int
    caller_id: UUID
    staged_run_id: UUID
    logical_artifact_key: str
    commit_message: str
    pr_title: str
    pr_body: str
    starts_before: datetime
    expires_at: datetime


@frozen
class DraftPublicationResult:
    publication_id: UUID
    status: Literal["pending", "published", "unknown", "blocked", "revoked"]
    pr_number: int | None
    pr_url: str | None


class InvalidDraftPublicationError(ValueError):
    """Raised when a draft publication does not match its protected lifecycle binding."""


def reserve_draft_publication(input: DraftPublicationRequest) -> DraftPublicationResult:
    from products.tasks.backend.logic.services.publication_service import reserve_publication

    return reserve_publication(input)


def publish_draft_publication(*, team_id: int, caller_id: UUID, publication_id: UUID) -> DraftPublicationResult:
    from products.tasks.backend.logic.services.publication_service import publish_publication

    return publish_publication(team_id=team_id, caller_id=caller_id, publication_id=publication_id)


def get_draft_publication(*, team_id: int, caller_id: UUID, publication_id: UUID) -> DraftPublicationResult:
    from products.tasks.backend.logic.services.publication_service import get_publication

    return get_publication(team_id=team_id, caller_id=caller_id, publication_id=publication_id)


def revoke_draft_publication(*, team_id: int, caller_id: UUID, publication_id: UUID) -> bool:
    from products.tasks.backend.logic.services.publication_service import revoke_publication

    return revoke_publication(team_id=team_id, caller_id=caller_id, publication_id=publication_id)
