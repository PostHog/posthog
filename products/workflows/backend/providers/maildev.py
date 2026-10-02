from dataclasses import replace

from products.workflows.backend.facade.contracts import EmailDomainCheck, EmailDomainDnsRecord
from products.workflows.backend.facade.enums import EmailDomainSetupRecordStatus, EmailDomainSetupStatus
from products.workflows.backend.services.email_domain_status import build_email_domain_check, build_email_domain_records

MAILDEV_MOCK_DNS_RECORDS: list[EmailDomainDnsRecord] = [
    # Mock DNS records for email domain setup when using local maildev
    {
        "type": "verification",
        "recordType": "TXT",
        "recordHostname": "_amazonses.example.com",
        "recordValue": "mock-verification-token",
        "status": "success",
    },
    {
        "type": "dkim",
        "recordType": "CNAME",
        "recordHostname": "mock1._domainkey.example.com",
        "recordValue": "mock1.dkim.amazonses.com",
        "status": "success",
    },
    {
        "type": "dkim",
        "recordType": "CNAME",
        "recordHostname": "mock2._domainkey.example.com",
        "recordValue": "mock2.dkim.amazonses.com",
        "status": "success",
    },
    {
        "type": "dkim",
        "recordType": "CNAME",
        "recordHostname": "mock3._domainkey.example.com",
        "recordValue": "mock3.dkim.amazonses.com",
        "status": "success",
    },
    {
        "type": "verification",
        "recordType": "TXT",
        "recordHostname": "@",
        "recordValue": "v=spf1 include:amazonses.com ~all",
        "status": "success",
    },
    {
        "type": "mail_from",
        "recordType": "MX",
        "recordHostname": "mail.example.com",
        "recordValue": "feedback-smtp.us-east-1.amazonses.com",
        "priority": 10,
        "status": "success",
    },
    {
        "type": "mail_from",
        "recordType": "TXT",
        "recordHostname": "mail.example.com",
        "recordValue": "v=spf1 include:amazonses.com ~all",
        "status": "success",
    },
]


def maildev_email_domain_status(domain: str, *, mail_from_subdomain: str) -> EmailDomainCheck:
    records = build_email_domain_records(
        domain=domain,
        mail_from_subdomain=mail_from_subdomain,
        verification_token="mock-verification-token",
        dkim_tokens=["mock1", "mock2", "mock3"],
        ses_region="us-east-1",
    )
    return build_email_domain_check(
        provider_status=EmailDomainSetupStatus.VERIFIED,
        records=[replace(record, status=EmailDomainSetupRecordStatus.VERIFIED) for record in records],
    )
