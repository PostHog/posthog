from django.db import transaction
from django.db.models import F, QuerySet, Value
from django.db.models.functions import Coalesce, Greatest, Least, Now
from django.utils import timezone

from products.messaging.backend.models.email_hard_bounce import GLOBAL_HARD_BOUNCE_MAX_HOLD, EmailHardBounce
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


class ComplaintConfirmationRequired(Exception):
    def __init__(self, identifiers: list[str]) -> None:
        super().__init__(f"Removing spam complaints needs confirmation: {', '.join(identifiers)}")
        self.identifiers = identifiers


def remove_suppressions(team_id: int, identifiers: list[str], confirm_complaints: bool) -> list[str]:
    """Remove `identifiers` from the team's list, and return the ones the team had a row for.

    Raises `ComplaintConfirmationRequired`, and removes nothing, when a spam complaint is among them unconfirmed.
    """
    with transaction.atomic():
        rows = MessageSuppression.objects.for_team(team_id)
        # The lock stops a complaint that lands during the check from being removed unconfirmed. A row inserted after
        # the lock is not checked, so only the locked rows are removed.
        locked = list(
            rows.filter(identifier__in=identifiers)
            .order_by("identifier")
            .select_for_update()
            .values_list("id", "identifier", "source", "suppressed", "deleted")
        )
        complaints = sorted(
            identifier
            for _, identifier, source, suppressed, deleted in locked
            if source == SuppressionSource.COMPLAINT and suppressed and not deleted
        )
        if complaints and not confirm_complaints:
            raise ComplaintConfirmationRequired(complaints)
        _remove(rows.filter(id__in=[row_id for row_id, *_ in locked]))
    return sorted(identifier for _, identifier, *_ in locked)


def _remove(rows: QuerySet[MessageSuppression]) -> None:
    # Soft-delete and un-suppress. Reset the bounce counter and the hard-bounce mark so a
    # previously-dead address that a user deliberately re-enables starts from a clean slate. The reason is cleared too,
    # because the node writes treat a BOUNCE row with a legacy hard-bounce reason as hard-bounced, and the next soft
    # bounce or complaint would set the mark again. `source` is reset to BOUNCE so
    # a future auto-suppression can re-suppress this row — the node upserts skip rows with
    # source='MANUAL' (to protect user-managed entries), so a removed MANUAL row would otherwise
    # be permanently invisible to the bounce-driven write path.
    rows.update(
        suppressed=False,
        deleted=True,
        transient_bounce_count=0,
        hard_bounced_at=None,
        reason=None,
        source=SuppressionSource.BOUNCE,
        updated_at=timezone.now(),
    )


def add_global_hard_bounces(emails: list[str]) -> None:
    """Hold each address on the global hard-bounce list, which every team's sends skip, for the longest hold from now."""
    identifiers = sorted({email.strip().lower() for email in emails if email.strip()})
    now = timezone.now()
    # The source list keeps no bounce history, so each address gets the longest hold rather than the one-day hold of a
    # single bounce.
    first_bounced_at = now - GLOBAL_HARD_BOUNCE_MAX_HOLD
    EmailHardBounce.objects.bulk_create(
        [EmailHardBounce(email=email, first_bounced_at=first_bounced_at, last_bounced_at=now) for email in identifiers],
        ignore_conflicts=True,
    )
    # An existing row can have a lapsed hold, and the source list still blocks the address, so renew it. LEAST and
    # GREATEST keep times that are already earlier or later, like the upsert in the Node `EmailSuppressionService`.
    EmailHardBounce.objects.filter(email__in=identifiers).update(
        first_bounced_at=Least(F("first_bounced_at"), Value(first_bounced_at)),
        last_bounced_at=Greatest(F("last_bounced_at"), Value(now)),
    )
