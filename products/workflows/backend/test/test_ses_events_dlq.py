import json
import base64
from collections.abc import Callable
from typing import Any

from django.test import SimpleTestCase, override_settings

import requests
from botocore.exceptions import ClientError
from parameterized import parameterized

from products.workflows.backend.services.ses_events_dlq import (
    MIN_MAX_PER_SECOND,
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
    def __init__(
        self,
        messages: list[dict[str, Any]],
        refuse_release: set[str] | None = None,
        release_errors: int = 0,
        clock: Callable[[], float] = lambda: 0.0,
    ):
        self.messages = {m["MessageId"]: m for m in messages}
        self.receipts = {m["ReceiptHandle"]: m["MessageId"] for m in messages}
        self.hidden: set[str] = set()
        self.refuse_release = refuse_release or set()
        self.release_errors = release_errors
        self.release_calls = 0
        self.clock = clock
        self.received_at: dict[str, float] = {}

    def _by_receipt(self, handle: str) -> str:
        return self.receipts[handle]

    def receive_message(self, *, MaxNumberOfMessages: int, VisibilityTimeout: int, **_: Any) -> dict[str, Any]:
        visible = [m for mid, m in self.messages.items() if mid not in self.hidden][:MaxNumberOfMessages]
        if VisibilityTimeout > 0:
            self.hidden.update(m["MessageId"] for m in visible)
            self.received_at.update((m["MessageId"], self.clock()) for m in visible)
        return {"Messages": visible}

    def delete_message(self, *, ReceiptHandle: str, **_: Any) -> None:
        del self.messages[self._by_receipt(ReceiptHandle)]

    def change_message_visibility_batch(self, *, Entries: list[dict[str, Any]], **_: Any) -> dict[str, Any]:
        self.release_calls += 1
        if self.release_calls <= self.release_errors:
            raise ClientError({"Error": {"Code": "ServiceUnavailable"}}, "ChangeMessageVisibilityBatch")
        failed = []
        for entry in Entries:
            assert entry["VisibilityTimeout"] == 0
            message_id = self._by_receipt(entry["ReceiptHandle"])
            if message_id in self.refuse_release:
                failed.append({"Id": entry["Id"], "Code": "ReceiptHandleIsInvalid", "SenderFault": True})
            else:
                self.hidden.discard(message_id)
        return {"Successful": [], "Failed": failed}

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

    @parameterized.expand(
        [
            ("mail_null", None),
            ("mail_not_an_object", "oops"),
            ("headers_not_objects", {"headers": ["x-posthog-tracking-code"], "destination": "a@example.com"}),
            ("tags_not_lists", {"tags": {"ph_id": "abc"}, "timestamp": 5}),
        ]
    )
    def test_an_unexpected_ses_record_shape_still_replays_and_the_run_continues(self, _name: str, mail: Any) -> None:
        odd = sns_message("a")
        envelope = json.loads(odd["Body"])
        envelope["Message"] = json.dumps({"eventType": "Bounce", "mail": mail})
        odd["Body"] = json.dumps(envelope)
        sqs = FakeSqs([odd, sns_message("b")])
        webhook = StubWebhook()

        report = run(sqs, webhook)

        assert webhook.posted == ["a", "b"]
        assert sqs.messages == {}
        assert report.to_dict()["by_team"] == {"unknown": {"replayed": 1}, "7": {"replayed": 1}}

    @parameterized.expand(
        [
            ("slow_webhook", 25, 1000.0, 12.0),
            ("minimum_rate_past_the_sqs_visibility_cap", 5000, MIN_MAX_PER_SECOND, 0.5),
        ]
    )
    def test_a_run_stops_before_kept_messages_outlive_their_visibility(
        self, _name: str, count: int, max_per_second: float, post_seconds: float
    ) -> None:
        now = [0.0]
        sqs = FakeSqs([sns_message(str(i)) for i in range(count)], clock=lambda: now[0])
        options = ReplayOptions(dry_run=False, limit=count, max_per_second=max_per_second)
        posts_ended_at: dict[str, float] = {}

        def slow_post(body: str) -> int:
            now[0] += post_seconds
            posts_ended_at[json.loads(body)["MessageId"].removeprefix("sns-")] = now[0]
            return 200

        def sleep(seconds: float) -> None:
            now[0] += seconds

        report = replay_queue(
            QUEUE,
            options,
            sqs=sqs,  # type: ignore[arg-type]
            triggered_by="test",
            post=slow_post,
            clock=lambda: now[0],
            sleep=sleep,
        )

        late = [
            mid
            for mid, ended in posts_ended_at.items()
            if ended >= sqs.received_at[mid] + options.visibility_timeout_seconds
        ]
        assert late == []
        assert report.stopped_at_deadline
        assert report.totals == {"replayed": len(posts_ended_at)}
        assert sqs.visible_ids == set(sqs.messages)
        assert len(sqs.messages) == count - len(posts_ended_at) > 0

    @parameterized.expand([("release_works", 0, {"0", "1", "2", "3", "4"}), ("release_fails_too", 99, set())])
    def test_an_error_mid_batch_still_releases_every_received_message_and_surfaces(
        self, _name: str, release_errors: int, visible: set[str]
    ) -> None:
        sqs = FakeSqs([sns_message(str(i)) for i in range(5)], release_errors=release_errors)

        def boom(body: str) -> int:
            raise RuntimeError("bug")

        with self.assertRaises(RuntimeError):
            replay_queue(
                QUEUE,
                ReplayOptions(dry_run=False, limit=5, max_per_second=1000.0),
                sqs=sqs,  # type: ignore[arg-type]
                triggered_by="test",
                post=boom,
                clock=lambda: 0.0,
                sleep=lambda seconds: None,
            )

        assert sqs.visible_ids == visible

    @parameterized.expand(
        [
            ("entry_refused", {"b"}, 0, {"a"}, 1),
            ("transient_client_error", set(), 1, {"a", "b"}, 0),
            ("client_error_every_attempt", set(), 3, set(), 2),
        ]
    )
    def test_kept_messages_sqs_will_not_release_are_retried_and_reported(
        self, _name: str, refuse: set[str], release_errors: int, visible: set[str], unreleased: int
    ) -> None:
        sqs = FakeSqs([sns_message("a"), sns_message("b")], refuse_release=refuse, release_errors=release_errors)

        report = run(sqs, StubWebhook({"a": 500, "b": 500}))

        assert sqs.visible_ids == visible
        assert report.to_dict()["unreleased"] == unreleased

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

    def test_refuses_a_rate_whose_pacing_wait_would_outlast_the_deadline_margin(self) -> None:
        with self.assertRaises(ValueError):
            ReplayOptions(dry_run=False, limit=10, max_per_second=MIN_MAX_PER_SECOND / 2)

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
