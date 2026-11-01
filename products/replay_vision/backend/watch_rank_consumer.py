"""Ranks observations for the highlight feed from the embedding worker's results topic.

The scan emits each observation's text to the embedding worker over Kafka. The worker publishes every
embedded document to the results topic, and this consumer ranks the Replay Vision ones from their
vectors. A worker outage only delays ranks, and a database outage shorter than the retry window too.
"""

import time
import uuid
import signal
import asyncio
from collections.abc import Sequence
from datetime import datetime
from typing import Any, Literal, Protocol

from django.conf import settings
from django.db import InterfaceError, OperationalError, close_old_connections, connection, transaction
from django.utils import timezone

import orjson
import structlog
from asgiref.sync import sync_to_async
from confluent_kafka import Consumer, KafkaException, Message, TopicPartition
from prometheus_client import Counter, Gauge, Histogram

from posthog.kafka_client import helper
from posthog.kafka_client.client import _build_sasl_config, _KafkaSecurityProtocol
from posthog.kafka_client.routing import get_profile_settings
from posthog.kafka_client.topics import KAFKA_DOCUMENT_EMBEDDING_RESULTS_TOPIC
from posthog.temporal.common.liveness_tracker import LivenessTracker

from products.replay_vision.backend.embeddings import (
    EMBEDDING_DOCUMENT_TYPE,
    EMBEDDING_PRODUCT,
    OBSERVATION_EMBEDDING_MODEL,
)
from products.replay_vision.backend.highlight_feed_groups import feed_group_cache
from products.replay_vision.backend.watch_rank import RankRequest, rank_observation
from products.replay_vision.backend.watch_semantics import SemanticAssignment, assign_semantics
from products.replay_vision.backend.watch_themes import name_theme

logger = structlog.get_logger(__name__)

CONSUMER_GROUP = "replay-vision-watch-rank"

_BATCH_SIZE = 50
_POLL_TIMEOUT_S = 1.0
# A batch stops after this long and goes back to Kafka, so the loop polls well inside the poll interval.
_BATCH_BUDGET_S = 240.0
_MAX_POLL_INTERVAL_S = 360.0
# How long one observation keeps failing, across batches, before the consumer moves past it.
_RETRY_WINDOW_S = 600.0
# Any other error is unlikely to clear by waiting, and every partition waits behind it, so it gives up sooner.
_ERROR_RETRY_WINDOW_S = 60.0
# Long enough for a naming call that waits behind ranking on the shared database thread, short enough that a hung
# model call frees its slot.
_NAMING_TIMEOUT_S = 120.0
_NAMING_DRAIN_S = 20.0
# A due theme left unnamed while this many are in flight is named when its next member arrives.
_MAX_NAMING_TASKS = 8
_RETRY_BACKOFF_S = 2.0
_RETRY_BACKOFF_MAX_S = 60.0

Outcome = Literal["skipped", "ranked", "already_ranked", "missing", "failed", "deferred", "interrupted"]

MESSAGES_TOTAL = Counter(
    "replay_vision_watch_rank_consumer_messages_total",
    "Embedding results the highlight feed rank consumer handled, by outcome. A deferred result counts once per batch it is deferred in.",
    labelnames=["outcome"],
)
BATCH_DURATION = Histogram(
    "replay_vision_watch_rank_consumer_batch_duration_seconds",
    "Time the highlight feed rank consumer spent on one non-empty batch.",
    buckets=(0.1, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 240, 300),
)
THEME_NAMING_TOTAL = Counter(
    "replay_vision_watch_rank_consumer_theme_naming_total",
    "Theme naming outcomes of the highlight feed rank consumer, including names dropped while every slot was busy.",
    labelnames=["outcome"],
)
NAMING_IN_FLIGHT = Gauge(
    "replay_vision_watch_rank_consumer_naming_in_flight",
    "Theme naming calls the highlight feed rank consumer has in flight.",
)

# The worker writes compact JSON, and a quote inside a string value is escaped, so this marks our results.
_DOCUMENT_TYPE_MARKER = f'"document_type":"{EMBEDDING_DOCUMENT_TYPE}"'.encode()


def parse_rank_request(value: bytes | None) -> RankRequest | None:
    """The rank request in one results message, or None when it is not a Replay Vision observation."""
    # Most messages belong to other products, and decoding their content and vectors is the expensive part.
    if value is None or _DOCUMENT_TYPE_MARKER not in value:
        return None
    try:
        payload = orjson.loads(value)
    except orjson.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("product") != EMBEDDING_PRODUCT or payload.get("document_type") != EMBEDDING_DOCUMENT_TYPE:
        return None
    metadata = payload.get("metadata")
    scanner_id = metadata.get("scanner_id") if isinstance(metadata, dict) else None
    vector = next(
        (
            result.get("embedding")
            for result in payload.get("results") or []
            if isinstance(result, dict)
            and result.get("model") == OBSERVATION_EMBEDDING_MODEL.value
            and result.get("outcome") == "success"
        ),
        None,
    )
    team_id = payload.get("team_id")
    observation_id = payload.get("document_id")
    if not isinstance(team_id, int) or not isinstance(scanner_id, str) or not isinstance(observation_id, str):
        return None
    # A zero vector has no direction, so the cosine scores would come out as NaN.
    if not isinstance(vector, list) or not any(vector):
        return None
    return RankRequest(team_id=team_id, scanner_id=scanner_id, observation_id=observation_id, vector=vector)


def _assign_with_timeouts(
    *, team_id: int, scanner_id: str, observation_id: str, vector: list[float], now: datetime
) -> SemanticAssignment | None:
    """Assign under transaction-local timeouts, which survive transaction pooling where a session setting would not."""
    try:
        with transaction.atomic():
            # A slow statement or a long wait on the scanner's lock fails and retries instead of hanging.
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT set_config('lock_timeout', '30s', true), set_config('statement_timeout', '60s', true)"
                )
            return assign_semantics(
                team_id=team_id, scanner_id=scanner_id, observation_id=observation_id, vector=vector, now=now
            )
    except Exception:
        # The commit happens here, outside the assignment's own guard, so a failed one must still drop the cache.
        feed_group_cache.forget(scanner_id)
        raise


class BatchConsumer(Protocol):
    def store_offsets(self, *, message: Message) -> None: ...

    def seek(self, partition: TopicPartition, /) -> None: ...


class WatchRankConsumer:
    def __init__(self, liveness: LivenessTracker) -> None:
        self._liveness = liveness
        self._stop = asyncio.Event()
        # When each observation that is still failing first failed, so its retry window spans batches.
        self._first_failed_at: dict[str, float] = {}
        # Naming calls run beside the loop, so a slow model call never holds up ranking. Kept to stop collection.
        self._naming: set[asyncio.Task[Any]] = set()
        NAMING_IN_FLIGHT.set_function(lambda: len(self._naming))

    async def _wait(self, seconds: float) -> bool:
        """Sleep, unless shutdown comes first. True when the full time passed."""
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=max(seconds, 0))
        except TimeoutError:
            return True
        return False

    async def handle(self, value: bytes | None, batch_deadline: float) -> Outcome:
        """Rank the observation in one message, retrying failures until the batch or retry window ends."""
        request = parse_rank_request(value)
        if request is None:
            return "skipped"
        backoff = _RETRY_BACKOFF_S
        while True:
            # Async ORM calls share one thread, so a connection that broke must be replaced before a retry.
            await sync_to_async(close_old_connections)()
            try:
                outcome = await rank_observation(request)
                if outcome != "missing":
                    await self._semantics(request)
                self._first_failed_at.pop(request.observation_id, None)
                return outcome
            except Exception as error:
                logger.exception(
                    "replay_vision.watch_rank_consumer.rank_failed",
                    team_id=request.team_id,
                    observation_id=request.observation_id,
                )
                # A lock or statement timeout is an OperationalError, so it waits out the database like an outage.
                window = (
                    _RETRY_WINDOW_S if isinstance(error, OperationalError | InterfaceError) else _ERROR_RETRY_WINDOW_S
                )
            self._liveness.record_heartbeat()
            now = time.monotonic()
            give_up_at = self._first_failed_at.setdefault(request.observation_id, now) + window
            if now + backoff > give_up_at:
                # The backfill command can write a rank this gave up on.
                self._first_failed_at.pop(request.observation_id, None)
                return "failed"
            if now + backoff > batch_deadline:
                return "deferred"
            if not await self._wait(backoff):
                return "interrupted"
            backoff = min(backoff * 2, _RETRY_BACKOFF_MAX_S)

    async def _semantics(self, request: RankRequest) -> None:
        """Put a ranked observation in a feed group and a theme, and name the theme in the background once it is due."""
        now = timezone.now()
        assignment = await sync_to_async(_assign_with_timeouts)(
            team_id=request.team_id,
            scanner_id=request.scanner_id,
            observation_id=request.observation_id,
            vector=request.vector,
            now=now,
        )
        if assignment is None or assignment.theme is None or not assignment.theme.name_due:
            return
        if len(self._naming) >= _MAX_NAMING_TASKS:
            THEME_NAMING_TOTAL.labels(outcome="dropped").inc()
            return
        task = asyncio.create_task(self._name(request.team_id, assignment.theme.theme_id, now))
        self._naming.add(task)
        task.add_done_callback(self._naming.discard)

    @staticmethod
    async def _name(team_id: int, theme_id: uuid.UUID, now: datetime) -> None:
        try:
            name = await asyncio.wait_for(name_theme(team_id, theme_id, now), timeout=_NAMING_TIMEOUT_S)
        except TimeoutError:
            THEME_NAMING_TOTAL.labels(outcome="timeout").inc()
            logger.warning("replay_vision.watch_rank_consumer.theme_naming_timed_out", team_id=team_id)
        except Exception:
            THEME_NAMING_TOTAL.labels(outcome="failed").inc()
            # A theme that missed its name is named again when it next doubles.
            logger.exception("replay_vision.watch_rank_consumer.theme_naming_failed", team_id=team_id)
        else:
            THEME_NAMING_TOTAL.labels(outcome="named" if name else "unnamed").inc()

    async def process_batch(self, consumer: BatchConsumer, messages: Sequence[Message]) -> None:
        batch_deadline = time.monotonic() + _BATCH_BUDGET_S
        for index, message in enumerate(messages):
            if self._stop.is_set():
                return
            if message.error():
                logger.warning("replay_vision.watch_rank_consumer.kafka_error", error=str(message.error()))
                continue
            outcome = await self.handle(message.value(), batch_deadline)
            self._liveness.record_heartbeat()
            MESSAGES_TOTAL.labels(outcome=outcome).inc()
            if outcome == "interrupted":
                return
            if outcome == "deferred":
                self._rewind(consumer, messages[index:])
                return
            try:
                consumer.store_offsets(message=message)
            except KafkaException:
                logger.warning("replay_vision.watch_rank_consumer.offset_store_failed", partition=message.partition())
                self._rewind(consumer, messages[index + 1 :])
                return

    @staticmethod
    def _rewind(consumer: BatchConsumer, unhandled: Sequence[Message]) -> None:
        """Seek each partition back to its first unhandled message, so the next poll reads it again."""
        first: dict[tuple[str, int], int] = {}
        for message in unhandled:
            topic, partition = message.topic(), message.partition()
            if topic is not None and partition is not None:
                first.setdefault((topic, partition), message.offset() or 0)
        for (topic, partition), offset in first.items():
            try:
                consumer.seek(TopicPartition(topic, partition, offset))
            except KafkaException:
                # A rebalance took the partition, and its new owner starts from the last committed offset.
                continue

    @staticmethod
    def _consumer_config() -> dict[str, Any]:
        profile = get_profile_settings(topic=KAFKA_DOCUMENT_EMBEDDING_RESULTS_TOPIC)
        security_protocol = profile.security_protocol
        # Self-hosted base64 cert mode supplies its own SSL material, so SASL credentials must not attach.
        if settings.KAFKA_BASE64_KEYS:
            security_protocol = _KafkaSecurityProtocol.SSL
        config: dict[str, Any] = {
            "bootstrap.servers": ",".join(profile.hosts),
            "group.id": CONSUMER_GROUP,
            # Ranking skips rows that already have a current rank, so reading old results again is harmless.
            "auto.offset.reset": "earliest",
            # Offsets are stored only after a message is handled, and committed in the background.
            "enable.auto.commit": True,
            "enable.auto.offset.store": False,
            "max.poll.interval.ms": int(_MAX_POLL_INTERVAL_S * 1000),
            # The worker writes results inside Kafka transactions, and an aborted one must never rank.
            "isolation.level": "read_committed",
            "security.protocol": security_protocol or _KafkaSecurityProtocol.PLAINTEXT,
        }
        config.update(
            _build_sasl_config(security_protocol, profile.sasl_mechanism, profile.sasl_user, profile.sasl_password)
        )
        if settings.KAFKA_BASE64_KEYS:
            config.update(helper.ssl_cert_config())
        return config

    async def run(self) -> None:  # pragma: no cover - exercised in dogfood
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._stop.set)

        consumer = Consumer(self._consumer_config())
        consumer.subscribe([KAFKA_DOCUMENT_EMBEDDING_RESULTS_TOPIC])
        logger.info("replay_vision.watch_rank_consumer.started")
        try:
            while not self._stop.is_set():
                self._liveness.record_heartbeat()
                messages = await asyncio.to_thread(consumer.consume, _BATCH_SIZE, _POLL_TIMEOUT_S)
                if not messages:
                    continue
                with BATCH_DURATION.time():
                    await self.process_batch(consumer, messages)
        finally:
            consumer.close()
            # A theme claimed for naming stays unnamed until it doubles, so in-flight names get a moment to finish.
            if self._naming:
                await asyncio.wait(self._naming, timeout=_NAMING_DRAIN_S)
            logger.info("replay_vision.watch_rank_consumer.stopped")
