"""Inspect and replay the dead-letter queues of the SES events SNS subscriptions.

SES posts delivery, bounce, complaint, open and click events through SNS to the CDP webhook
(`/public/m/ses_webhook` on cdp-api-webhooks). SNS retries a failed delivery for about two minutes and
then moves the notification to the subscription's dead-letter queue. Each queued body is the signed SNS
envelope that SNS tried to deliver, so replay posts it unchanged and the webhook verifies the signature
and the topic as it does for a live delivery. The webhook does not check the age of a notification.

A replay can count a metric twice. The webhook writes metrics before the suppression list and the email
statuses, so a notification that failed after its first metric write writes that metric again on replay.
"""

import json
import time
import base64
import binascii
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlparse

from django.conf import settings

import boto3
import requests
import structlog
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from posthog.dataclasses import frozen
from posthog.security.outbound_proxy import internal_requests

if TYPE_CHECKING:
    from types_boto3_sqs import SQSClient

logger = structlog.get_logger(__name__)

ReplayOutcome = Literal["replayed", "failed", "unparseable", "would_replay"]
StopReason = Literal["run_limit", "held_limit", "lease_lost"]

RECEIVE_BATCH_SIZE = 10
WEBHOOK_TIMEOUT_SECONDS = 10
MAX_REPORTED_FAILURES = 50
RELEASE_ATTEMPTS = 3
MIN_MAX_PER_SECOND = 0.1
# A run hides every message it holds for this long and renews that every HEARTBEAT_SECONDS. A single post,
# pacing wait or SQS call has to take longer than the difference before a held message can show again.
VISIBILITY_TIMEOUT_SECONDS = 300
HEARTBEAT_SECONDS = 60
# SQS ends a message's visibility 12 hours after it was received, however often the run renews it.
MAX_RUN_SECONDS = 11 * 3600
# Bounds the renewal work of one heartbeat to 100 batch calls.
MAX_HELD_MESSAGES = 1000
TRACKING_CODE_HEADER = "x-posthog-tracking-code"
VERSIONED_TRACKING_CODE_MARKER = "v2"


class ReplayNotConfigured(Exception):
    pass


@frozen
class DlqQueue:
    url: str

    @property
    def name(self) -> str:
        return self.url.rstrip("/").rsplit("/", 1)[-1]

    @property
    def region(self) -> str:
        # Queue URLs look like https://sqs.<region>.amazonaws.com/<account>/<name>. A local endpoint
        # carries no region, so it uses the SES region.
        host_parts = (urlparse(self.url).hostname or "").split(".")
        if len(host_parts) >= 3 and host_parts[0] == "sqs":
            return host_parts[1]
        return settings.SES_REGION


def configured_queues() -> list[DlqQueue]:
    return [DlqQueue(url=url) for url in settings.SES_EVENTS_DLQ_URLS]


def find_queue(name: str) -> DlqQueue | None:
    return next((queue for queue in configured_queues() if queue.name == name), None)


def sqs_client(queue: DlqQueue) -> "SQSClient":
    return boto3.client(
        "sqs", region_name=queue.region, config=Config(connect_timeout=5, read_timeout=20, retries={"max_attempts": 3})
    )


@frozen
class DlqMessageSummary:
    message_id: str
    event_type: str
    # Read from the unverified tracking code, so it only says where to look, never who to trust.
    team_id: int | None
    ses_timestamp: str | None
    masked_recipient: str | None
    dead_lettered_at: datetime | None
    replayable: bool


def summarize_message(message: dict[str, Any]) -> DlqMessageSummary:
    envelope = _parse_envelope(message.get("Body", ""))
    record = _parse_json_object(envelope.get("Message", "")) if envelope else None
    mail = _as_dict((record or {}).get("mail"))
    destinations = mail.get("destination")
    timestamp = mail.get("timestamp")
    return DlqMessageSummary(
        message_id=str(message.get("MessageId", "")),
        event_type=str((record or {}).get("eventType") or "unknown"),
        team_id=_team_id_from_mail(mail),
        ses_timestamp=timestamp if isinstance(timestamp, str) else None,
        masked_recipient=_mask_email(destinations[0] if isinstance(destinations, list) and destinations else None),
        dead_lettered_at=_sent_timestamp(message),
        replayable=envelope is not None,
    )


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _parse_json_object(text: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _parse_envelope(body: str) -> dict[str, Any] | None:
    # Only a signed Notification can pass the webhook. A raw SES record has no signature and the
    # webhook refuses it, so posting one would only add a failure.
    envelope = _parse_json_object(body)
    if envelope is None or envelope.get("Type") != "Notification" or not envelope.get("Signature"):
        return None
    return envelope


def _team_id_from_mail(mail: dict[str, Any]) -> int | None:
    headers = mail.get("headers")
    header = next(
        (
            h.get("value")
            for h in (headers if isinstance(headers, list) else [])
            if isinstance(h, dict) and str(h.get("name", "")).lower() == TRACKING_CODE_HEADER
        ),
        None,
    )
    tags = _as_dict(mail.get("tags")).get("ph_id")
    tag = tags[0] if isinstance(tags, list) and tags else None
    code = header or tag
    if not isinstance(code, str) or not code:
        return None
    payload = code.split(".", 1)[0]
    try:
        decoded = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)).decode()
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    fields = decoded.split(":")
    if fields and fields[0] == VERSIONED_TRACKING_CODE_MARKER:
        fields = fields[1:]
    try:
        return int(fields[2])
    except (IndexError, ValueError):
        return None


def _mask_email(address: Any) -> str | None:
    if not isinstance(address, str) or "@" not in address:
        return None
    local, domain = address.rsplit("@", 1)
    return f"{local[:1]}***@{domain}"


def _sent_timestamp(message: dict[str, Any]) -> datetime | None:
    raw = _as_dict(message.get("Attributes")).get("SentTimestamp")
    if raw is None:
        return None
    try:
        return datetime.fromtimestamp(int(raw) / 1000, tz=UTC)
    except (TypeError, ValueError):
        return None


@frozen
class QueueSnapshot:
    queue: DlqQueue
    visible: int
    in_flight: int
    oldest_sampled_at: datetime | None
    sample: list[DlqMessageSummary]


def inspect_queue(queue: DlqQueue, sqs: "SQSClient") -> QueueSnapshot:
    attributes = sqs.get_queue_attributes(
        QueueUrl=queue.url,
        AttributeNames=["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"],
    )["Attributes"]
    # A zero visibility timeout reads the sample without hiding it from a replay that runs next.
    sampled = sqs.receive_message(
        QueueUrl=queue.url,
        MaxNumberOfMessages=RECEIVE_BATCH_SIZE,
        VisibilityTimeout=0,
        WaitTimeSeconds=1,
        MessageSystemAttributeNames=["SentTimestamp"],
    ).get("Messages", [])
    sample = [summarize_message(dict(message)) for message in sampled]
    sent_times = [s.dead_lettered_at for s in sample if s.dead_lettered_at is not None]
    return QueueSnapshot(
        queue=queue,
        visible=int(attributes.get("ApproximateNumberOfMessages", 0)),
        in_flight=int(attributes.get("ApproximateNumberOfMessagesNotVisible", 0)),
        oldest_sampled_at=min(sent_times) if sent_times else None,
        sample=sample,
    )


@frozen
class ReplayOptions:
    dry_run: bool
    limit: int
    max_per_second: float

    def __post_init__(self) -> None:
        if self.limit < 1:
            raise ValueError("limit must be at least 1")
        if self.max_per_second < MIN_MAX_PER_SECOND:
            raise ValueError(f"max_per_second must be at least {MIN_MAX_PER_SECOND}")


@frozen
class ReplayFailure:
    message_id: str
    event_type: str
    error: str


@frozen(frozen=False)
class ReplayReport:
    queue_name: str
    dry_run: bool
    by_event_type: Counter[tuple[str, ReplayOutcome]]
    by_team: Counter[tuple[int | None, ReplayOutcome]]
    failures: list[ReplayFailure]
    stopped_reason: StopReason | None = None
    # Kept messages that SQS did not make visible again. They return when their visibility timeout ends.
    unreleased: int = 0

    @property
    def totals(self) -> Counter[ReplayOutcome]:
        totals: Counter[ReplayOutcome] = Counter()
        for (_, outcome), count in self.by_event_type.items():
            totals[outcome] += count
        return totals

    def record(self, summary: DlqMessageSummary, outcome: ReplayOutcome, error: str | None = None) -> None:
        self.by_event_type[(summary.event_type, outcome)] += 1
        self.by_team[(summary.team_id, outcome)] += 1
        if error is not None and len(self.failures) < MAX_REPORTED_FAILURES:
            self.failures.append(
                ReplayFailure(message_id=summary.message_id, event_type=summary.event_type, error=error)
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "queue": self.queue_name,
            "dry_run": self.dry_run,
            "totals": dict(self.totals),
            "stopped_reason": self.stopped_reason,
            "unreleased": self.unreleased,
            "by_event_type": _nest(self.by_event_type),
            "by_team": _nest(self.by_team),
            "failures": [
                {"message_id": f.message_id, "event_type": f.event_type, "error": f.error} for f in self.failures
            ],
        }


def _nest(counter: Counter[tuple[Any, ReplayOutcome]]) -> dict[str, dict[str, int]]:
    nested: dict[str, dict[str, int]] = {}
    for (key, outcome), count in sorted(counter.items(), key=lambda item: str(item[0])):
        nested.setdefault("unknown" if key is None else str(key), {})[outcome] = count
    return nested


PostToWebhook = Callable[[str], int]


def post_to_webhook(body: str) -> int:
    if not settings.SES_EVENTS_REPLAY_WEBHOOK_URL:
        raise ReplayNotConfigured("SES_EVENTS_REPLAY_WEBHOOK_URL is not set")
    # The webhook parses a text/plain body, which is the content type SNS itself sends. The URL is
    # cluster-local, and Smokescreen in HTTP_PROXY refuses cluster-local hosts, so skip the proxy.
    response = internal_requests.post(
        settings.SES_EVENTS_REPLAY_WEBHOOK_URL,
        data=body.encode(),
        headers={"Content-Type": "text/plain; charset=UTF-8", "x-amz-sns-message-type": "Notification"},
        timeout=WEBHOOK_TIMEOUT_SECONDS,
    )
    return response.status_code


class _Pacer:
    def __init__(self, max_per_second: float, clock: Callable[[], float], sleep: Callable[[float], None]):
        self._interval = 1 / max_per_second
        self._clock = clock
        self._sleep = sleep
        self._next_at: float | None = None

    def wait(self) -> None:
        now = self._clock()
        if self._next_at is not None and now < self._next_at:
            self._sleep(self._next_at - now)
            now = self._next_at
        self._next_at = now + self._interval


def replay_queue(
    queue: DlqQueue,
    options: ReplayOptions,
    *,
    sqs: "SQSClient",
    triggered_by: str,
    post: PostToWebhook = post_to_webhook,
    on_progress: Callable[[ReplayReport], None] = lambda report: None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> ReplayReport:
    """Post up to `options.limit` dead-lettered notifications to the webhook again.

    A message leaves the queue only after the webhook answers 2xx. Every other message goes back to
    the queue, visible at once, when the run ends.
    """
    if not options.dry_run and not settings.SES_EVENTS_REPLAY_WEBHOOK_URL:
        raise ReplayNotConfigured("SES_EVENTS_REPLAY_WEBHOOK_URL is not set")

    report = ReplayReport(
        queue_name=queue.name, dry_run=options.dry_run, by_event_type=Counter(), by_team=Counter(), failures=[]
    )
    pacer = _Pacer(options.max_per_second, clock, sleep)
    started_at = leases_renewed_at = clock()
    held: dict[str, str] = {}
    logger.info("ses_events_dlq.replay_started", queue=queue.name, triggered_by=triggered_by, options=options)
    try:
        for message in _receive_unseen(queue, options, sqs, held):
            report.stopped_reason = _stop_reason(clock(), started_at, len(held))
            if report.stopped_reason is None and clock() - leases_renewed_at >= HEARTBEAT_SECONDS:
                renewal_started_at = clock()
                if not _renew_leases(queue, sqs, held, leases_renewed_at, clock):
                    report.stopped_reason = "lease_lost"
                leases_renewed_at = renewal_started_at
            if report.stopped_reason is not None:
                logger.warning("ses_events_dlq.replay_stopped", queue=queue.name, reason=report.stopped_reason)
                break
            summary = summarize_message(message)
            outcome, error = _replay_one(message, summary, options, post, pacer)
            report.record(summary, outcome, error)
            if outcome == "replayed":
                sqs.delete_message(QueueUrl=queue.url, ReceiptHandle=message["ReceiptHandle"])
                del held[str(message["MessageId"])]
            on_progress(report)
    finally:
        report.unreleased = _change_visibility(queue, sqs, list(held.values()), 0)
        logger.info(
            "ses_events_dlq.replay_finished", queue=queue.name, triggered_by=triggered_by, report=report.to_dict()
        )
    return report


def _stop_reason(now: float, started_at: float, held_count: int) -> StopReason | None:
    if now - started_at >= MAX_RUN_SECONDS:
        return "run_limit"
    if held_count > MAX_HELD_MESSAGES:
        return "held_limit"
    return None


def _renew_leases(
    queue: DlqQueue, sqs: "SQSClient", held: dict[str, str], renewed_at: float, clock: Callable[[], float]
) -> bool:
    """Extend the lease of every held message. False when a lease may have lapsed, so another consumer can hold it."""
    if clock() - renewed_at >= VISIBILITY_TIMEOUT_SECONDS:
        return False
    refused = _change_visibility(queue, sqs, list(held.values()), VISIBILITY_TIMEOUT_SECONDS)
    return refused == 0 and clock() - renewed_at < VISIBILITY_TIMEOUT_SECONDS


def _receive_unseen(
    queue: DlqQueue, options: ReplayOptions, sqs: "SQSClient", held: dict[str, str]
) -> Iterator[dict[str, Any]]:
    seen: set[str] = set()
    while len(seen) < options.limit:
        messages = sqs.receive_message(
            QueueUrl=queue.url,
            MaxNumberOfMessages=min(RECEIVE_BATCH_SIZE, options.limit - len(seen)),
            VisibilityTimeout=VISIBILITY_TIMEOUT_SECONDS,
            WaitTimeSeconds=1,
            MessageSystemAttributeNames=["SentTimestamp"],
        ).get("Messages", [])
        for received in messages:
            # A message whose lease ran out comes back with a new receipt handle. Only the newest
            # handle can still hide or release it.
            if str(received["MessageId"]) in held:
                held[str(received["MessageId"])] = str(received["ReceiptHandle"])
        unseen = [dict(m) for m in messages if m["MessageId"] not in seen]
        if not unseen:
            return
        for message in unseen:
            seen.add(str(message["MessageId"]))
            held[str(message["MessageId"])] = str(message["ReceiptHandle"])
        yield from unseen


def _replay_one(
    message: dict[str, Any],
    summary: DlqMessageSummary,
    options: ReplayOptions,
    post: PostToWebhook,
    pacer: _Pacer,
) -> tuple[ReplayOutcome, str | None]:
    if not summary.replayable:
        return "unparseable", "body is not a signed SNS notification"
    if options.dry_run:
        return "would_replay", None
    pacer.wait()
    try:
        status = post(message["Body"])
    except requests.RequestException as error:
        return "failed", f"{type(error).__name__}: {error}"
    if 200 <= status < 300:
        return "replayed", None
    return "failed", f"webhook answered {status}"


def _change_visibility(queue: DlqQueue, sqs: "SQSClient", receipt_handles: Sequence[str], timeout: int) -> int:
    """Set the visibility timeout of held messages. Returns how many SQS still refused after the retries."""
    refused = 0
    for start in range(0, len(receipt_handles), RECEIVE_BATCH_SIZE):
        pending = dict(enumerate(receipt_handles[start : start + RECEIVE_BATCH_SIZE]))
        for _ in range(RELEASE_ATTEMPTS):
            try:
                response = sqs.change_message_visibility_batch(
                    QueueUrl=queue.url,
                    Entries=[
                        {"Id": str(index), "ReceiptHandle": handle, "VisibilityTimeout": timeout}
                        for index, handle in pending.items()
                    ],
                )
            except (BotoCoreError, ClientError) as error:
                logger.warning("ses_events_dlq.visibility_change_failed", queue=queue.name, error=str(error))
                continue
            # SQS answers 200 even when single entries fail, and lists those under Failed.
            failed = {int(entry["Id"]) for entry in response.get("Failed", [])}
            pending = {index: handle for index, handle in pending.items() if index in failed}
            if not pending:
                break
        if pending:
            logger.error("ses_events_dlq.visibility_not_changed", queue=queue.name, timeout=timeout, count=len(pending))
        refused += len(pending)
    return refused
