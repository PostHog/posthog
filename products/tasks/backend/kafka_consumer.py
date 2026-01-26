import asyncio
import json
import ssl
import uuid
from collections import defaultdict
from collections.abc import AsyncGenerator
from typing import Any

import aiokafka
import structlog
from django.conf import settings

from posthog.kafka_client.topics import KAFKA_AGENT_EVENTS

logger = structlog.get_logger(__name__)


def _get_ssl_context() -> ssl.SSLContext | None:
    if settings.KAFKA_SECURITY_PROTOCOL in ("SSL", "SASL_SSL"):
        ssl_context = ssl.create_default_context()
        if settings.KAFKA_CERT_FILE:
            ssl_context.load_cert_chain(
                certfile=settings.KAFKA_CERT_FILE,
                keyfile=settings.KAFKA_KEY_FILE,
            )
        if settings.KAFKA_TRUSTED_CERT_FILE:
            ssl_context.load_verify_locations(cafile=settings.KAFKA_TRUSTED_CERT_FILE)
        return ssl_context
    return None


class AgentEventBroker:
    """
    Singleton broker that consumes from Kafka and fans out to SSE connections.

    One consumer per pod reads all messages, routes to local subscriptions.
    """

    _instance: "AgentEventBroker | None" = None
    _lock = asyncio.Lock()

    def __init__(self):
        self._subscriptions: dict[str, list[asyncio.Queue]] = defaultdict(list)
        self._consumer: aiokafka.AIOKafkaConsumer | None = None
        self._consumer_task: asyncio.Task | None = None
        self._started = False
        self._pod_id = uuid.uuid4().hex[:8]

    @classmethod
    async def get_instance(cls) -> "AgentEventBroker":
        async with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            if not cls._instance._started:
                await cls._instance._start()
            return cls._instance

    async def _start(self):
        if self._started:
            return

        ssl_context = _get_ssl_context()
        consumer_group = f"agent-events-sse-{self._pod_id}"

        self._consumer = aiokafka.AIOKafkaConsumer(
            KAFKA_AGENT_EVENTS,
            bootstrap_servers=settings.KAFKA_HOSTS,
            security_protocol=settings.KAFKA_SECURITY_PROTOCOL or "PLAINTEXT",
            ssl_context=ssl_context,
            group_id=consumer_group,
            auto_offset_reset="latest",
            enable_auto_commit=True,
        )

        await self._consumer.start()
        self._started = True
        self._consumer_task = asyncio.create_task(self._consume_loop())

        logger.info(
            "agent_event_broker_started",
            pod_id=self._pod_id,
            consumer_group=consumer_group,
        )

    async def _consume_loop(self):
        try:
            async for msg in self._consumer:
                try:
                    key = msg.key.decode("utf-8") if msg.key else None
                    if not key:
                        continue

                    # Key format: {task_id}:{run_id}
                    parts = key.split(":", 1)
                    if len(parts) != 2:
                        continue

                    run_id = parts[1]

                    # Get subscriptions for this run
                    queues = self._subscriptions.get(run_id, [])
                    if not queues:
                        continue

                    # Parse message
                    value = json.loads(msg.value.decode("utf-8"))

                    # Fan out to all subscriptions for this run
                    for queue in queues:
                        try:
                            queue.put_nowait(value)
                        except asyncio.QueueFull:
                            logger.warning(
                                "agent_event_queue_full",
                                run_id=run_id,
                            )

                except Exception as e:
                    logger.exception("agent_event_broker_message_error", error=str(e))

        except asyncio.CancelledError:
            logger.info("agent_event_broker_consumer_cancelled")
        except Exception as e:
            logger.exception("agent_event_broker_consumer_error", error=str(e))

    def subscribe(self, run_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subscriptions[run_id].append(queue)
        logger.info("agent_event_subscription_added", run_id=run_id)
        return queue

    def unsubscribe(self, run_id: str, queue: asyncio.Queue):
        if run_id in self._subscriptions:
            try:
                self._subscriptions[run_id].remove(queue)
                if not self._subscriptions[run_id]:
                    del self._subscriptions[run_id]
                logger.info("agent_event_subscription_removed", run_id=run_id)
            except ValueError:
                pass

    async def stop(self):
        if self._consumer_task:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass

        if self._consumer:
            await self._consumer.stop()

        self._started = False
        logger.info("agent_event_broker_stopped")


async def consume_agent_events(
    task_id: str,
    run_id: str,
    from_sequence: int | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """
    Subscribe to agent events for a specific run.

    Uses the singleton broker for efficient fan-out.
    """
    broker = await AgentEventBroker.get_instance()
    queue = broker.subscribe(run_id)

    try:
        while True:
            try:
                value = await asyncio.wait_for(queue.get(), timeout=30.0)

                sequence = value.get("sequence", 0)
                if from_sequence is not None and sequence <= from_sequence:
                    continue

                entry = value.get("entry")
                if entry:
                    if isinstance(entry, str):
                        entry = json.loads(entry)
                    yield entry

            except asyncio.TimeoutError:
                # Send keepalive comment
                yield {"_keepalive": True}
            except asyncio.CancelledError:
                break

    finally:
        broker.unsubscribe(run_id, queue)
