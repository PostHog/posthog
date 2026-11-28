"""Received email, for products that act on incoming mail and for team and person deletion."""

from products.workflows.backend.services.inbound_email.retention import RETENTION_DAYS, delete_received_emails_for_teams


def queue_received_email_deletion_for_persons(team_id: int, person_ids: list[str], addresses: list[str]) -> None:
    # Imported here because the task module loads intake, and person deletion shouldn't load that for every import.
    from products.workflows.backend.tasks.inbound_email import delete_received_emails_for_persons_task  # noqa: PLC0415

    delete_received_emails_for_persons_task.delay(team_id, person_ids, addresses)


__all__ = ["RETENTION_DAYS", "delete_received_emails_for_teams", "queue_received_email_deletion_for_persons"]
