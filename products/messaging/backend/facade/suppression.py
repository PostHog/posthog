"""The email suppression list: addresses a team's sends skip."""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from posthog.dataclasses import frozen

from products.messaging.backend.models.message_suppression import MessageSuppression, SuppressionSource
from products.messaging.backend.services import suppression as suppression_service
from products.messaging.backend.services.lazy_list import LazyList

SUPPRESSION_SOURCE_CHOICES: list[tuple[str, str]] = list(SuppressionSource.choices)


@frozen
class Suppression:
    id: UUID
    identifier: str
    source: str
    reason: str | None
    transient_bounce_count: int
    last_bounce_at: datetime | None
    last_bounce_diagnostic: str | None
    suppressed: bool
    suppressed_at: datetime | None
    created_at: datetime
    updated_at: datetime


@frozen
class AddedSuppression:
    suppression: Suppression
    created: bool


def _to_contract(row: MessageSuppression) -> Suppression:
    return Suppression(
        id=row.id,
        identifier=row.identifier,
        source=row.source,
        reason=row.reason,
        transient_bounce_count=row.transient_bounce_count,
        last_bounce_at=row.last_bounce_at,
        last_bounce_diagnostic=row.last_bounce_diagnostic,
        suppressed=row.suppressed,
        suppressed_at=row.suppressed_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def list_active_suppressions(team_id: int, search: str | None) -> Sequence[Suppression]:
    """Actively suppressed addresses, most recently updated first. Sizing is a COUNT, and a slice reads one page."""
    return LazyList(suppression_service.active_suppressions(team_id, search), _to_contract)


def add_manual_suppression(team_id: int, identifier: str, created_by_id: int | None) -> AddedSuppression:
    """Suppress `identifier`, or re-suppress and un-delete an existing row for it."""
    row, created = suppression_service.add_manual_suppression(team_id, identifier, created_by_id)
    return AddedSuppression(suppression=_to_contract(row), created=created)


def remove_suppression(team_id: int, identifier: str) -> bool:
    """Un-suppress `identifier`. Returns False when the team has no row for it."""
    return suppression_service.remove_suppression(team_id, identifier)
