from uuid import UUID

from django.db import transaction
from django.db.models import Case, F, Q, QuerySet, TextField, Value, When
from django.db.models.functions import Coalesce, Greatest, Least, Now
from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.models.scoping.manager import resolve_effective_team_id

from products.messaging.backend.models.email_hard_bounce import (
    GLOBAL_HARD_BOUNCE_COPY_DIAGNOSTIC,
    GLOBAL_HARD_BOUNCE_MAX_HOLD,
    EmailHardBounce,
)
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


def block_transactional_for_hard_bounces(
    team_id: int, identifiers: list[str], reason: str, *, rows_locked: bool = False
) -> None:
    """Make the team's existing rows for these hard-bounced addresses suppress them and block transactional email.

    `team_id` must be the canonical project id. A row keeps its source, so a spam complaint still needs confirmation
    to remove. A manual entry or a complaint keeps its reason, like a live hard bounce. A row copied from the global
    list becomes the team's own bounce, so it stays when the global hold lapses. A row someone removed stays removed.
    Outside a transaction, as in the bulk API, each statement updates one row, so the import never holds two row locks
    that a Node bounce write can wait on. A caller that already holds the rows' locks, as the Customer.io import does,
    passes `rows_locked` and updates them in one statement, which keeps those locks short.
    """
    pending = MessageSuppression.objects.for_team(team_id, canonical=True).filter(
        Q(hard_bounced_at__isnull=True)
        | Q(source=SuppressionSource.BOUNCE, last_bounce_diagnostic=GLOBAL_HARD_BOUNCE_COPY_DIAGNOSTIC),
        deleted=False,
    )
    now = timezone.now()
    marks = {
        "suppressed": True,
        "suppressed_at": Case(When(suppressed=False, then=Value(now)), default=F("suppressed_at")),
        "hard_bounced_at": now,
        "reason": Case(
            When(source__in=[SuppressionSource.MANUAL, SuppressionSource.COMPLAINT], then=F("reason")),
            default=Value(reason),
            output_field=TextField(),
        ),
        "last_bounce_diagnostic": Case(
            When(last_bounce_diagnostic=GLOBAL_HARD_BOUNCE_COPY_DIAGNOSTIC, then=Value(None)),
            default=F("last_bounce_diagnostic"),
            output_field=TextField(),
        ),
        "updated_at": now,
    }
    if rows_locked:
        pending.filter(identifier__in=identifiers).update(**marks)
        return
    for row_id in pending.filter(identifier__in=identifiers).values_list("id", flat=True):
        pending.filter(id=row_id).update(**marks)


IMPORTED_SUPPRESSION_REASONS: dict[SuppressionSource, str] = {
    SuppressionSource.BOUNCE: "Imported (bounced)",
    SuppressionSource.COMPLAINT: "Imported (spam complaint)",
    SuppressionSource.MANUAL: "Imported (manually suppressed)",
}


def bulk_add_suppressions(
    team_id: int, sources_by_identifier: dict[str, SuppressionSource], created_by_id: int | None
) -> int:
    """Suppress the identifiers that have no row yet, and return how many rows it added.

    An existing row keeps its source. It can be a manual entry, an address someone removed from the list on purpose,
    or a row the bounce feedback already manages. A bounce still makes a row nobody removed block transactional email,
    see `block_transactional_for_hard_bounces`.
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
            # A provider lists a bounce only for an address that can't receive mail, so it blocks transactional email.
            hard_bounced_at=now if source == SuppressionSource.BOUNCE else None,
            created_by_id=created_by_id,
        )
        # Sorted so concurrent imports take the unique-index locks in the same order and can't deadlock.
        for identifier, source in sorted(sources_by_identifier.items())
        if identifier not in existing
    ]
    # ignore_conflicts skips an address inserted after the read above, and the count by pk leaves it out.
    suppressions.bulk_create(new_rows, ignore_conflicts=True)
    block_transactional_for_hard_bounces(
        team_id,
        [identifier for identifier, source in sources_by_identifier.items() if source == SuppressionSource.BOUNCE],
        IMPORTED_SUPPRESSION_REASONS[SuppressionSource.BOUNCE],
    )
    return suppressions.filter(pk__in=[row.pk for row in new_rows]).count()


class ComplaintConfirmationRequired(Exception):
    def __init__(self, identifiers: list[str]) -> None:
        super().__init__(f"Removing spam complaints needs confirmation: {', '.join(identifiers)}")
        self.identifiers = identifiers


def remove_suppressions(team_id: int, identifiers: list[str], confirm_complaints: bool) -> list[str]:
    """Remove `identifiers` from the team's list, and return the ones that were on it.

    Raises `ComplaintConfirmationRequired`, and removes nothing, when a spam complaint is among them unconfirmed.
    """
    with transaction.atomic():
        rows = MessageSuppression.objects.for_team(team_id)
        locked = lock_confirming_complaints(
            rows.filter(identifier__in=identifiers, suppressed=True, deleted=False), confirm_complaints
        )
        _remove(rows.filter(id__in=[row.id for row in locked]))
    return sorted(row.identifier for row in locked)


@frozen
class LockedSuppression:
    id: UUID
    identifier: str


def lock_confirming_complaints(rows: QuerySet[MessageSuppression], confirm_complaints: bool) -> list[LockedSuppression]:
    """Lock `rows` for the current transaction, and return them.

    Raises `ComplaintConfirmationRequired` when an active spam complaint is among them and `confirm_complaints` is
    false. The lock stops a complaint that lands during the check from being changed unconfirmed. A row inserted
    after the lock is not checked, so callers change only the rows returned.
    """
    locked = list(
        rows.order_by("identifier")
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
    return [LockedSuppression(id=row_id, identifier=identifier) for row_id, identifier, *_ in locked]


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
