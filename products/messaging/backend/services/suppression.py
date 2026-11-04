from django.db.models import F, QuerySet
from django.db.models.functions import Coalesce, Now
from django.utils import timezone

from posthog.models.scoping.manager import resolve_effective_team_id

from products.messaging.backend.models.email_hard_bounce import EmailHardBounce
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


IMPORTED_SUPPRESSION_REASONS: dict[SuppressionSource, str] = {
    SuppressionSource.BOUNCE: "Imported (bounced)",
    SuppressionSource.COMPLAINT: "Imported (spam complaint)",
    SuppressionSource.MANUAL: "Imported (manually suppressed)",
}


def bulk_add_suppressions(
    team_id: int, sources_by_identifier: dict[str, SuppressionSource], created_by_id: int | None
) -> int:
    """Suppress the identifiers that have no row yet, and return how many rows it added.

    An existing row is left alone. It can be a manual entry, an address someone removed from the list on purpose,
    or a row the bounce feedback already manages.
    """
    # bulk_create skips the save() that moves a child environment's rows to its parent project.
    team_id = resolve_effective_team_id(team_id)
    suppressions = MessageSuppression.objects.for_team(team_id, canonical=True)
    existing = set(suppressions.filter(identifier__in=list(sources_by_identifier)).values_list("identifier", flat=True))
    now = timezone.now()
    new_rows = [
        MessageSuppression(
            team_id=team_id,
            identifier=identifier,
            source=source,
            reason=IMPORTED_SUPPRESSION_REASONS[source],
            suppressed=True,
            suppressed_at=now,
            # A provider lists a bounced address only when it can't receive mail, so it blocks transactional
            # email the way our own hard bounces do.
            hard_bounced_at=now if source == SuppressionSource.BOUNCE else None,
            created_by_id=created_by_id,
        )
        for identifier, source in sources_by_identifier.items()
        if identifier not in existing
    ]
    # ignore_conflicts covers an address the bounce feedback inserts between the read above and this write.
    suppressions.bulk_create(new_rows, ignore_conflicts=True)
    return len(new_rows)


def remove_suppression(team_id: int, identifier: str) -> bool:
    # Soft-delete and un-suppress. Reset the bounce counter and the hard-bounce mark so a
    # previously-dead address that a user deliberately re-enables starts from a clean slate. The reason is cleared too,
    # because the node writes treat a BOUNCE row with a legacy hard-bounce reason as hard-bounced, and the next soft
    # bounce or complaint would set the mark again. `source` is reset to BOUNCE so
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
            hard_bounced_at=None,
            reason=None,
            source=SuppressionSource.BOUNCE,
            updated_at=timezone.now(),
        )
    )
    return bool(updated)


def add_global_hard_bounces(emails: list[str]) -> None:
    """Add addresses to the global hard-bounce list that every team's sends skip. Keeps existing entries as they are."""
    identifiers = sorted({email.strip().lower() for email in emails if email.strip()})
    now = timezone.now()
    # An existing row came from a real bounce and carries better times, so it wins.
    EmailHardBounce.objects.bulk_create(
        [EmailHardBounce(email=email, first_bounced_at=now, last_bounced_at=now) for email in identifiers],
        ignore_conflicts=True,
    )
