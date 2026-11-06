import json
import base64
from collections.abc import Callable
from typing import Any

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

import requests
from botocore.exceptions import ClientError
from parameterized import parameterized

from products.workflows.backend.services import ses_events_dlq
from products.workflows.backend.services.ses_events_dlq import (
    MIN_MAX_PER_SECOND,
    DlqQueue,
    ReplayNotConfigured,
    ReplayOptions,
    replay_queue,
    summarize_message,
)

QUEUE = DlqQueue(url="https://sqs.eu-central-1.amazonaws.com/000000000000/ses-events-posthog-messaging-dlq")
WEBHOOK_URL = "http://cdp-api-webhooks.cdp-api-webhooks.svc.cluster.local/public/m/ses_webhook"


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
    """An SQS queue whose leases expire on the injected clock, like the real one."""

    MAX_VISIBILITY_SECONDS = 43_200

    def __init__(
        self,
        messages: list[dict[str, Any]],
        refuse_release: set[str] | None = None,
        release_errors: int = 0,
        clock: Callable[[], float] = lambda: 0.0,
        advance: Callable[[float], None] = lambda seconds: None,
        call_seconds: float = 0.0,
        refuse_renewal: bool = False,
        false_empty_receives: int = 0,
    ):
        self.messages = {m["MessageId"]: m for m in messages}
        self.handles: dict[str, str] = {}
        self.visible_after: dict[str, float] = {}
        self.received_at: dict[str, float] = {}
        self.refuse_release = refuse_release or set()
        self.release_errors = release_errors
        self.release_calls = 0
        self.clock = clock
        self.advance = advance
        self.call_seconds = call_seconds
        self.refuse_renewal = refuse_renewal
        self.false_empty_receives = false_empty_receives

    def _hide(self, message_id: str, timeout: int) -> None:
        self.visible_after[message_id] = min(
            self.clock() + timeout, self.received_at[message_id] + self.MAX_VISIBILITY_SECONDS
        )

    def _is_visible(self, message_id: str) -> bool:
        return self.visible_after.get(message_id, float("-inf")) <= self.clock()

    def receive_message(self, *, MaxNumberOfMessages: int, VisibilityTimeout: int, **_: Any) -> dict[str, Any]:
        visible = [mid for mid in self.messages if self._is_visible(mid)][:MaxNumberOfMessages]
        if VisibilityTimeout == 0:
            return {"Messages": [self.messages[mid] for mid in visible]}
        if self.false_empty_receives:
            self.false_empty_receives -= 1
            return {"Messages": []}
        received = []
        for mid in visible:
            self.handles[mid] = f"receipt-{mid}-{self.clock()}"
            self.received_at[mid] = self.clock()
            self._hide(mid, VisibilityTimeout)
            received.append({**self.messages[mid], "ReceiptHandle": self.handles[mid]})
        return {"Messages": received}

    def delete_message(self, *, ReceiptHandle: str, **_: Any) -> None:
        del self.messages[ReceiptHandle.split("-")[1]]

    def change_message_visibility_batch(self, *, Entries: list[dict[str, Any]], **_: Any) -> dict[str, Any]:
        self.release_calls += 1
        self.advance(self.call_seconds)
        if self.release_calls <= self.release_errors:
            raise ClientError({"Error": {"Code": "ServiceUnavailable"}}, "ChangeMessageVisibilityBatch")
        failed = []
        for entry in Entries:
            message_id = entry["ReceiptHandle"].split("-")[1]
            # SQS refuses a stale receipt handle, and a message whose lease already ran out.
            stale = self.handles.get(message_id) != entry["ReceiptHandle"] or self._is_visible(message_id)
            refused = message_id in self.refuse_release if entry["VisibilityTimeout"] == 0 else self.refuse_renewal
            if stale or refused:
                failed.append({"Id": entry["Id"], "Code": "ReceiptHandleIsInvalid", "SenderFault": True})
            else:
                self._hide(message_id, entry["VisibilityTimeout"])
        return {"Successful": [], "Failed": failed}

    @property
    def visible_ids(self) -> set[str]:
        return {mid for mid in self.messages if self._is_visible(mid)}

    def lapsed_leases(self) -> set[str]:
        return {mid for mid in self.received_at if mid in self.messages and self._is_visible(mid)}


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
    @parameterized.expand([("every_receive_answers", 0), ("sqs_answers_empty_while_messages_wait", 2)])
    def test_accepted_messages_leave_the_queue(self, _name: str, false_empty_receives: int) -> None:
        sqs = FakeSqs(
            [sns_message("a", "Bounce", team_id=7), sns_message("b", "Delivery", team_id=8)],
            false_empty_receives=false_empty_receives,
        )
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
            ("slow_failing_webhook_past_the_visibility_timeout", 25, 20.0, 500, {}, None),
            ("run_past_the_sqs_visibility_cap", 1000, 50.0, 200, {}, "run_limit"),
            ("renewal_refused", 25, 20.0, 500, {"refuse_renewal": True}, "lease_lost"),
            ("renewal_pass_slower_than_the_lease", 900, 0.5, 500, {"call_seconds": 4.0}, "lease_lost"),
            ("more_kept_messages_than_the_held_limit", 1200, 0.0, 500, {}, "held_limit"),
        ]
    )
    def test_held_messages_stay_hidden_for_the_whole_run(
        self, _name: str, count: int, post_seconds: float, status: int, sqs_kwargs: dict, reason: str | None
    ) -> None:
        now = [0.0]

        def advance(seconds: float) -> None:
            now[0] += seconds

        sqs = FakeSqs([sns_message(str(i)) for i in range(count)], clock=lambda: now[0], advance=advance, **sqs_kwargs)
        posted: list[str] = []
        lapsed: set[str] = set()

        def slow_post(body: str) -> int:
            lapsed.update(sqs.lapsed_leases())
            posted.append(json.loads(body)["MessageId"].removeprefix("sns-"))
            advance(post_seconds)
            return status

        report = replay_queue(
            QUEUE,
            ReplayOptions(dry_run=False, limit=count, max_per_second=1000.0),
            sqs=sqs,  # type: ignore[arg-type]
            triggered_by="test",
            post=slow_post,
            clock=lambda: now[0],
            sleep=advance,
        )

        assert lapsed == set()
        assert len(posted) == len(set(posted))
        assert report.stopped_reason == reason
        assert (len(posted) < count) == (reason is not None)
        assert sqs.visible_ids == set(sqs.messages)

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

    def test_refuses_a_rate_whose_pacing_wait_would_outlast_the_heartbeat(self) -> None:
        with self.assertRaises(ValueError):
            ReplayOptions(dry_run=False, limit=10, max_per_second=MIN_MAX_PER_SECOND / 2)

    @override_settings(SES_EVENTS_REPLAY_WEBHOOK_URL="")
    def test_refuses_to_replay_without_a_webhook_url(self) -> None:
        with self.assertRaises(ReplayNotConfigured):
            run(FakeSqs([sns_message("a")]), StubWebhook())


class TestPostToWebhook(SimpleTestCase):
    @override_settings(SES_EVENTS_REPLAY_WEBHOOK_URL=WEBHOOK_URL)
    def test_posts_the_unchanged_body_as_text_without_the_egress_proxy(self) -> None:
        # Django pods get Smokescreen in HTTP_PROXY, and Smokescreen refuses cluster-local hosts.
        # The webhook reads the body with express.text() and checks the SNS signature over it, so a
        # JSON body or a re-serialized envelope breaks every replay.
        body = sns_message("a")["Body"]
        response = requests.Response()
        response.status_code = 200
        with patch.object(ses_events_dlq.internal_requests, "post", return_value=response) as post:
            status = ses_events_dlq.post_to_webhook(body)

        assert status == 200
        assert ses_events_dlq.internal_requests.trust_env is False
        post.assert_called_once_with(
            WEBHOOK_URL,
            data=body.encode(),
            headers={"Content-Type": "text/plain; charset=UTF-8", "x-amz-sns-message-type": "Notification"},
            timeout=ses_events_dlq.WEBHOOK_TIMEOUT_SECONDS,
        )


class TestSummarizeDlqMessage(SimpleTestCase):
    def test_reads_event_team_and_masked_recipient(self) -> None:
        summary = summarize_message(sns_message("a", "Complaint", team_id=42))

        assert (summary.event_type, summary.team_id, summary.masked_recipient, summary.replayable) == (
            "Complaint",
            42,
            "r***@example.com",
            True,
        )


class TestSesEventsDlqConsoleTool(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)

    @time_machine.travel("2026-11-03T12:00:00Z", tick=False)
    @override_settings(
        SES_EVENTS_DLQ_URLS=[QUEUE.url, "https://sqs.eu-central-1.amazonaws.com/000000000000/ses-events-other-dlq"]
    )
    @patch("products.workflows.backend.facade.ses_events_dlq.sqs_client")
    def test_shows_each_queue_and_masks_recipients(self, sqs_client: MagicMock) -> None:
        readable = MagicMock()
        readable.get_queue_attributes.return_value = {
            "Attributes": {"ApproximateNumberOfMessages": "3", "ApproximateNumberOfMessagesNotVisible": "1"}
        }
        readable.receive_message.return_value = {
            "Messages": [sns_message("a", "Bounce", team_id=42), sns_message("b", "Delivery", team_id=-1)]
        }
        unreadable = MagicMock()
        unreadable.get_queue_attributes.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "not allowed"}}, "GetQueueAttributes"
        )
        sqs_client.side_effect = lambda queue, _config: readable if queue == QUEUE else unreadable

        response = self.client.get("/admin/console/tools/ses-events-dlq/")

        assert response.status_code == 200
        content = response.content.decode()
        assert QUEUE.name in content
        assert "Could not read the queue: AccessDenied<" in content
        assert 'href="/admin/console/teams/42/"' in content
        assert "Delivery" in content and "/admin/console/teams/-1/" not in content
        assert "r***@example.com" in content
        assert "recipient@example.com" not in content
        assert "2 h 0 min" in content
