import json
import base64
from typing import Any

from django.test import SimpleTestCase, override_settings

import requests
from parameterized import parameterized

from products.workflows.backend.services.ses_events_dlq import (
    DlqQueue,
    ReplayNotConfigured,
    ReplayOptions,
    replay_queue,
    summarize_message,
)

QUEUE = DlqQueue(url="https://sqs.eu-central-1.amazonaws.com/000000000000/ses-events-posthog-messaging-dlq")


def tracking_code(team_id: int) -> str:
    payload = base64.urlsafe_b64encode(f"v2:fn-1:inv-1:{team_id}:action-1::0".encode()).decode().rstrip("=")
    return f"{payload}.signature"


def sns_message(message_id: str, event_type: str = "Bounce", team_id: int = 7) -> dict[str, Any]:
    record = {
        "eventType": event_type,
        "mail": {
            "timestamp": "2026-11-01T10:00:00.000Z",
            "messageId": f"ses-{message_id}",
            "source": "sender@example.com",
            "destination": ["recipient@example.com"],
            "tags": {"ph_id": [tracking_code(team_id)]},
        },
    }
    envelope = {
        "Type": "Notification",
        "MessageId": f"sns-{message_id}",
        "TopicArn": "arn:aws:sns:eu-central-1:000000000000:ses-events-posthog-messaging",
        "Message": json.dumps(record),
        "Timestamp": "2026-11-01T10:00:01.000Z",
        "SignatureVersion": "1",
        "Signature": "c2lnbmF0dXJl",
        "SigningCertURL": "https://sns.eu-central-1.amazonaws.com/cert.pem",
    }
    return {
        "MessageId": message_id,
        "ReceiptHandle": f"receipt-{message_id}",
        "Body": json.dumps(envelope),
        "Attributes": {"SentTimestamp": "1793700000000"},
    }


class FakeSqs:
    def __init__(self, messages: list[dict[str, Any]]):
        self.messages = {m["MessageId"]: m for m in messages}
        self.hidden: set[str] = set()

    def _by_receipt(self, handle: str) -> str:
        return next(mid for mid, m in self.messages.items() if m["ReceiptHandle"] == handle)

    def receive_message(self, *, MaxNumberOfMessages: int, VisibilityTimeout: int, **_: Any) -> dict[str, Any]:
        visible = [m for mid, m in self.messages.items() if mid not in self.hidden][:MaxNumberOfMessages]
        if VisibilityTimeout > 0:
            self.hidden.update(m["MessageId"] for m in visible)
        return {"Messages": visible}

    def delete_message(self, *, ReceiptHandle: str, **_: Any) -> None:
        del self.messages[self._by_receipt(ReceiptHandle)]

    def change_message_visibility_batch(self, *, Entries: list[dict[str, Any]], **_: Any) -> None:
        for entry in Entries:
            assert entry["VisibilityTimeout"] == 0
            self.hidden.discard(self._by_receipt(entry["ReceiptHandle"]))

    @property
    def visible_ids(self) -> set[str]:
        return set(self.messages) - self.hidden


class StubWebhook:
    def __init__(self, statuses: dict[str, int | Exception] | None = None):
        self.statuses = statuses or {}
        self.posted: list[str] = []

    def __call__(self, body: str) -> int:
        message_id = json.loads(body)["MessageId"].removeprefix("sns-")
        self.posted.append(message_id)
        status = self.statuses.get(message_id, 200)
        if isinstance(status, Exception):
            raise status
        return status


def run(sqs: FakeSqs, webhook: StubWebhook, *, dry_run: bool = False, limit: int = 100, max_per_second: float = 1000.0):
    return replay_queue(
        QUEUE,
        ReplayOptions(dry_run=dry_run, limit=limit, max_per_second=max_per_second),
        sqs=sqs,  # type: ignore[arg-type]
        triggered_by="test",
        post=webhook,
        clock=lambda: 0.0,
        sleep=lambda seconds: None,
    )


@override_settings(SES_EVENTS_REPLAY_WEBHOOK_URL="http://cdp-api-webhooks.test/public/m/ses_webhook")
class TestReplaySesEventsDlq(SimpleTestCase):
    def test_accepted_messages_leave_the_queue(self) -> None:
        sqs = FakeSqs([sns_message("a", "Bounce", team_id=7), sns_message("b", "Delivery", team_id=8)])
        webhook = StubWebhook()

        report = run(sqs, webhook)

        assert webhook.posted == ["a", "b"]
        assert sqs.messages == {}
        assert report.to_dict()["by_event_type"] == {"Bounce": {"replayed": 1}, "Delivery": {"replayed": 1}}
        assert report.to_dict()["by_team"] == {"7": {"replayed": 1}, "8": {"replayed": 1}}

    @parameterized.expand(
        [
            ("server_error", 500, "webhook answered 500"),
            ("forbidden", 403, "webhook answered 403"),
            ("timeout", requests.Timeout("read timed out"), "Timeout: read timed out"),
        ]
    )
    def test_failed_messages_stay_in_the_queue_and_become_visible(
        self, _name: str, failure: int | Exception, error: str
    ) -> None:
        sqs = FakeSqs([sns_message("a"), sns_message("b")])

        report = run(sqs, StubWebhook({"b": failure}))

        assert sqs.visible_ids == {"b"}
        assert report.totals == {"replayed": 1, "failed": 1}
        assert [(f.message_id, f.error) for f in report.failures] == [("b", error)]

    def test_dry_run_posts_and_deletes_nothing(self) -> None:
        sqs = FakeSqs([sns_message("a", "Open"), sns_message("b", "Click")])
        webhook = StubWebhook()

        report = run(sqs, webhook, dry_run=True)

        assert webhook.posted == []
        assert sqs.visible_ids == {"a", "b"}
        assert report.totals == {"would_replay": 2}

    def test_limit_caps_the_messages_taken(self) -> None:
        sqs = FakeSqs([sns_message(str(i)) for i in range(25)])
        webhook = StubWebhook()

        report = run(sqs, webhook, limit=12)

        assert len(webhook.posted) == 12
        assert len(sqs.messages) == 13
        assert report.totals == {"replayed": 12}

    def test_a_body_that_is_not_a_signed_notification_is_kept_without_posting(self) -> None:
        raw_record = {**sns_message("a"), "Body": json.dumps({"eventType": "Bounce", "mail": {}})}
        sqs = FakeSqs([raw_record])
        webhook = StubWebhook()

        report = run(sqs, webhook)

        assert webhook.posted == []
        assert sqs.visible_ids == {"a"}
        assert report.totals == {"unparseable": 1}

    def test_posts_are_spaced_by_the_rate_limit(self) -> None:
        sqs = FakeSqs([sns_message(str(i)) for i in range(3)])
        sleeps: list[float] = []
        now = [0.0]

        def sleep(seconds: float) -> None:
            sleeps.append(seconds)
            now[0] += seconds

        replay_queue(
            QUEUE,
            ReplayOptions(dry_run=False, limit=10, max_per_second=4),
            sqs=sqs,  # type: ignore[arg-type]
            triggered_by="test",
            post=StubWebhook(),
            clock=lambda: now[0],
            sleep=sleep,
        )

        assert sleeps == [0.25, 0.25]

    @override_settings(SES_EVENTS_REPLAY_WEBHOOK_URL="")
    def test_refuses_to_replay_without_a_webhook_url(self) -> None:
        with self.assertRaises(ReplayNotConfigured):
            run(FakeSqs([sns_message("a")]), StubWebhook())


class TestSummarizeDlqMessage(SimpleTestCase):
    def test_reads_event_team_and_masked_recipient(self) -> None:
        summary = summarize_message(sns_message("a", "Complaint", team_id=42))

        assert (summary.event_type, summary.team_id, summary.masked_recipient, summary.replayable) == (
            "Complaint",
            42,
            "r***@example.com",
            True,
        )
