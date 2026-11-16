from collections.abc import Sequence

from products.workflows.backend.facade.contracts import EmailDomainCheck, EmailDomainStatusRecord, EmailDomainStatusStep
from products.workflows.backend.facade.enums import (
    EmailDomainSetupRecordKind as Kind,
    EmailDomainSetupRecordStatus as RecordStatus,
    EmailDomainSetupRecordType as RecordType,
    EmailDomainSetupStatus as Status,
    EmailDomainSetupStepKey as StepKey,
    EmailDomainSetupStepState as StepState,
)

SES_SPF_VALUE = "v=spf1 include:amazonses.com ~all"
DEFAULT_DMARC_VALUE = "v=DMARC1; p=none;"


def build_email_domain_records(
    *,
    domain: str,
    mail_from_subdomain: str,
    verification_token: str | None,
    dkim_tokens: Sequence[str],
    ses_region: str,
) -> tuple[EmailDomainStatusRecord, ...]:
    mail_from_domain = f"{mail_from_subdomain}.{domain}"
    verification = (
        [
            EmailDomainStatusRecord(
                kind=Kind.VERIFICATION, hostname=f"_amazonses.{domain}", type=RecordType.TXT, value=verification_token
            )
        ]
        if verification_token
        else []
    )
    dkim = [
        EmailDomainStatusRecord(
            kind=Kind.DKIM,
            hostname=f"{token}._domainkey.{domain}",
            type=RecordType.CNAME,
            value=f"{token}.dkim.amazonses.com",
        )
        for token in dkim_tokens
    ]
    return (
        *verification,
        *dkim,
        EmailDomainStatusRecord(kind=Kind.SPF, hostname=domain, type=RecordType.TXT, value=SES_SPF_VALUE),
        EmailDomainStatusRecord(
            kind=Kind.MAIL_FROM_MX,
            hostname=mail_from_domain,
            type=RecordType.MX,
            value=f"feedback-smtp.{ses_region}.amazonses.com",
            priority=10,
        ),
        EmailDomainStatusRecord(
            kind=Kind.MAIL_FROM_SPF, hostname=mail_from_domain, type=RecordType.TXT, value=SES_SPF_VALUE
        ),
        EmailDomainStatusRecord(
            kind=Kind.DMARC, hostname=f"_dmarc.{domain}", type=RecordType.TXT, value=DEFAULT_DMARC_VALUE
        ),
    )


def build_email_domain_check(
    *, provider_status: Status, records: Sequence[EmailDomainStatusRecord], every_dns_lookup_answered: bool = True
) -> EmailDomainCheck:
    status = _overall_status(provider_status, records)
    return EmailDomainCheck(
        status=status,
        steps=_steps(status, records),
        records=tuple(records),
        every_dns_lookup_answered=every_dns_lookup_answered,
    )


def _overall_status(provider_status: Status, records: Sequence[EmailDomainStatusRecord]) -> Status:
    if provider_status == Status.PENDING and _all_records_published(records):
        return Status.RECORDS_FOUND
    return provider_status


def _all_records_published(records: Sequence[EmailDomainStatusRecord]) -> bool:
    return bool(records) and all(record.status != RecordStatus.PENDING for record in records)


def _steps(status: Status, records: Sequence[EmailDomainStatusRecord]) -> tuple[EmailDomainStatusStep, ...]:
    return (
        EmailDomainStatusStep(key=StepKey.DOMAIN_ADDED, state=_domain_added_state(status)),
        EmailDomainStatusStep(key=StepKey.RECORDS_FOUND, state=_records_found_state(status, records)),
        EmailDomainStatusStep(key=StepKey.VERIFIED, state=_verified_state(status)),
    )


def _domain_added_state(status: Status) -> StepState:
    return StepState.PENDING if status == Status.NOT_STARTED else StepState.DONE


def _records_found_state(status: Status, records: Sequence[EmailDomainStatusRecord]) -> StepState:
    if status == Status.VERIFIED or _all_records_published(records):
        return StepState.DONE
    if status in (Status.FAILED, Status.TEMPORARY_FAILURE):
        return StepState.FAILED
    return StepState.PENDING


def _verified_state(status: Status) -> StepState:
    if status == Status.VERIFIED:
        return StepState.DONE
    if status == Status.FAILED:
        return StepState.FAILED
    return StepState.PENDING
