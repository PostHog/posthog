from datetime import timedelta
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership
from posthog.models.integration import Integration

from products.access_control.backend.facade.testing import create_access_control
from products.workflows.backend.facade.enums import (
    InboundEmailContentStatus,
    InboundEmailDomainKind,
    InboundEmailDomainStatus,
    ReceivedEmailStatus,
)
from products.workflows.backend.facade.testing import create_workflow_for_test
from products.workflows.backend.models import InboundEmailDomain, ReceivedEmail
from products.workflows.backend.services.email_domain_dns import MxLookup

FLAG = "products.workflows.backend.presentation.views.inbound_email_domains.posthoganalytics.feature_enabled"
LOOKUP = "products.workflows.backend.services.inbound_email.domains.lookup_mx"
MX_HOST = "inbound-smtp.example.amazonaws.com"


@override_settings(WORKFLOWS_INBOUND_EMAIL_MX_HOST=MX_HOST, WORKFLOWS_INBOUND_EMAIL_BASE_DOMAIN="in.example.org")
@patch(FLAG, return_value=True)
class TestInboundEmailDomains(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        Integration.objects.create(
            team=self.team,
            kind="email",
            integration_id="a@acme.example",
            config={"domain": "acme.example", "verified": True},
        )
        self.url = f"/api/projects/{self.team.id}/inbound_email_domains/"

    def _add(self, domain: str, **extra: object):
        return self.client.post(self.url, {"domain": domain, **extra}, content_type="application/json")

    def test_ready_made_address_is_stable_and_can_be_changed(self, _flag) -> None:
        url = f"{self.url}receiving_address/"
        first = self.client.post(url, {}, content_type="application/json").json()
        again = self.client.post(url, {}, content_type="application/json").json()
        changed = self.client.post(url, {"rotate": True}, content_type="application/json").json()
        self.assertEqual(first["domain"], again["domain"])
        self.assertTrue(first["domain"].endswith(".in.example.org"))
        self.assertEqual(first["status"], "active")
        self.assertNotEqual(first["domain"], changed["domain"])

    @parameterized.expand(
        [
            ("not_owned", "mail.other.example"),
            ("generated_namespace", "anything.in.example.org"),
            ("malformed", "not a domain"),
        ]
    )
    def test_a_domain_the_project_has_not_proved_is_refused(self, _flag, _name: str, domain: str) -> None:
        with patch(LOOKUP, return_value=MxLookup(records=(), answered=True)):
            response = self._add(domain)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @parameterized.expand(
        [
            ("subdomain_with_mail", "mail.acme.example", ((10, "aspmx.l.google.com"),)),
            ("whole_domain", "acme.example", ()),
        ]
    )
    def test_moving_mail_needs_confirmation(self, _flag, _name: str, domain: str, records: tuple) -> None:
        with patch(LOOKUP, return_value=MxLookup(records=records, answered=True)):
            refused = self._add(domain)
            accepted = self._add(domain, confirm_move_mail=True)
        self.assertEqual(refused.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(refused.json()["code"], "confirmation_required")
        self.assertEqual(accepted.status_code, status.HTTP_201_CREATED)

    @parameterized.expand(
        [
            ("missing", (), "missing", "pending"),
            ("elsewhere", ((10, "aspmx.l.google.com"),), "conflict", "pending"),
            ("outranked", ((5, "aspmx.l.google.com"), (10, MX_HOST)), "conflict", "pending"),
            ("tied", ((10, "aspmx.l.google.com"), (10, MX_HOST)), "conflict", "pending"),
            ("ours_first", ((10, MX_HOST), (20, "backup.example")), "active", "active"),
        ]
    )
    def test_check_reports_what_dns_says(self, _flag, _name: str, records: tuple, state: str, row_status: str) -> None:
        with patch(LOOKUP, return_value=MxLookup(records=(), answered=True)):
            domain_id = self._add("inbound.acme.example").json()["domain"]["id"]
        with patch(LOOKUP, return_value=MxLookup(records=records, answered=True)):
            check = self.client.post(f"{self.url}{domain_id}/verify/").json()
        self.assertEqual((check["state"], check["domain"]["status"]), (state, row_status))

    def test_a_failed_lookup_does_not_stop_a_working_domain(self, _flag) -> None:
        with patch(LOOKUP, return_value=MxLookup(records=((10, MX_HOST),), answered=True)):
            domain_id = self._add("inbound.acme.example").json()["domain"]["id"]
        with patch(LOOKUP, return_value=MxLookup(records=(), answered=False)):
            check = self.client.post(f"{self.url}{domain_id}/verify/").json()
        self.assertEqual((check["state"], check["domain"]["status"]), ("lookup_failed", "active"))

    def test_check_says_when_no_sending_domain_covers_the_domain(self, _flag) -> None:
        with patch(LOOKUP, return_value=MxLookup(records=(), answered=True)):
            domain_id = self._add("inbound.acme.example").json()["domain"]["id"]
        Integration.objects.filter(team=self.team, kind="email").delete()
        with patch(LOOKUP, return_value=MxLookup(records=((10, MX_HOST),), answered=True)):
            check = self.client.post(f"{self.url}{domain_id}/verify/").json()
        self.assertEqual((check["state"], check["domain"]["status"]), ("no_sending_domain", "pending"))

    def test_a_domain_another_project_receives_on_cannot_be_taken(self, _flag) -> None:
        other = self.create_team_with_organization(organization=self.organization)
        Integration.objects.create(
            team=other,
            kind="email",
            integration_id="b@acme.example",
            config={"domain": "acme.example", "verified": True},
        )
        InboundEmailDomain.objects.for_team(other.pk).create(
            team_id=other.pk,
            domain="inbound.acme.example",
            kind=InboundEmailDomainKind.CUSTOM,
            status=InboundEmailDomainStatus.ACTIVE,
        )
        with patch(LOOKUP, return_value=MxLookup(records=(), answered=True)):
            self.assertEqual(self._add("inbound.acme.example").status_code, status.HTTP_400_BAD_REQUEST)


@patch(FLAG, return_value=True)
class TestReceivedEmails(APIBaseTest):
    def _email(self, team_id: int | None = None, **fields: object) -> ReceivedEmail:
        team_id = team_id or self.team.pk
        defaults: dict = {
            "ses_message_id": uuid4().hex,
            "status": ReceivedEmailStatus.RECEIVED,
            "content_status": InboundEmailContentStatus.TOO_LARGE,
            "received_at": timezone.now(),
            "subject": "Hello",
            "from_address": "dana@sender.example",
        }
        return ReceivedEmail.objects.for_team(team_id).create(team_id=team_id, **{**defaults, **fields})

    @parameterized.expand(
        [
            ("pass", "PASS", True),
            ("gray", "GRAY", False),
            ("processing_failed", "PROCESSING_FAILED", False),
            ("missing", "", False),
        ]
    )
    def test_files_are_only_downloadable_after_a_passed_virus_scan(
        self, _flag, _name: str, verdict: str, downloadable: bool
    ) -> None:
        email = self._email(content_status=InboundEmailContentStatus.AVAILABLE, virus_verdict=verdict)
        attachment = {"index": 0, "filename": "a.txt", "content_type": "text/plain", "size": 1}
        reads = "products.workflows.backend.services.inbound_email.reads.storage"
        with (
            patch(f"{reads}.read_content", return_value={"attachments": [attachment]}),
            patch(f"{reads}.download_link", return_value="https://storage.example/link"),
        ):
            url = f"/api/projects/{self.team.pk}/received_emails/{email.id}/"
            detail = self.client.get(url).json()
            single = self.client.get(f"{url}attachments/0/").json()
        expected = "https://storage.example/link" if downloadable else None
        self.assertEqual(detail["raw"]["download_url"], expected)
        self.assertEqual(detail["attachments"][0]["download_url"], expected)
        self.assertEqual(single["download_url"], expected)

    def test_mail_kept_without_content_offers_no_raw_message(self, _flag) -> None:
        email = self._email(content_status=InboundEmailContentStatus.NOT_STORED, virus_verdict="PASS")
        detail = self.client.get(f"/api/projects/{self.team.pk}/received_emails/{email.id}/").json()
        self.assertEqual((detail["content_status"], detail["raw"]["download_url"]), ("not_stored", None))

    def test_another_projects_email_is_not_found(self, _flag) -> None:
        other = self.create_team_with_organization(organization=self.organization)
        email = self._email(team_id=other.pk)
        response = self.client.get(f"/api/projects/{self.team.id}/received_emails/{email.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_an_expired_email_is_not_found(self, _flag) -> None:
        email = self._email(received_at=timezone.now() - timedelta(days=31))
        response = self.client.get(f"/api/projects/{self.team.id}/received_emails/{email.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_counts_filtered_mail_behind_the_default_view(self, _flag) -> None:
        self._email(subject="kept")
        self._email(subject="spam", status=ReceivedEmailStatus.FILTERED, filter_reason="spam")
        body = self.client.get(f"/api/projects/{self.team.id}/received_emails/", {"status": "received"}).json()
        self.assertEqual([row["subject"] for row in body["results"]], ["kept"])
        self.assertEqual(body["filtered_count"], 1)

    @parameterized.expand([("sender", "dana@"), ("subject", "hell"), ("recipient", "support@")])
    def test_search_finds_by(self, _flag, _name: str, search: str) -> None:
        self._email(envelope_recipients=["support@a.example"])
        self._email(subject="zzz", from_address="z@z.example")
        body = self.client.get(f"/api/projects/{self.team.id}/received_emails/", {"search": search}).json()
        self.assertEqual(len(body["results"]), 1)

    def test_old_mail_keeps_the_list_out_of_setup(self, _flag) -> None:
        self._email(received_at=timezone.now() - timedelta(days=20))
        body = self.client.get(f"/api/projects/{self.team.id}/received_emails/").json()
        self.assertEqual((body["results"], body["has_any_email"]), ([], True))

    def _as_member_with_access_control(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

    def test_a_member_without_person_access_cannot_read_mail(self, _flag) -> None:
        self._as_member_with_access_control()
        create_access_control(team_id=self.team.id, resource="person", access_level="none")
        response = self.client.get(f"/api/projects/{self.team.id}/received_emails/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_access_to_one_workflow_does_not_reach_the_mail(self, _flag) -> None:
        self._as_member_with_access_control()
        create_access_control(team_id=self.team.id, resource="hog_flow", access_level="none")
        create_access_control(
            team_id=self.team.id,
            resource="hog_flow",
            resource_id=str(create_workflow_for_test(team_id=self.team.id, name="Only this one").id),
            access_level="viewer",
            organization_member_id=self.organization_membership.id,
        )
        for path in ("received_emails", "inbound_email_domains"):
            response = self.client.get(f"/api/projects/{self.team.id}/{path}/")
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, path)

    def test_is_hidden_while_the_flag_is_off(self, flag) -> None:
        flag.return_value = False
        response = self.client.get(f"/api/projects/{self.team.id}/received_emails/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
