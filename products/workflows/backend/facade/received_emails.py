"""Received email and inbound domains, for the API, for products that act on incoming mail, and for team and person
deletion."""

from products.workflows.backend.facade.contracts import (
    DomainPreflightResult,
    InboundDomain,
    InboundDomainCheck,
    InboundDomainError,
    InboundDomainsOverview,
    ReceivedEmailAttachment,
    ReceivedEmailDetail,
    ReceivedEmailPage,
    ReceivedEmailSummary,
)
from products.workflows.backend.services.inbound_email.reads import (
    check_inbound_domain,
    create_inbound_domain,
    delete_inbound_domain,
    get_inbound_domain_overview,
    get_received_email,
    get_received_email_attachment,
    list_received_emails,
    preflight_inbound_domain,
    use_receiving_address,
)
from products.workflows.backend.services.inbound_email.retention import RETENTION_DAYS, delete_received_emails_for_teams


def queue_received_email_deletion_for_persons(team_id: int, person_ids: list[str], addresses: list[str]) -> None:
    # Imported here because the task module loads intake, and person deletion shouldn't load that for every import.
    from products.workflows.backend.tasks.inbound_email import delete_received_emails_for_persons_task  # noqa: PLC0415

    delete_received_emails_for_persons_task.delay(team_id, person_ids, addresses)


__all__ = [
    "DomainPreflightResult",
    "InboundDomain",
    "InboundDomainCheck",
    "InboundDomainError",
    "InboundDomainsOverview",
    "RETENTION_DAYS",
    "ReceivedEmailAttachment",
    "ReceivedEmailDetail",
    "ReceivedEmailPage",
    "ReceivedEmailSummary",
    "check_inbound_domain",
    "create_inbound_domain",
    "delete_inbound_domain",
    "delete_received_emails_for_teams",
    "get_inbound_domain_overview",
    "get_received_email",
    "get_received_email_attachment",
    "list_received_emails",
    "preflight_inbound_domain",
    "queue_received_email_deletion_for_persons",
    "use_receiving_address",
]
