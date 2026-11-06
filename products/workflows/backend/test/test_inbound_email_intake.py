import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from typing import Any
from uuid import uuid4

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from parameterized import parameterized

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team import Team
from posthog.redis import get_client
from posthog.storage.object_storage import ObjectStorageError

from products.workflows.backend.facade.enums import InboundEmailDomainKind, InboundEmailDomainStatus
from products.workflows.backend.models import InboundEmailDomain, ReceivedEmail
from products.workflows.backend.services.inbound_email.domains import (
    CHECK_FAILURE_GRACE,
    PENDING_ACTIVATION_WINDOW,
    check_domain_mx,
    preflight_domain,
    sweep_active_domains,
)
from products.workflows.backend.services.inbound_email.intake import (
    IntakeObjectMissing,
    MxLookupUnavailable,
    _over_daily_limit,
    _spend_daily_bytes,
    is_sender_verified,
    process_notification,
    received_email_id,
)
from products.workflows.backend.services.inbound_email.matching import SendMatch, ses_message_id
from products.workflows.backend.services.inbound_email.parsing import MAX_HEADER_BLOCK_BYTES, MAX_RAW_BYTES
from products.workflows.backend.services.inbound_email.retention import (
    delete_expired_received_emails,
    delete_received_emails_for_persons,
)

BUCKET = "qa-bucket"
SIMPLE = (
    b"Received: by mx for <other@b.example>;\r\nFrom: Dana <dana@sender.example>\r\nTo: hi@a.example\r\n"
    b"Subject: Hello\r\nMessage-ID: <1@sender.example>\r\n\r\nThanks\r\n"
)


MX_HOST = "inbound-smtp.example.amazonaws.com"
DOMAINS = "products.workflows.backend.services.inbound_email.domains"
INTAKE = "products.workflows.backend.services.inbound_email.intake"


def _verify_sending_domain(team: Team, domain: str) -> Integration:
    return Integration.objects.create(
        team=team,
        kind="email",
        integration_id=f"sender@{domain}",
        config={"domain": domain, "email": f"sender@{domain}", "provider": "maildev", "verified": True},
    )


def _mx(*hosts: str) -> MagicMock:
    return MagicMock(answered=True, records=tuple((10, host) for host in hosts))


class _FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def write(self, key: str, content: Any, extras: Any = None, bucket: str | None = None) -> None:
        self.objects[key] = content.encode() if isinstance(content, str) else content

    def read_bytes(self, key: str, bucket: str | None = None, *, missing_ok: bool = False) -> bytes | None:
        return self.objects.get(key)

    def read(self, key: str, bucket: str | None = None, *, missing_ok: bool = False) -> str | None:
        value = self.objects.get(key)
        return value.decode() if value is not None else None

    def head_object(self, key: str, bucket: str | None = None) -> dict[str, int] | None:
        return {"ContentLength": len(self.objects[key])} if key in self.objects else None

    def delete(self, key: str, bucket: str | None = None) -> None:
        self.objects.pop(key, None)

    def iter_keys(self, prefix: str, bucket: str | None = None) -> list[str]:
        return [key for key in self.objects if key.startswith(prefix)]

    def delete_objects(self, keys: list[str], bucket: str | None = None) -> list[str]:
        for key in keys:
            self.objects.pop(key, None)
        return []


@override_settings(
    WORKFLOWS_INBOUND_EMAIL_BUCKET=BUCKET,
    WORKFLOWS_INBOUND_EMAIL_INTAKE_PREFIX="intake/",
    WORKFLOWS_INBOUND_EMAIL_MX_HOST=MX_HOST,
)
class TestProcessNotification(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.storage = _FakeStorage()
        self.other_team = Team.objects.create(
            organization=Organization.objects.create(name="other"), name="other", api_token=f"phc_{uuid4().hex}"
        )
        for team, name in ((self.team, "a.example"), (self.other_team, "b.example")):
            _verify_sending_domain(team, name)
            InboundEmailDomain.objects.for_team(team.pk).create(
                team_id=team.pk, domain=name, kind=InboundEmailDomainKind.CUSTOM, status=InboundEmailDomainStatus.ACTIVE
            )
        self.capture = MagicMock()

    @contextmanager
    def _patched(self) -> Iterator[None]:
        base = "products.workflows.backend.services.inbound_email"
        patches: list[Any] = [
            patch(f"{base}.intake.object_storage", self.storage),
            patch(f"{base}.storage.object_storage", self.storage),
            patch(f"{base}.intake.capture_internal", self.capture),
            patch(f"{base}.intake.find_person_by_email", return_value=None),
            patch(f"{base}.intake.find_original_send", return_value=None),
            patch(f"{base}.intake._over_sender_limit", return_value=False),
            patch(f"{base}.intake._over_daily_limit", return_value=False),
            patch(f"{base}.intake._spend_daily_bytes", return_value=True),
        ]
        for started in patches:
            started.start()
        try:
            yield
        finally:
            for started in patches:
                started.stop()

    def _notification(
        self, recipients: list[str], ses_id: str = "ses-1", raw: bytes | None = SIMPLE, **verdicts: str
    ) -> Any:
        key = f"intake/{ses_id}"
        if raw is not None:
            self.storage.objects[key] = raw
        receipt = {
            f"{name}Verdict": {"status": verdicts.get(name, "PASS")}
            for name in ("spf", "dkim", "dmarc", "spam", "virus")
        }
        return {
            "notificationType": "Received",
            "mail": {
                "messageId": ses_id,
                "source": verdicts.get("source", "dana@sender.example"),
                "commonHeaders": {"from": verdicts.get("receipt_from", ["Dana <dana@sender.example>"])},
            },
            "receipt": {
                **receipt,
                "timestamp": "2026-11-06T10:00:00.000Z",
                "recipients": recipients,
                "action": {"type": "S3", "bucketName": BUCKET, "objectKey": key},
            },
        }

    def _rows(self, team: Team) -> list[ReceivedEmail]:
        return list(ReceivedEmail.objects.for_team(team.pk).all())

    def test_stores_mail_captures_metadata_only_and_clears_intake(self) -> None:
        with self._patched():
            process_notification(self._notification(["hi@a.example"]))
        row = self._rows(self.team)[0]
        self.assertEqual(row.subject, "Hello")
        self.assertNotIn("intake/ses-1", self.storage.objects)
        call = self.capture.call_args.kwargs
        self.assertEqual(call["event_name"], "$email_received")
        self.assertFalse(call["process_person_profile"])
        self.assertNotIn("Thanks", json.dumps(call["properties"]))
        self.assertNotIn("Hello", json.dumps(call["properties"]))
        self.assertNotIn("$email_subject", call["properties"])
        self.assertNotIn("$email_cc_addresses", call["properties"])
        self.assertIn(f"inbound-email/teams/{self.team.pk}/{row.id}/raw.eml", self.storage.objects)

    def test_each_team_sees_only_its_own_recipients(self) -> None:
        with self._patched():
            process_notification(self._notification(["hi@a.example", "other@b.example", "stranger@nobody.example"]))
        mine, theirs = self._rows(self.team)[0], self._rows(self.other_team)[0]
        self.assertEqual(mine.envelope_recipients, ["hi@a.example"])
        self.assertEqual(theirs.envelope_recipients, ["other@b.example"])
        raw = self.storage.objects[f"inbound-email/teams/{self.team.pk}/{mine.id}/raw.eml"]
        self.assertNotIn(b"other@b.example", raw)

    def test_redelivery_stores_and_captures_once(self) -> None:
        notification = self._notification(["hi@a.example"])
        with self._patched():
            process_notification(notification)
            process_notification(notification)
        self.assertEqual(len(self._rows(self.team)), 1)
        self.assertEqual(self.capture.call_count, 1)

    def test_a_failed_capture_is_retried_without_a_second_row(self) -> None:
        notification = self._notification(["hi@a.example"])
        self.capture.side_effect = [RuntimeError("capture down"), MagicMock()]
        with self._patched():
            with self.assertRaises(RuntimeError):
                process_notification(notification)
            self.assertIn("intake/ses-1", self.storage.objects)
            process_notification(notification)
        self.assertEqual(len(self._rows(self.team)), 1)
        self.assertIsNotNone(self._rows(self.team)[0].event_captured_at)
        self.assertNotIn("intake/ses-1", self.storage.objects)

    @parameterized.expand(
        [
            ("bounce", {"source": ""}, SIMPLE, "auto_reply"),
            (
                "auto_submitted",
                {},
                b"From: a@x.example\r\nAuto-Submitted: auto-replied\r\n\r\naway\r\n",
                "auto_reply",
            ),
        ]
    )
    def test_filtered_mail_is_kept_but_fires_no_event(self, _name: str, verdicts: Any, raw: bytes, reason: str) -> None:
        with self._patched():
            process_notification(self._notification(["hi@a.example"], raw=raw, **verdicts))
        row = self._rows(self.team)[0]
        self.assertEqual(row.filter_reason, reason)
        self.assertEqual(row.content_status, "available")
        self.capture.assert_not_called()

    @parameterized.expand(
        [
            ("spam", {"spam": "FAIL"}, False, "spam"),
            ("over_the_sender_limit", {}, True, "rate_limited"),
        ]
    )
    def test_mail_filtered_on_the_receipt_keeps_only_details(
        self, _name: str, verdicts: Any, over_sender_limit: bool, reason: str
    ) -> None:
        with self._patched(), patch(f"{INTAKE}._over_sender_limit", return_value=over_sender_limit):
            with patch.object(self.storage, "read_bytes") as read_bytes:
                process_notification(self._notification(["hi@a.example"], **verdicts))
        read_bytes.assert_not_called()
        row = self._rows(self.team)[0]
        self.assertEqual((row.filter_reason, row.content_status), (reason, "not_stored"))
        self.assertEqual(row.from_address, "dana@sender.example")
        self.assertEqual(self.storage.objects, {})
        self.capture.assert_not_called()

    def test_junk_over_its_own_cap_leaves_proven_mail_flowing(self) -> None:
        get_client().delete(*get_client().keys(f"workflows:inbound_email:*:{self.team.pk}:*") or ["unused"])
        with (
            self._patched(),
            patch(f"{INTAKE}.UNTRUSTED_DAILY_LIMIT", 1),
            patch(f"{INTAKE}._over_daily_limit", wraps=_over_daily_limit),
        ):
            for index in range(3):
                process_notification(self._notification(["hi@a.example"], f"junk-{index}", dmarc="FAIL", spf="FAIL"))
            process_notification(self._notification(["hi@a.example"], "proven"))
        self.assertEqual(sorted(row.ses_message_id for row in self._rows(self.team)), ["junk-0", "proven"])
        self.assertIsNotNone(InboundEmailDomain.objects.for_team(self.team.pk).get().daily_limit_reached_at)

    def test_a_message_past_the_byte_budget_is_dropped_but_a_smaller_one_fits(self) -> None:
        get_client().delete(*get_client().keys(f"workflows:inbound_email:*:{self.team.pk}:*") or ["unused"])
        big = SIMPLE + b"x" * 100
        with (
            self._patched(),
            patch(f"{INTAKE}.TEAM_DAILY_BYTES", len(big)),
            patch(f"{INTAKE}._spend_daily_bytes", wraps=_spend_daily_bytes),
        ):
            process_notification(self._notification(["hi@a.example"], "first", raw=SIMPLE))
            process_notification(self._notification(["hi@a.example"], "too-big", raw=big))
            process_notification(self._notification(["hi@a.example"], "still-fits", raw=b"From: a@b.example\r\n\r\nx"))
        self.assertEqual(sorted(row.ses_message_id for row in self._rows(self.team)), ["first", "still-fits"])

    @parameterized.expand(
        [
            ("plain", b"From: Dana <dana@sender.example>", True),
            ("two_from_headers", b"From: dana@sender.example\r\nFrom: a@other.example", False),
            ("route", b"From: <@sender.example:a@other.example>", False),
            ("comment", b"From: a@other.example(@sender.example)", False),
            ("encoded_address", b"From: =?utf-8?q?a=40other.example?=", False),
            ("other_domain_than_the_receipt", b"From: a@other.example", False),
        ]
    )
    def test_sender_verified_needs_one_plain_from_in_the_domain_ses_checked(
        self, _name: str, from_header: bytes, expected: bool
    ) -> None:
        lookup = MagicMock(return_value=None)
        raw = from_header + b"\r\nTo: hi@a.example\r\nSubject: Hello\r\n\r\nThanks\r\n"
        with self._patched(), patch(f"{INTAKE}.find_person_by_email", lookup):
            process_notification(self._notification(["hi@a.example"], raw=raw))
        self.assertEqual(self._rows(self.team)[0].sender_verified, expected)
        self.assertEqual(lookup.called, expected)

    def test_mail_with_no_parsed_message_stays_unverified(self) -> None:
        raw = b"From: Dana <dana@sender.example>\r\nSubject: " + b"y" * (MAX_HEADER_BLOCK_BYTES + 1) + b"\r\n\r\nb"
        lookup = MagicMock(return_value=None)
        with self._patched(), patch(f"{INTAKE}.find_person_by_email", lookup):
            process_notification(self._notification(["hi@a.example"], raw=raw))
        row = self._rows(self.team)[0]
        self.assertEqual((row.content_status, row.sender_verified), ("parse_failed", False))
        self.assertEqual(row.from_address, "dana@sender.example")
        lookup.assert_not_called()

    def test_a_raw_8_bit_message_id_reaches_the_database(self) -> None:
        raw = b"From: a@x.example\r\nMessage-ID: <\xe9@x.example>\r\nIn-Reply-To: <\xe9@x.example>\r\n\r\nb"
        with self._patched():
            process_notification(self._notification(["hi@a.example"], raw=raw))
        self.assertIn("@x.example", self._rows(self.team)[0].message_id)

    def test_a_domain_whose_last_sender_is_gone_stops_receiving(self) -> None:
        Integration.objects.filter(team=self.team, kind="email").delete()
        with self._patched():
            process_notification(self._notification(["hi@a.example"]))
        self.assertEqual(self._rows(self.team), [])
        self.assertEqual(self.storage.objects, {})
        domain = InboundEmailDomain.objects.for_team(self.team.pk).get()
        self.assertEqual((domain.status, domain.activated_at), ("pending", None))

    @parameterized.expand(
        [
            ("a_fresh_claim_alone", timedelta(hours=1), False, 1),
            ("a_leftover_claim", PENDING_ACTIVATION_WINDOW + timedelta(hours=1), False, 0),
            ("a_fresh_claim_with_a_competitor", timedelta(hours=1), True, 0),
        ]
    )
    def test_mail_activates_only_a_fresh_claim_alone(
        self, _name: str, age: timedelta, competitor: bool, expected_rows: int
    ) -> None:
        _verify_sending_domain(self.team, "fresh.example")
        row = InboundEmailDomain.objects.for_team(self.team.pk).create(
            team_id=self.team.pk,
            domain="in.fresh.example",
            kind=InboundEmailDomainKind.CUSTOM,
            status=InboundEmailDomainStatus.PENDING,
        )
        InboundEmailDomain.objects.for_team(self.team.pk).filter(pk=row.pk).update(created_at=timezone.now() - age)
        if competitor:
            InboundEmailDomain.objects.for_team(self.other_team.pk).create(
                team_id=self.other_team.pk,
                domain="in.fresh.example",
                kind=InboundEmailDomainKind.CUSTOM,
                status=InboundEmailDomainStatus.PENDING,
            )
        with self._patched(), patch(f"{DOMAINS}.lookup_mx", return_value=_mx(MX_HOST)):
            process_notification(self._notification(["hi@in.fresh.example"]))
        self.assertEqual(len(self._rows(self.team)), expected_rows)

    def test_person_deletion_removes_linked_and_same_address_mail_only(self) -> None:
        person_id = uuid4()
        for ses_id, from_address, linked in (
            ("linked", "changed@sender.example", person_id),
            ("same-address", "dana@sender.example", None),
            ("someone-else", "other@sender.example", None),
        ):
            email_id = received_email_id(self.team.pk, ses_id)
            ReceivedEmail.objects.for_team(self.team.pk).create(
                id=email_id,
                team_id=self.team.pk,
                ses_message_id=ses_id,
                from_address=from_address,
                person_id=linked,
                status="received",
                content_status="available",
                received_at=timezone.now(),
            )
            self.storage.objects[f"inbound-email/teams/{self.team.pk}/{email_id}/raw.eml"] = b"x"
        with self._patched():
            deleted = delete_received_emails_for_persons(self.team.pk, [str(person_id)], ["Dana@sender.example"])
        self.assertEqual(deleted, 2)
        self.assertEqual([row.ses_message_id for row in self._rows(self.team)], ["someone-else"])
        self.assertEqual(len(self.storage.objects), 1)

    @parameterized.expand(
        [
            ("virus", ["hi@a.example"], {"virus": "FAIL"}),
            ("unknown_domain", ["hi@nobody.example"], {}),
        ]
    )
    def test_dropped_mail_leaves_nothing_behind(self, _name: str, recipients: list[str], verdicts: Any) -> None:
        with self._patched():
            process_notification(self._notification(recipients, **verdicts))
        self.assertEqual(self._rows(self.team), [])
        self.assertEqual(self.storage.objects, {})
        self.capture.assert_not_called()

    def test_a_domain_another_team_only_tried_to_claim_routes_to_nobody(self) -> None:
        InboundEmailDomain.objects.for_team(self.other_team.pk).create(
            team_id=self.other_team.pk,
            domain="pending.example",
            kind=InboundEmailDomainKind.CUSTOM,
            status=InboundEmailDomainStatus.PENDING,
        )
        lookup = "products.workflows.backend.services.inbound_email.domains.lookup_mx"
        with self._patched(), patch(lookup, return_value=MagicMock(answered=True, records=())):
            process_notification(self._notification(["hi@pending.example"]))
        self.assertEqual(self._rows(self.other_team), [])

    def test_mail_over_the_limit_keeps_only_details(self) -> None:
        notification = self._notification(["hi@a.example"], raw=b"x")
        notification["mail"]["commonHeaders"] = {"from": ["Dana <dana@sender.example>"], "subject": "Huge"}
        size = {"ContentLength": MAX_RAW_BYTES + 1}
        with self._patched(), patch.object(self.storage, "head_object", return_value=size):
            process_notification(notification)
        row = self._rows(self.team)[0]
        self.assertEqual((row.content_status, row.subject), ("too_large", "Huge"))
        self.assertEqual([key for key in self.storage.objects if key.startswith("inbound-email/")], [])

    def test_a_team_over_its_limit_never_downloads_the_message(self) -> None:
        base = "products.workflows.backend.services.inbound_email.intake"
        with self._patched(), patch(f"{base}._over_daily_limit", return_value=True):
            with patch.object(self.storage, "read_bytes") as read_bytes:
                process_notification(self._notification(["hi@a.example"]))
        read_bytes.assert_not_called()
        self.assertEqual(self._rows(self.team), [])

    def test_a_failed_mx_lookup_keeps_the_mail_for_a_retry(self) -> None:
        _verify_sending_domain(self.other_team, "pending.example")
        InboundEmailDomain.objects.for_team(self.other_team.pk).create(
            team_id=self.other_team.pk,
            domain="pending.example",
            kind=InboundEmailDomainKind.CUSTOM,
            status=InboundEmailDomainStatus.PENDING,
        )
        lookup = "products.workflows.backend.services.inbound_email.domains.lookup_mx"
        with self._patched(), patch(lookup, return_value=MagicMock(answered=False, records=())):
            with self.assertRaises(MxLookupUnavailable):
                process_notification(self._notification(["hi@pending.example"]))
        self.assertIn("intake/ses-1", self.storage.objects)

    def test_a_row_stays_when_its_objects_could_not_be_deleted(self) -> None:
        with self._patched():
            process_notification(self._notification(["hi@a.example"]))
        ReceivedEmail.objects.for_team(self.team.pk).update(received_at=timezone.now() - timedelta(days=31))
        fake = MagicMock(ObjectStorageError=ObjectStorageError)
        fake.iter_keys.return_value = ["some/key"]
        fake.delete_objects.return_value = ["some/key"]
        with patch("products.workflows.backend.services.inbound_email.storage.object_storage", fake):
            with self.assertRaises(ObjectStorageError):
                delete_expired_received_emails()
        self.assertEqual(len(self._rows(self.team)), 1)

    def test_an_unreadable_message_is_retried_until_it_appears(self) -> None:
        with self._patched(), self.assertRaises(IntakeObjectMissing):
            process_notification(self._notification(["hi@a.example"], raw=None))

    def test_a_notification_naming_another_bucket_is_ignored(self) -> None:
        notification = self._notification(["hi@a.example"])
        notification["receipt"]["action"]["bucketName"] = "someone-elses-bucket"
        with self._patched():
            process_notification(notification)
        self.assertEqual(self._rows(self.team), [])

    def test_links_the_original_send_and_the_person_of_a_verified_sender(self) -> None:
        send = SendMatch(message_id=uuid4(), workflow_id=uuid4(), method="in_reply_to")  # type: ignore[arg-type]
        base = "products.workflows.backend.services.inbound_email.intake"
        person = MagicMock(person_id=uuid4(), distinct_id="user-1")
        with (
            self._patched(),
            patch(f"{base}.find_person_by_email", return_value=person),
            patch(f"{base}.find_original_send", return_value=send),
        ):
            process_notification(self._notification(["hi@a.example"]))
        row = self._rows(self.team)[0]
        self.assertEqual(row.person_distinct_id, "user-1")
        self.assertEqual(row.original_message_id, send.message_id)
        self.assertEqual(self.capture.call_args.kwargs["distinct_id"], "user-1")

    def test_a_forged_sender_never_reaches_a_person(self) -> None:
        base = "products.workflows.backend.services.inbound_email.intake"
        lookup = MagicMock()
        with self._patched(), patch(f"{base}.find_person_by_email", lookup):
            process_notification(self._notification(["hi@a.example"], dmarc="FAIL", spf="FAIL"))
        lookup.assert_not_called()
        row = self._rows(self.team)[0]
        self.assertEqual(self.capture.call_args.kwargs["distinct_id"], f"received-email-{row.id}")
        self.assertEqual(row.id, received_email_id(self.team.pk, "ses-1"))


@override_settings(WORKFLOWS_INBOUND_EMAIL_MX_HOST=MX_HOST)
class TestReceivingDomains(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.sibling = Team.objects.create(
            organization=self.organization, name="sibling", api_token=f"phc_{uuid4().hex}"
        )
        self.stranger = Team.objects.create(
            organization=Organization.objects.create(name="stranger"), name="stranger", api_token=f"phc_{uuid4().hex}"
        )
        _verify_sending_domain(self.team, "x.example")

    def _row(self, team: Team, status: str = "pending", name: str = "in.x.example") -> InboundEmailDomain:
        return InboundEmailDomain.objects.for_team(team.pk).create(
            team_id=team.pk, domain=name, kind=InboundEmailDomainKind.CUSTOM, status=status
        )

    def test_a_second_project_in_the_organization_cannot_claim_the_domain(self) -> None:
        _verify_sending_domain(self.sibling, "x.example")
        self._row(self.team)
        with patch(f"{DOMAINS}.lookup_mx", return_value=_mx()):
            preflight = preflight_domain(self.sibling.pk, "in.x.example")
        self.assertFalse(preflight.eligible)
        self.assertIn("Another project in this organization", preflight.reason)

    def test_a_claim_whose_sending_domain_is_gone_does_not_hold_the_domain(self) -> None:
        self._row(self.sibling)
        with patch(f"{DOMAINS}.lookup_mx", return_value=_mx()):
            self.assertTrue(preflight_domain(self.team.pk, "in.x.example").eligible)

    def test_an_active_row_whose_sending_domain_is_gone_does_not_block_a_new_owner(self) -> None:
        stale = self._row(self.stranger, status="active")
        with patch(f"{DOMAINS}.lookup_mx", return_value=_mx()):
            self.assertTrue(preflight_domain(self.team.pk, "in.x.example").eligible)
        stale.refresh_from_db()
        self.assertEqual(stale.status, "pending")

    def test_the_later_of_two_competing_claims_cannot_activate(self) -> None:
        _verify_sending_domain(self.sibling, "x.example")
        first = self._row(self.team)
        second = self._row(self.sibling)
        with patch(f"{DOMAINS}.lookup_mx", return_value=_mx(MX_HOST)):
            self.assertEqual(check_domain_mx(second).state, "taken")
            self.assertEqual(check_domain_mx(first).state, "active")

    def test_activation_needs_a_verified_sending_domain(self) -> None:
        row = self._row(self.stranger)
        with patch(f"{DOMAINS}.lookup_mx", return_value=_mx(MX_HOST)):
            self.assertEqual(check_domain_mx(row).state, "no_sending_domain")
        row.refresh_from_db()
        self.assertEqual(row.status, "pending")

    def test_an_active_domain_is_only_demoted_by_failures_over_time(self) -> None:
        row = self._row(self.team, status="active")
        with patch(f"{DOMAINS}.lookup_mx", return_value=_mx("mail.other.example")):
            self.assertEqual(check_domain_mx(row).state, "conflict")
            row.refresh_from_db()
            self.assertEqual(row.status, "active")
            self.assertIsNotNone(row.checks_failing_since)
            check_domain_mx(row)
            row.refresh_from_db()
            self.assertEqual(row.status, "active")
            with time_machine.travel(timezone.now() + CHECK_FAILURE_GRACE + timedelta(minutes=1), tick=False):
                check_domain_mx(row)
        row.refresh_from_db()
        self.assertEqual((row.status, row.checks_failing_since), ("pending", None))

    def test_the_sweep_demotes_a_domain_ses_no_longer_verifies_and_recovery_clears_it(self) -> None:
        row = self._row(self.team, status="active")
        lost = MagicMock(check=MagicMock(every_dns_lookup_answered=True, is_verified=False))
        kept = MagicMock(check=MagicMock(every_dns_lookup_answered=True, is_verified=True))
        status = f"{DOMAINS}.EmailIntegration.status"
        with patch(f"{DOMAINS}.lookup_mx", return_value=_mx(MX_HOST)):
            with patch(status, return_value=lost):
                sweep_active_domains()
            row.refresh_from_db()
            self.assertEqual(row.status, "active")
            self.assertIsNotNone(row.checks_failing_since)

            with patch(status, return_value=kept):
                sweep_active_domains()
            row.refresh_from_db()
            self.assertIsNone(row.checks_failing_since)

            with patch(status, return_value=lost):
                sweep_active_domains()
                with time_machine.travel(timezone.now() + CHECK_FAILURE_GRACE + timedelta(minutes=1), tick=False):
                    sweep_active_domains()
        row.refresh_from_db()
        self.assertEqual(row.status, "pending")

    def test_a_sweep_keeps_going_past_a_domain_that_raises(self) -> None:
        broken, healthy = (
            self._row(self.team, status="active"),
            self._row(self.team, status="active", name="other.x.example"),
        )
        kept = MagicMock(check=MagicMock(every_dns_lookup_answered=True, is_verified=True))
        lookup = MagicMock(side_effect=[RuntimeError("dns"), _mx(MX_HOST)])
        with patch(f"{DOMAINS}.lookup_mx", lookup), patch(f"{DOMAINS}.EmailIntegration.status", return_value=kept):
            sweep_active_domains()
        self.assertEqual(lookup.call_count, 2)
        for row in (broken, healthy):
            row.refresh_from_db()
            self.assertEqual(row.status, "active")


class TestIsSenderVerified(SimpleTestCase):
    @parameterized.expand(
        [
            ("dmarc_pass", "PASS", "FAIL", "x@other.example", "a@x.example", "a@x.example", True),
            ("dmarc_fail_even_if_spf_aligned", "FAIL", "PASS", "a@x.example", "a@x.example", "a@x.example", False),
            ("no_dmarc_spf_aligned", "GRAY", "PASS", "bounce@x.example", "a@x.example", "a@x.example", True),
            ("no_dmarc_spf_other_domain", "GRAY", "PASS", "bounce@esp.example", "a@x.example", "a@x.example", False),
            ("no_from_at_all", "PASS", "PASS", "a@x.example", "", "", False),
            ("receipt_names_another_domain", "PASS", "PASS", "a@x.example", "a@x.example", "b@y.example", False),
            ("no_receipt_from", "PASS", "PASS", "a@x.example", "a@x.example", "", False),
        ]
    )
    def test_verdicts(
        self, _name: str, dmarc: str, spf: str, envelope: str, from_address: str, receipt_from: str, expected: bool
    ) -> None:
        self.assertEqual(
            is_sender_verified(
                dmarc=dmarc, spf=spf, envelope_from=envelope, from_address=from_address, receipt_from=receipt_from
            ),
            expected,
        )

    @parameterized.expand(
        [
            ("regional", "<abc-123@eu-central-1.amazonses.com>", "abc-123"),
            ("email_host", "<abc-123@email.amazonses.com>", "abc-123"),
            ("someone_elses", "<abc-123@mail.example.com>", None),
            ("lookalike", "<abc@amazonses.com.evil.example>", None),
        ]
    )
    def test_ses_message_id(self, _name: str, header: str, expected: str | None) -> None:
        self.assertEqual(ses_message_id(header), expected)
