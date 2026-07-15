"""Throttling consumer for warehouse -> person-property $set intents.

Drains ``KAFKA_WAREHOUSE_PERSON_PROPERTY_UPDATES`` and sends each as a ``$set`` through
capture-internal, at a global rate (a constance setting ops can retune live). The rate is enforced
by the shared, Redis-backed outbound egress limiter, so the budget holds across every replica at
once — the consumer can run many pods without multiplying the send rate. Kafka lag is the
backpressure: when the budget is spent the send blocks (the message stays on the topic) until a
slot frees. Offsets commit only after a successful send; permanently-rejected (poison) messages go
to a DLQ so they can't wedge a partition.

The rate gate and the message->capture mapping are the tested seams; the Kafka loop, the capture
call, and the distributed limiter are the boundaries.
"""

import json
import time
import signal
from collections.abc import Callable
from typing import Any

from django.conf import settings

import structlog
from prometheus_client import Counter

from posthog.egress.limiter.outbound import OutboundRateLimiter
from posthog.egress.limiter.policies import RatePolicy, register_policy
from posthog.kafka_client import helper
from posthog.kafka_client.client import _KafkaSecurityProtocol
from posthog.kafka_client.routing import get_producer, get_profile_settings
from posthog.kafka_client.topics import (
    KAFKA_WAREHOUSE_PERSON_PROPERTY_UPDATES,
    KAFKA_WAREHOUSE_PERSON_PROPERTY_UPDATES_DLQ,
)
from posthog.models.instance_setting import get_instance_setting
from posthog.settings import CONSTANCE_CONFIG

logger = structlog.get_logger(__name__)

CONSUMER_GROUP = "warehouse-person-property-updates"
_RATE_SETTING = "WAREHOUSE_PERSON_PROPERTY_SET_RATE_PER_SEC"
EVENT_SOURCE = "customer_analytics_person_property_sync"

# The shared limiter budget is keyed by domain; ``:global`` is the single scope we throttle on, so
# every replica draws from one per-second bucket in Redis.
_RATE_DOMAIN = "warehouse_person_property"
_RATE_KEY = f"{_RATE_DOMAIN}:global"
# Divides the per-process fallback budget when Redis is unreachable. Matched to the consumer's max
# replica count so the sum across pods still ~equals the global rate during a Redis outage (fewer
# pods just run slower, never faster). Keep in sync with charts ``autoscaling.maxPods``.
_IN_MEMORY_DIVIDER = 6

SENT_TOTAL = Counter("warehouse_person_property_sent_total", "person-property $set events sent to capture")
DLQ_TOTAL = Counter("warehouse_person_property_dlq_total", "person-property update messages routed to DLQ")
DLQ_FAILED_TOTAL = Counter(
    "warehouse_person_property_dlq_failed_total", "person-property DLQ writes that failed to deliver"
)
RETRY_TOTAL = Counter("warehouse_person_property_retry_total", "person-property update messages left for redelivery")
THROTTLED_TOTAL = Counter(
    "warehouse_person_property_throttled_total", "person-property sends that had to wait on the rate limiter"
)

# Fall back to the configured default (and never below this floor) when the live rate setting is
# unreadable, so a fat-fingered constance value can't crash-loop every replica at once.
_DEFAULT_RATE_PER_SEC = float(CONSTANCE_CONFIG[_RATE_SETTING][0])
_MIN_RATE_PER_SEC = 1.0

# 4xx statuses that are transient despite being client errors: request timeout and rate limiting
# (capture returns 408 with Retry-After for timeouts, 429 when throttled). These must retry, not DLQ.
_RETRYABLE_CLIENT_STATUSES = frozenset({408, 429})

# How long to wait for a DLQ produce to be acknowledged before treating it as failed.
_DLQ_DELIVERY_TIMEOUT_SECONDS = 30.0

# Pause between in-place retries of a transiently-failing message (capture down / timeout).
_RETRY_BACKOFF_SECONDS = 1.0

# Pause between polls of the shared budget while a send is throttled. Small so the send fires
# promptly once a slot frees; Kafka lag, not this sleep, is the real buffer.
_THROTTLE_BACKOFF_SECONDS = 0.05


class InvalidPersonPropertyMessage(Exception):
    """A message that can never succeed (bad shape) -> DLQ, not retry."""


def _current_rate() -> float:
    """Live global send rate. A non-numeric or empty setting (saved via admin/constance) must not
    take the fleet down: fall back to the default and clamp to a floor rather than letting a
    ValueError propagate through the rate policy into the consume loop and crash-loop every pod."""
    raw = get_instance_setting(_RATE_SETTING)
    try:
        rate = float(raw)
    except (TypeError, ValueError):
        logger.warning("person_property_update.invalid_rate_setting", raw_value=raw)
        rate = _DEFAULT_RATE_PER_SEC
    return max(_MIN_RATE_PER_SEC, rate)


def _rate_policy(_key: str) -> RatePolicy:
    """Resolve the live global budget. Registered as a provider so a constance change to the rate
    takes effect without a restart (read on each acquire, not frozen at import)."""
    return RatePolicy(limits=((max(1, int(_current_rate())), 1.0),), in_memory_divider=_IN_MEMORY_DIVIDER)


register_policy(_RATE_DOMAIN, _rate_policy)


def build_capture_kwargs(payload: dict[str, Any]) -> dict[str, Any]:
    """Map a topic message to capture_internal kwargs. Raises InvalidPersonPropertyMessage for a
    shape that can never succeed (missing token/distinct_id, or no properties)."""
    token = payload.get("token")
    distinct_id = payload.get("distinct_id")
    properties = payload.get("properties")
    if not token or not distinct_id:
        raise InvalidPersonPropertyMessage("message missing token or distinct_id")
    if not isinstance(properties, dict) or not properties:
        raise InvalidPersonPropertyMessage("message has no properties to set")
    # Non-finite floats (NaN/Infinity) survive json.loads but serialize to non-compliant JSON that
    # the capture transport rejects as an unaccounted (non-terminal) failure, which would otherwise
    # retry forever and wedge the partition. They can never succeed, so treat them as poison -> DLQ.
    try:
        json.dumps(properties, allow_nan=False)
    except ValueError as exc:
        raise InvalidPersonPropertyMessage("message has non-finite property values") from exc
    return {
        "token": token,
        "event_name": "$set",
        "event_source": payload.get("event_source") or EVENT_SOURCE,
        "distinct_id": str(distinct_id),
        "properties": {"$set": properties},
        "process_person_profile": True,
    }


# Outcomes of handling one message. "sent" and "dlq" are terminal (commit the offset); "retry"
# leaves the offset uncommitted so the message is redelivered.
SENT = "sent"
DLQ = "dlq"
RETRY = "retry"


def _is_permanent_client_error(status_code: object) -> bool:
    """True for a 4xx that can never succeed on retry (bad/stale token, validation) -> DLQ. The
    retryable 4xx (408 timeout, 429 throttled) are excluded so a client hammering capture into
    timeouts can't get queued updates dropped instead of retried."""
    return isinstance(status_code, int) and 400 <= status_code < 500 and status_code not in _RETRYABLE_CLIENT_STATUSES


class PersonPropertyUpdateConsumer:
    def __init__(
        self,
        *,
        capture_fn: Callable[..., Any] | None = None,
        grant_fn: Callable[[], bool] | None = None,
        dlq_producer: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        # Lazy default import so tests can inject without importing the capture stack.
        if capture_fn is None:
            from posthog.api.capture import capture_internal  # noqa: PLC0415

            capture_fn = capture_internal
        self._capture = capture_fn
        # The distributed limiter's non-blocking check: True if this send fits the shared budget.
        # Built per process (lazy Redis backend), reused for every message.
        if grant_fn is None:
            limiter = OutboundRateLimiter()
            grant_fn = lambda: limiter.consume_sync(_RATE_KEY, source=EVENT_SOURCE)  # noqa: E731
        self._grant = grant_fn
        self._dlq_producer = dlq_producer
        self._sleep = sleep
        self._shutdown = False
        # Set by run() from the health server; called on every loop turn and during any wait
        # (throttle / retry) so a pod stuck waiting still passes its liveness probe. No-op by default.
        self._health_reporter: Callable[[], None] = lambda: None

    def _get_dlq_producer(self) -> Any:
        # Reuse the routed, process-wide singleton producer for the DLQ topic rather than
        # constructing one per message (Kafka producers are heavyweight). Resolved lazily so a
        # consumer that never hits a poison message never opens a producer, and tests inject their
        # own without touching the Kafka stack.
        if self._dlq_producer is None:
            self._dlq_producer = get_producer(topic=KAFKA_WAREHOUSE_PERSON_PROPERTY_UPDATES_DLQ)
        return self._dlq_producer

    def _dlq(self, value: bytes, reason: str) -> str:
        """Route a poison message to the DLQ. Returns ``DLQ`` only once the write is confirmed
        delivered; a failed DLQ write returns ``RETRY`` so the source offset stays uncommitted and
        the message is redelivered rather than silently dropped from both topics."""
        logger.warning("person_property_update.dlq", reason=reason)
        producer = self._get_dlq_producer()
        result = producer.produce(
            topic=KAFKA_WAREHOUSE_PERSON_PROPERTY_UPDATES_DLQ,
            data={"raw": value.decode("utf-8", "replace"), "reason": reason},
        )
        # Bound the flush: an unavailable DLQ broker must not block past the liveness timeout and get
        # the pod killed mid-write. Heartbeat either side so a slow-but-progressing write stays live.
        self._health_reporter()
        producer.flush(timeout=_DLQ_DELIVERY_TIMEOUT_SECONDS)
        self._health_reporter()
        try:
            result.get(timeout=_DLQ_DELIVERY_TIMEOUT_SECONDS)
        except Exception:
            DLQ_FAILED_TOTAL.inc()
            logger.exception("person_property_update.dlq_delivery_failed", reason=reason)
            return RETRY
        DLQ_TOTAL.inc()
        return DLQ

    def _acquire_slot(self) -> bool:
        """Block until the shared per-second budget admits this send, or shutdown is requested.
        Returns True if a slot was granted; False if interrupted by shutdown (caller must leave the
        message uncommitted). The budget lives in Redis, so the limit holds across every replica at
        once — this is what lets the consumer scale out without multiplying the send rate."""
        throttled = False
        while not self._shutdown:
            try:
                granted = self._grant()
            except Exception:
                # The limiter degrades a Redis outage to its in-memory fallback internally; anything
                # that still escapes here is unexpected. Treat it like a transient failure — back off
                # and retry the acquire rather than letting it escape and crash-loop the pod. The
                # message stays uncommitted meanwhile, so nothing is sent or dropped.
                logger.exception("person_property_update.grant_error")
                self._health_reporter()
                self._sleep(_RETRY_BACKOFF_SECONDS)
                continue
            if granted:
                return True
            if not throttled:
                # Count the message once (not each poll) so the metric reads as "messages that were
                # throttled", not raw spin iterations.
                THROTTLED_TOTAL.inc()
                throttled = True
            self._health_reporter()
            self._sleep(_THROTTLE_BACKOFF_SECONDS)
        return False

    def process_record(self, value: bytes) -> str:
        """Handle one message. Terminal outcomes (sent/dlq) commit; retry does not."""
        try:
            payload = json.loads(value)
        except (ValueError, TypeError):
            return self._dlq(value, "invalid_json")
        # Valid JSON that isn't an object (``[]``, ``"foo"``, ``null``) parses fine but can never map
        # to a $set; DLQ it instead of letting build_capture_kwargs crash and wedge the partition.
        if not isinstance(payload, dict):
            return self._dlq(value, "payload_not_object")
        try:
            kwargs = build_capture_kwargs(payload)
        except InvalidPersonPropertyMessage as exc:
            return self._dlq(value, str(exc))

        # Pace the send against the shared budget. Blocks until a slot frees (Kafka lag absorbs the
        # wait) or shutdown is requested; on shutdown mid-wait we leave the message uncommitted for
        # redelivery rather than sending or dropping it.
        if not self._acquire_slot():
            return RETRY
        try:
            result = self._capture(**kwargs)
        except Exception as exc:
            # A permanent client-side/4xx rejection (bad/stale token, validation) can never succeed on
            # retry, so DLQ it rather than retrying forever and wedging the partition. capture surfaces
            # most permanent rejections as a returned result (handled below); this covers the case
            # where it raises one instead — decoupling us from capture's exact validation set. status
            # 0 (transport/client-side), retryable 4xx (408/429), and 5xx stay transient -> uncommitted.
            status_code = getattr(exc, "status_code", None)
            if _is_permanent_client_error(status_code):
                return self._dlq(value, f"capture_client_error:{status_code}")
            RETRY_TOTAL.inc()
            logger.exception("person_property_update.capture_error")
            return RETRY
        if result.succeeded():
            SENT_TOTAL.inc()
            return SENT
        # A drop is terminal: capture rejected the event permanently (e.g. invalid/stale token,
        # validation failure), so it's poison. DLQ it rather than redelivering forever.
        if result.dropped:
            return self._dlq(value, "capture_dropped")
        # A permanent whole-request 4xx is likewise poison (bad/stale token, validation), so DLQ it
        # too. Everything else (exhausted retries, unaccounted, retryable 4xx, 5xx, transport) is
        # transient -> retry.
        if result.error and _is_permanent_client_error(result.status_code):
            return self._dlq(value, f"capture_error:{result.status_code}")
        RETRY_TOTAL.inc()
        return RETRY

    def _process_with_retries(self, value: bytes) -> str:
        """Process one message, retrying transient failures in place. A ``RETRY`` must never
        advance past the message: Kafka offset commits are a high-water mark, so committing a
        later message's offset would silently skip this one. We re-send the same message (Kafka
        lag is the backpressure) until it's terminal, or return ``RETRY`` if shutdown is requested
        mid-retry so the uncommitted offset is redelivered on the next start."""
        outcome = self.process_record(value)
        while outcome == RETRY and not self._shutdown:
            self._health_reporter()
            self._sleep(_RETRY_BACKOFF_SECONDS)
            outcome = self.process_record(value)
        return outcome

    @staticmethod
    def _build_consumer_config() -> dict[str, str | int | float | bool | None]:
        # Resolve hosts + TLS/SASL through the router so the input topic's cluster profile (and any
        # KAFKA_TOPIC_ROUTING_OVERRIDES) applies — never a bare plaintext KAFKA_HOSTS connection.
        profile = get_profile_settings(topic=KAFKA_WAREHOUSE_PERSON_PROPERTY_UPDATES)
        security_protocol = profile.security_protocol
        # Self-hosted base64 cert mode provides its own SSL material; force the protocol to SSL
        # before SASL resolution so SASL creds aren't attached (mirrors _KafkaProducer).
        if settings.KAFKA_BASE64_KEYS:
            security_protocol = _KafkaSecurityProtocol.SSL
        config: dict[str, str | int | float | bool | None] = {
            "bootstrap.servers": ",".join(profile.hosts),
            "group.id": CONSUMER_GROUP,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
            "security.protocol": security_protocol or _KafkaSecurityProtocol.PLAINTEXT,
        }
        if security_protocol in (_KafkaSecurityProtocol.SASL_PLAINTEXT, _KafkaSecurityProtocol.SASL_SSL):
            config["sasl.mechanism"] = profile.sasl_mechanism
            config["sasl.username"] = profile.sasl_user
            config["sasl.password"] = profile.sasl_password
        if settings.KAFKA_BASE64_KEYS:
            # Writes cert/key/CA files on first call; returns the ssl.* paths plus security.protocol=SSL.
            config.update(helper.ssl_cert_config())
        return config

    def run(
        self, poll_timeout: float = 1.0, health_reporter: Callable[[], None] | None = None
    ) -> None:  # pragma: no cover - exercised in dogfood
        from confluent_kafka import Consumer as ConfluentConsumer  # noqa: PLC0415

        # Report liveness each loop turn (and, via self._health_reporter, during throttle/retry
        # waits) so a wedged loop fails its liveness probe. No-op when no health server is wired.
        if health_reporter is not None:
            self._health_reporter = health_reporter

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, lambda *_: setattr(self, "_shutdown", True))
            except ValueError:
                pass

        consumer = ConfluentConsumer(self._build_consumer_config())
        consumer.subscribe([KAFKA_WAREHOUSE_PERSON_PROPERTY_UPDATES])
        logger.info("person_property_update.consumer_started")
        try:
            while not self._shutdown:
                self._health_reporter()
                message = consumer.poll(poll_timeout)
                if message is None:
                    continue
                if message.error():
                    logger.warning("person_property_update.kafka_error", error=str(message.error()))
                    continue
                value = message.value()
                if value is None:
                    # Tombstone / empty payload: nothing to $set. Commit past it so it doesn't replay.
                    consumer.commit(message=message, asynchronous=False)
                    continue
                outcome = self._process_with_retries(value)
                if outcome in (SENT, DLQ):
                    consumer.commit(message=message, asynchronous=False)
        finally:
            consumer.close()
            logger.info("person_property_update.consumer_stopped")
