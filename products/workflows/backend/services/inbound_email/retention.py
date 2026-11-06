"""Received mail lives for 30 days, and leaves with its team."""

from datetime import timedelta

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
