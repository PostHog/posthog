"""The DNS record an organization publishes to prove it owns a sending domain that another organization also claims.

The provider's own records cannot tell claimants apart, because every organization on a domain shares one identity
at the provider and so gets the same records. The token is random and stored on the organization's senders, so
another organization cannot know it.
"""

from dataclasses import replace

from products.workflows.backend.facade.contracts import EmailDomainCheck, EmailDomainStatusRecord
from products.workflows.backend.facade.enums import (
    EmailDomainSetupRecordKind as Kind,
    EmailDomainSetupRecordStatus as RecordStatus,
    EmailDomainSetupRecordType as RecordType,
    EmailDomainSetupStatus as Status,
)
from products.workflows.backend.services.email_domain_dns import find_published_records
from products.workflows.backend.services.email_domain_status import build_email_domain_check


def organization_proof_record(domain: str, token: str) -> EmailDomainStatusRecord:
    return EmailDomainStatusRecord(
        kind=Kind.ORGANIZATION,
        hostname=f"_posthog-verification.{domain}",
        type=RecordType.TXT,
        value=f"posthog-verification={token}",
    )


def organization_proof_published(domain: str, token: str) -> bool:
    record = organization_proof_record(domain, token)
    return record in find_published_records(domain, [record]).records


def with_organization_proof(check: EmailDomainCheck, *, domain: str, token: str) -> EmailDomainCheck:
    record = organization_proof_record(domain, token)
    published = find_published_records(domain, [record])
    proven = record in published.records
    proof = replace(record, status=RecordStatus.VERIFIED if proven else RecordStatus.PENDING)
    return build_email_domain_check(
        provider_status=_status_with_proof(check.status, proven=proven),
        records=(*check.records, proof),
        every_dns_lookup_answered=check.every_dns_lookup_answered and published.every_lookup_answered,
    )


def _status_with_proof(status: Status, *, proven: bool) -> Status:
    if status in (Status.VERIFIED, Status.RECORDS_FOUND) and not proven:
        return Status.PENDING
    return status
