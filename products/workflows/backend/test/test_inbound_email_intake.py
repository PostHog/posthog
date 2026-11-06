import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from typing import Any
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from parameterized import parameterized

from posthog.models.organization import Organization
from posthog.models.team import Team
from posthog.storage.object_storage import ObjectStorageError

from products.workflows.backend.facade.enums import InboundEmailDomainKind, InboundEmailDomainStatus
from products.workflows.backend.models import InboundEmailDomain, ReceivedEmail
from products.workflows.backend.services.inbound_email.intake import (
    IntakeObjectMissing,
    MxLookupUnavailable,
    is_sender_verified,
    process_notification,
    received_email_id,
)
from products.workflows.backend.services.inbound_email.matching import SendMatch, ses_message_id
from products.workflows.backend.services.inbound_email.parsing import MAX_RAW_BYTES
from products.workflows.backend.services.inbound_email.retention import delete_expired_received_emails

BUCKET = "qa-bucket"
SIMPLE = (
    b"Received: by mx for <other@b.example>;\r\nFrom: Dana <dana@sender.example>\r\nTo: hi@a.example\r\n"
    b"Subject: Hello\r\nMessage-ID: <1@sender.example>\r\n\r\nThanks\r\n"
)


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


@override_settings(
    WORKFLOWS_INBOUND_EMAIL_BUCKET=BUCKET,
    WORKFLOWS_INBOUND_EMAIL_INTAKE_PREFIX="intake/",
    WORKFLOWS_INBOUND_EMAIL_MX_HOST="inbound-smtp.example.amazonaws.com",
)
class TestProcessNotification(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.storage = _FakeStorage()
        self.other_team = Team.objects.create(
            organization=Organization.objects.create(name="other"), name="other", api_token=f"phc_{uuid4().hex}"
        )
        for team, name in ((self.team, "a.example"), (self.other_team, "b.example")):
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
            "mail": {"messageId": ses_id, "source": verdicts.get("source", "dana@sender.example"), "commonHeaders": {}},
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
            ("spam", {"spam": "FAIL"}, SIMPLE, "spam"),
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
        self.capture.assert_not_called()

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


class TestIsSenderVerified(SimpleTestCase):
    @parameterized.expand(
        [
            ("dmarc_pass", "PASS", "FAIL", "x@other.example", "a@x.example", True),
            ("dmarc_fail_even_if_spf_aligned", "FAIL", "PASS", "a@x.example", "a@x.example", False),
            ("no_dmarc_spf_aligned", "GRAY", "PASS", "bounce@x.example", "a@x.example", True),
            ("no_dmarc_spf_other_domain", "GRAY", "PASS", "bounce@esp.example", "a@x.example", False),
            ("no_from_at_all", "PASS", "PASS", "a@x.example", "", False),
        ]
    )
    def test_verdicts(self, _name: str, dmarc: str, spf: str, envelope: str, from_address: str, expected: bool) -> None:
        self.assertEqual(
            is_sender_verified(dmarc=dmarc, spf=spf, envelope_from=envelope, from_address=from_address), expected
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
