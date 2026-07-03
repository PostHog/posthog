import json
import signal
import asyncio
from collections.abc import Callable, Mapping
from enum import StrEnum
from typing import TypeVar

from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser

import structlog
from confluent_kafka import (
    Consumer as ConfluentConsumer,
    KafkaError,
    KafkaException,
    Message,
)
from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.kafka_client.client import _KafkaSecurityProtocol
from posthog.kafka_client.routing import get_profile_settings, resolve_profile_name
from posthog.kafka_client.topics import KAFKA_DOCUMENT_EMBEDDING_RESULTS_TOPIC
from posthog.temporal.common.client import async_connect

from products.error_tracking.backend.temporal.fingerprint_embedding_result.types import (
    FingerprintEmbeddingResultInputs,
    select_model_name,
)
from products.error_tracking.backend.temporal.fingerprint_embedding_result.workflow import (
    ErrorTrackingFingerprintEmbeddingResultWorkflow,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.health import (
    HealthState,
    start_health_server,
)

logger = structlog.get_logger(__name__)

DEFAULT_CONSUMER_GROUP = "error-tracking-fingerprint-embedding-results"
T = TypeVar("T")

# Commit failures caused by a group rebalance: the partition was reassigned, so the
# message will be redelivered to its new owner. Workflow starts are deduplicated by
# workflow id, so redelivery is safe and these must not crash the consumer.
_REBALANCE_COMMIT_ERROR_CODES = (
    KafkaError.ILLEGAL_GENERATION,  # type: ignore[attr-defined]
    KafkaError.UNKNOWN_MEMBER_ID,  # type: ignore[attr-defined]
    KafkaError.REBALANCE_IN_PROGRESS,  # type: ignore[attr-defined]
)


async def _run_blocking_call(callback: Callable[[], T]) -> T:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, callback)


async def _commit_message(consumer: ConfluentConsumer, message: Message) -> None:
    try:
        await _run_blocking_call(lambda: consumer.commit(message=message, asynchronous=False))
    except KafkaException as err:
        error = err.args[0] if err.args and isinstance(err.args[0], KafkaError) else None
        if error is None or error.code() not in _REBALANCE_COMMIT_ERROR_CODES:
            raise
        logger.warning(
            "error_tracking.embedding_results_consumer.commit_failed_rebalance",
            error=str(error),
        )


class FingerprintEmbeddingResultOutcome(StrEnum):
    STARTED = "started"
    SKIPPED = "skipped"
    ALREADY_STARTED = "already_started"


def _string_value(data: Mapping[str, object], key: str) -> str | None:
    value = data.get(key)
    if isinstance(value, str) and value:
        return value
    return None


def _float_option(options: Mapping[str, object], key: str) -> float:
    value = options[key]
    if isinstance(value, str | int | float):
        return float(value)
    raise TypeError(f"{key} must be a number")


def _int_option(options: Mapping[str, object], key: str) -> int:
    value = options[key]
    if isinstance(value, str | int):
        return int(value)
    raise TypeError(f"{key} must be an integer")


def _success_model_names(results: object) -> list[str]:
    if not isinstance(results, list):
        return []

    model_names: list[str] = []
    for result in results:
        if not isinstance(result, dict):
            continue
        if result.get("outcome") != "success":
            continue
        model = result.get("model")
        if isinstance(model, str):
            model_names.append(model)
    return model_names


def _float_list(value: object) -> list[float] | None:
    if not isinstance(value, list) or not value:
        return None
    try:
        return [float(item) for item in value]
    except (TypeError, ValueError):
        return None


def _success_embedding(results: object, model_name: str) -> list[float] | None:
    if not isinstance(results, list):
        return None

    for result in results:
        if not isinstance(result, dict) or result.get("outcome") != "success":
            continue
        model = result.get("model")
        if model == model_name:
            return _float_list(result.get("embedding"))
    return None


def fingerprint_embedding_result_inputs_from_message(value: bytes) -> FingerprintEmbeddingResultInputs | None:
    loaded_data = json.loads(value)
    if not isinstance(loaded_data, dict):
        return None
    data: Mapping[str, object] = loaded_data
    if data.get("product") != "error_tracking" or data.get("document_type") != "fingerprint":
        return None

    team_id = data.get("team_id")
    fingerprint = _string_value(data, "document_id")
    rendering = _string_value(data, "rendering")
    timestamp = _string_value(data, "timestamp")
    results = data.get("results")
    model_names = _success_model_names(results)
    model_name = select_model_name(model_names)
    embedding = _success_embedding(results, model_name)

    invalid_fields: list[str] = []
    if not isinstance(team_id, int):
        invalid_fields.append("team_id")
    if fingerprint is None:
        invalid_fields.append("document_id")
    if rendering is None:
        invalid_fields.append("rendering")
    if timestamp is None:
        invalid_fields.append("timestamp")
    if not model_names:
        invalid_fields.append("results")
    if invalid_fields:
        raise ValueError(f"Invalid error tracking fingerprint embedding result message: {', '.join(invalid_fields)}")

    if not isinstance(team_id, int) or fingerprint is None or rendering is None or timestamp is None:
        raise AssertionError("validated embedding result fields were unexpectedly invalid")

    return FingerprintEmbeddingResultInputs(
        team_id=team_id,
        fingerprint=fingerprint,
        rendering=rendering,
        timestamp=timestamp,
        model_name=model_name,
        model_names=model_names,
        embedding=embedding,
    )


async def start_fingerprint_embedding_result_workflow(
    client: Client,
    inputs: FingerprintEmbeddingResultInputs,
) -> FingerprintEmbeddingResultOutcome:
    workflow_id = ErrorTrackingFingerprintEmbeddingResultWorkflow.workflow_id_for(
        team_id=inputs.team_id,
        fingerprint=inputs.fingerprint,
        rendering=inputs.rendering,
        timestamp=inputs.timestamp,
    )

    try:
        await client.start_workflow(
            ErrorTrackingFingerprintEmbeddingResultWorkflow.run,
            inputs,
            id=workflow_id,
            task_queue=settings.ERROR_TRACKING_TASK_QUEUE,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
        )
    except WorkflowAlreadyStartedError:
        return FingerprintEmbeddingResultOutcome.ALREADY_STARTED

    return FingerprintEmbeddingResultOutcome.STARTED


async def handle_embedding_result_message(
    client: Client,
    value: bytes,
) -> FingerprintEmbeddingResultOutcome:
    inputs = fingerprint_embedding_result_inputs_from_message(value)
    if inputs is None:
        return FingerprintEmbeddingResultOutcome.SKIPPED

    return await start_fingerprint_embedding_result_workflow(client, inputs)


class Command(BaseCommand):
    help = "Consume document embedding results and start error tracking fingerprint workflows."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--topic", default=KAFKA_DOCUMENT_EMBEDDING_RESULTS_TOPIC)
        parser.add_argument("--consumer-group", default=DEFAULT_CONSUMER_GROUP)
        parser.add_argument("--poll-timeout", type=float, default=1.0)
        parser.add_argument("--max-messages", type=int, default=None)
        parser.add_argument(
            "--health-port",
            type=int,
            default=8080,
            help="Port for the health check HTTP server (default: 8080)",
        )
        parser.add_argument(
            "--health-timeout",
            type=float,
            default=60.0,
            help="Health check timeout in seconds (default: 60.0)",
        )

    def handle(self, *args: object, **options: object) -> None:
        topic = str(options["topic"])
        consumer_group = str(options["consumer_group"])
        poll_timeout = _float_option(options, "poll_timeout")
        max_messages = options["max_messages"]
        if max_messages is not None and not isinstance(max_messages, int):
            raise TypeError("max_messages must be an integer")
        health_port = _int_option(options, "health_port")
        health_timeout = _float_option(options, "health_timeout")

        health_state = HealthState(timeout_seconds=health_timeout)
        start_health_server(port=health_port, health_state=health_state)

        asyncio.run(
            self._run_consumer(
                topic=topic,
                consumer_group=consumer_group,
                poll_timeout=poll_timeout,
                max_messages=max_messages,
                health_reporter=health_state.report_healthy,
            )
        )

    async def _run_consumer(
        self,
        topic: str,
        consumer_group: str,
        poll_timeout: float,
        max_messages: int | None,
        health_reporter: Callable[[], None] | None = None,
    ) -> None:
        consumer = self._create_consumer(topic=topic, consumer_group=consumer_group)
        temporal_client = await async_connect()
        shutdown_requested = False

        def handle_signal(signum: int, frame: object) -> None:
            nonlocal shutdown_requested
            shutdown_requested = True
            logger.info("error_tracking.embedding_results_consumer.shutdown_signal", signal=signal.Signals(signum).name)

        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, handle_signal)

        processed_messages = 0
        self.stdout.write("consumer_started")
        logger.info(
            "error_tracking.embedding_results_consumer.started",
            topic=topic,
            consumer_group=consumer_group,
        )

        try:
            while not shutdown_requested:
                if health_reporter is not None:
                    health_reporter()
                message = await _run_blocking_call(lambda: consumer.poll(poll_timeout))
                if message is None:
                    continue
                await self._handle_kafka_message(consumer, temporal_client, message)
                if health_reporter is not None:
                    health_reporter()
                processed_messages += 1
                if max_messages is not None and processed_messages >= max_messages:
                    break
        finally:
            await _run_blocking_call(consumer.close)
            logger.info(
                "error_tracking.embedding_results_consumer.stopped",
                processed_messages=processed_messages,
            )

    def _create_consumer(self, topic: str, consumer_group: str) -> ConfluentConsumer:
        profile = get_profile_settings(profile=resolve_profile_name(topic=topic))
        hosts = profile.hosts
        config: dict[str, str | int | float | bool | None] = {
            "bootstrap.servers": ",".join(hosts) if isinstance(hosts, list) else hosts,
            "security.protocol": profile.security_protocol or _KafkaSecurityProtocol.PLAINTEXT,
            "group.id": consumer_group,
            "auto.offset.reset": "latest",
            "enable.auto.commit": False,
            "partition.assignment.strategy": "cooperative-sticky",
        }
        if profile.security_protocol in (
            _KafkaSecurityProtocol.SASL_PLAINTEXT,
            _KafkaSecurityProtocol.SASL_SSL,
        ):
            config["sasl.mechanism"] = profile.sasl_mechanism
            config["sasl.username"] = profile.sasl_user
            config["sasl.password"] = profile.sasl_password

        consumer = ConfluentConsumer(config)
        consumer.subscribe([topic])
        return consumer

    async def _handle_kafka_message(
        self, consumer: ConfluentConsumer, temporal_client: Client, message: Message
    ) -> None:
        error = message.error()
        if error is not None:
            partition_eof_code = getattr(KafkaError, "_PARTITION_EOF", None)
            if partition_eof_code is not None and error.code() == partition_eof_code:
                return
            raise KafkaException(error)

        value = message.value()
        if value is None:
            logger.warning("error_tracking.embedding_results_consumer.empty_message")
            await _commit_message(consumer, message)
            return

        try:
            outcome = await handle_embedding_result_message(temporal_client, value)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as err:
            logger.warning("error_tracking.embedding_results_consumer.invalid_message", error=str(err))
            await _commit_message(consumer, message)
            return

        logger.info(
            "error_tracking.embedding_results_consumer.message_processed",
            outcome=outcome,
        )
        await _commit_message(consumer, message)
