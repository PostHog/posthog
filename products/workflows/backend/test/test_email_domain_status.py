from django.test import SimpleTestCase

from parameterized import parameterized

from products.workflows.backend.facade.contracts import EmailDomainStatusRecord
from products.workflows.backend.facade.enums import (
    EmailDomainSetupRecordKind as Kind,
    EmailDomainSetupRecordType as RecordType,
)
from products.workflows.backend.services.email_domain_dns import find_published_records
from products.workflows.backend.test.fakes.world import EmailDomainWorld

DOMAIN = "mail.example.com"


def _record(kind: Kind, record_type: RecordType, hostname: str, value: str, priority: int | None = None):
    return EmailDomainStatusRecord(kind=kind, hostname=hostname, type=record_type, value=value, priority=priority)


SPF = _record(Kind.SPF, RecordType.TXT, DOMAIN, "v=spf1 include:amazonses.com ~all")
VERIFICATION = _record(Kind.VERIFICATION, RecordType.TXT, f"_amazonses.{DOMAIN}", "tok")
DKIM = _record(Kind.DKIM, RecordType.CNAME, f"dk1._domainkey.{DOMAIN}", "dk1.dkim.amazonses.com")
MAIL_FROM_MX = _record(
    Kind.MAIL_FROM_MX, RecordType.MX, f"feedback.{DOMAIN}", "feedback-smtp.us-east-1.amazonses.com", priority=10
)
DMARC = _record(Kind.DMARC, RecordType.TXT, f"_dmarc.{DOMAIN}", "v=DMARC1; p=none;")


class TestFindPublishedRecords(SimpleTestCase):
    @parameterized.expand(
        [
            ("txt_split_into_chunks", VERIFICATION, '"to" "k"', True),
            ("txt_other_value", VERIFICATION, '"other"', False),
            (
                "spf_merged_with_another_sender",
                SPF,
                '"v=spf1 include:_spf.google.com include:amazonses.com -all"',
                True,
            ),
            ("spf_without_ses_include", SPF, '"v=spf1 include:_spf.google.com ~all"', False),
            ("cname_in_upper_case", DKIM, "DK1.DKIM.AMAZONSES.COM.", True),
            ("mx_with_other_priority", MAIL_FROM_MX, "20 feedback-smtp.us-east-1.amazonses.com.", False),
            ("existing_strict_dmarc", DMARC, '"v=DMARC1; p=reject; rua=mailto:dmarc@example.com"', True),
        ]
    )
    def test_matches_published_value(
        self, _name: str, record: EmailDomainStatusRecord, published: str, expected: bool
    ) -> None:
        world = EmailDomainWorld()
        world.dns.add_zone("example.com", nameservers={"ns1.example-dns.net": "34.120.0.1"})
        world.dns.publish(record.hostname, record.type.value, published)

        with world.installed():
            assert (record in find_published_records(DOMAIN, [record]).records) is expected
