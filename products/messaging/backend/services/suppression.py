from django.db.models import F, QuerySet
from django.db.models.functions import Coalesce, Now
from django.utils import timezone

from products.messaging.backend.models.message_suppression import MessageSuppression, SuppressionSource


def active_suppressions(team_id: int, search: str | None) -> QuerySet[MessageSuppression]:
    suppressions = MessageSuppression.objects.for_team(team_id).filter(suppressed=True, deleted=False)
    if search:
        suppressions = suppressions.filter(identifier__icontains=search)
    return suppressions.order_by("-updated_at")


def add_manual_suppression(team_id: int, identifier: str, created_by_id: int | None) -> tuple[MessageSuppression, bool]:
    suppression, created = MessageSuppression.objects.for_team(team_id).get_or_create(
        team_id=team_id,
        identifier=identifier,
        defaults={
            "created_by_id": created_by_id,
            "source": SuppressionSource.MANUAL,
            "suppressed": True,
            "suppressed_at": timezone.now(),
            "reason": "Manually added",
        },
    )

    if not created:
        # Re-suppress (and un-delete) an existing row, e.g. one that had only been counting
        # bounces or was previously removed. Coalesce lets Postgres preserve an existing
        # suppressed_at atomically, so two concurrent add_suppression calls can't both compute
        # their own now() and overwrite each other.
        MessageSuppression.objects.for_team(team_id).filter(pk=suppression.pk).update(
            suppressed=True,
            suppressed_at=Coalesce(F("suppressed_at"), Now()),
            source=SuppressionSource.MANUAL,
            reason="Manually added",
            deleted=False,
            updated_at=Now(),
        )
        suppression.refresh_from_db()

    return suppression, created


def remove_suppression(team_id: int, identifier: str) -> bool:
    # Soft-delete and un-suppress. Reset the bounce counter so a previously-dead address that
    # a user deliberately re-enables starts from a clean slate. `source` is reset to BOUNCE so
    # a future auto-suppression can re-suppress this row — the node upserts skip rows with
    # source='MANUAL' (to protect user-managed entries), so a removed MANUAL row would otherwise
    # be permanently invisible to the bounce-driven write path.
    updated = (
        MessageSuppression.objects.for_team(team_id)
        .filter(identifier=identifier)
        .update(
            suppressed=False,
            deleted=True,
            transient_bounce_count=0,
            source=SuppressionSource.BOUNCE,
            updated_at=timezone.now(),
        )
    )
    return bool(updated)
