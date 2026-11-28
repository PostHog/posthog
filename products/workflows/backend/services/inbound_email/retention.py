"""Received mail lives for 30 days, and leaves with its team or the person who wrote it."""

from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

import structlog

from products.workflows.backend.models import ReceivedEmail
from products.workflows.backend.services.inbound_email import storage

logger = structlog.get_logger(__name__)

RETENTION_DAYS = 30
_BATCH_SIZE = 500
_MAX_BATCHES_PER_RUN = 40


def retention_cutoff():
    return timezone.now() - timedelta(days=RETENTION_DAYS)


def delete_expired_received_emails() -> int:
    deleted = 0
    for _ in range(_MAX_BATCHES_PER_RUN):
        rows = list(
            ReceivedEmail.objects.unscoped()
            .filter(received_at__lt=retention_cutoff())
            .order_by("received_at")
            .values_list("id", "team_id")[:_BATCH_SIZE]
        )
        if not rows:
            break
        # Objects first: a row left behind by a failure is found again, an object left behind is not.
        for email_id, team_id in rows:
            storage.delete_prefix(storage.email_prefix(team_id, email_id))
            ReceivedEmail.objects.for_team(team_id).filter(pk=email_id).delete()
        deleted += len(rows)
    return deleted


def delete_received_emails_for_teams(team_ids: list[int]) -> None:
    # Most teams never received mail, and their deletion shouldn't depend on object storage being reachable.
    with_mail = set(ReceivedEmail.objects.unscoped().filter(team_id__in=team_ids).values_list("team_id", flat=True))
    for team_id in with_mail:
        storage.delete_prefix(storage.team_prefix(team_id))
        ReceivedEmail.objects.for_team(team_id).all().delete()


def delete_received_emails_for_persons(team_id: int, person_ids: list[str], addresses: list[str]) -> int:
    """Remove mail linked to these persons or sent from these addresses, linked or not, since an unverified From stays."""
    lowered = [address.lower() for address in addresses]
    matching = Q(person_id__in=person_ids) | Q(from_address__in=lowered)
    deleted = 0
    # The team may already be gone by the time this runs, and then so is its mail.
    rows = ReceivedEmail.objects.unscoped().filter(matching, team_id=team_id)
    for email_id in list(rows.values_list("id", flat=True)):
        # Objects first, for the same reason as above.
        storage.delete_prefix(storage.email_prefix(team_id, email_id))
        ReceivedEmail.objects.for_team(team_id).filter(pk=email_id).delete()
        deleted += 1
    return deleted
