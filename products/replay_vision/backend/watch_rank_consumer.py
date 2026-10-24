"""Ranks observations for What to watch from the embedding worker's results topic.

The scan emits each observation's text to the embedding worker over Kafka. The worker publishes every
embedded document to the results topic, in the same transaction as the ClickHouse write, and this
consumer ranks the Replay Vision ones from their vectors. A worker outage delays ranks, and loses none.
"""

import json
import signal
import asyncio
from typing import Any

from django.conf import settings
from django.db import close_old_connections

import structlog
from asgiref.sync import sync_to_async
from prometheus_client import Counter

from posthog.dataclasses import frozen
from posthog.kafka_client import helper
from posthog.kafka_client.client import _KafkaSecurityProtocol
from posthog.kafka_client.routing import get_profile_settings
from posthog.kafka_client.topics import KAFKA_DOCUMENT_EMBEDDING_RESULTS_TOPIC
from posthog.temporal.common.liveness_tracker import LivenessTracker

from products.replay_vision.backend.embeddings import (
    EMBEDDING_DOCUMENT_TYPE,
    EMBEDDING_PRODUCT,
    OBSERVATION_EMBEDDING_MODEL,
)
from products.replay_vision.backend.watch_rank import rank_observation

logger = structlog.get_logger(__name__)

CONSUMER_GROUP = "replay-vision-watch-rank"

_BATCH_SIZE = 500
_POLL_TIMEOUT_S = 1.0
_RANK_ATTEMPTS = 3
_RETRY_BACKOFF_S = 2.0

MESSAGES_TOTAL = Counter(
    "replay_vision_watch_rank_consumer_messages_total",
    "Embedding results the What to watch rank consumer read, by outcome.",
    labelnames=["outcome"],
)


@frozen
class RankRequest:
    team_id: int
    scanner_id: str
    observation_id: str
    vector: list[float]


def parse_rank_request(value: bytes) -> RankRequest | None:
    """The rank request in one results message, or None when it is not a Replay Vision observation."""
    try:
        payload = json.loads(value)
    except (ValueError, TypeError):
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
    if not isinstance(vector, list) or not vector:
        return None
    return RankRequest(team_id=team_id, scanner_id=scanner_id, observation_id=observation_id, vector=vector)


class WatchRankConsumer:
    def __init__(self, liveness: LivenessTracker) -> None:
        self._liveness = liveness
        self._stop = asyncio.Event()

    async def handle(self, value: bytes | None) -> str:
        """Rank the observation in one message, retrying transient failures a few times."""
        request = parse_rank_request(value) if value is not None else None
        if request is None:
            return "skipped"
        for attempt in range(1, _RANK_ATTEMPTS + 1):
            try:
                await rank_observation(
                    team_id=request.team_id,
                    scanner_id=request.scanner_id,
                    observation_id=request.observation_id,
                    vector=request.vector,
                )
                return "ranked"
            except Exception:
                logger.exception(
                    "replay_vision.watch_rank_consumer.rank_failed",
                    team_id=request.team_id,
                    observation_id=request.observation_id,
                    attempt=attempt,
                )
                self._liveness.record_heartbeat()
                if attempt < _RANK_ATTEMPTS:
                    await asyncio.sleep(_RETRY_BACKOFF_S * attempt)
        # A missing rank only drops the observation from picks, and the backfill command can write it later.
        return "failed"

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
            "auto.offset.reset": "latest",
            # Offsets are stored only after a message is handled, and committed in the background.
            "enable.auto.commit": True,
            "enable.auto.offset.store": False,
            "security.protocol": security_protocol or _KafkaSecurityProtocol.PLAINTEXT,
        }
        if security_protocol in (_KafkaSecurityProtocol.SASL_PLAINTEXT, _KafkaSecurityProtocol.SASL_SSL):
            config["sasl.mechanism"] = profile.sasl_mechanism
            config["sasl.username"] = profile.sasl_user
            config["sasl.password"] = profile.sasl_password
        if settings.KAFKA_BASE64_KEYS:
            config.update(helper.ssl_cert_config())
        return config

    async def run(self) -> None:  # pragma: no cover - exercised in dogfood
        from confluent_kafka import Consumer  # noqa: PLC0415 — keeps the Kafka client off the import path

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
                # Async ORM calls share one thread, so its connection must be refreshed like a request's.
                await sync_to_async(close_old_connections)()
                for message in messages:
                    # The unhandled rest of the batch keeps no stored offset, so the next start reads it again.
                    if self._stop.is_set():
                        break
                    if message.error():
                        logger.warning("replay_vision.watch_rank_consumer.kafka_error", error=str(message.error()))
                        continue
                    MESSAGES_TOTAL.labels(outcome=await self.handle(message.value())).inc()
                    consumer.store_offsets(message=message)
        finally:
            consumer.close()
            logger.info("replay_vision.watch_rank_consumer.stopped")
