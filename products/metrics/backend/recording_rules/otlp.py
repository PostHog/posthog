"""Writing a recording rule's result into the team's metrics, through the same OTLP endpoint services send to."""

from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from typing import Final

from django.conf import settings

import requests
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.metrics.v1 import metrics_pb2
from opentelemetry.proto.resource.v1.resource_pb2 import Resource

from posthog.dataclasses import frozen
from posthog.security.outbound_proxy import internal_requests

# Ingestion keeps `service.name` in its own column, and PromQL calls that column `service_name`.
SERVICE_LABEL: Final = "service_name"
SCOPE_NAME: Final = "posthog-metrics-recording-rules"
SEND_TIMEOUT_SECONDS: Final = 10


@frozen
class RecordedSample:
    labels: dict[str, str]
    # None for a sample that is not a number, such as the result of 0/0.
    value: float | None


class IngestError(Exception):
    pass


class IngestUnconfirmed(IngestError):
    """The request went out, but no answer came back, so ingestion may have stored it."""


def _attributes(values: dict[str, str]) -> list[KeyValue]:
    return [KeyValue(key=key, value=AnyValue(string_value=value)) for key, value in sorted(values.items())]


def export_request(metric_name: str, samples: Sequence[RecordedSample], at: datetime) -> ExportMetricsServiceRequest:
    """One gauge point per sample at `at`. `service_name` goes back to the resource, so the recorded series
    has the same labels in PromQL as the query result. A sample that is not a number has no point."""
    by_service: dict[str, list[tuple[dict[str, str], float]]] = defaultdict(list)
    for sample in samples:
        if sample.value is not None:
            by_service[sample.labels.get(SERVICE_LABEL, "")].append((sample.labels, sample.value))
    time_unix_nano = int(at.timestamp() * 1e9)
    request = ExportMetricsServiceRequest()
    for service, service_samples in sorted(by_service.items()):
        resource_metrics = request.resource_metrics.add()
        resource_metrics.resource.CopyFrom(
            Resource(attributes=_attributes({"service.name": service} if service else {}))
        )
        scope = resource_metrics.scope_metrics.add()
        scope.scope.name = SCOPE_NAME
        metric = scope.metrics.add()
        metric.name = metric_name
        for labels, value in service_samples:
            attributes = {key: label for key, label in labels.items() if key not in ("__name__", SERVICE_LABEL)}
            metric.gauge.data_points.append(
                metrics_pb2.NumberDataPoint(
                    attributes=_attributes(attributes), time_unix_nano=time_unix_nano, as_double=value
                )
            )
    return request


def send(token: str, request: ExportMetricsServiceRequest) -> None:
    try:
        response = internal_requests.post(
            settings.METRICS_RECORDING_RULES_INGEST_URL.rstrip("/") + "/i/v1/metrics",
            data=request.SerializeToString(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/x-protobuf"},
            timeout=SEND_TIMEOUT_SECONDS,
        )
    except requests.ReadTimeout as error:
        raise IngestUnconfirmed("Metrics ingestion did not confirm the write in time.") from error
    except Exception as error:
        raise IngestError("Metrics ingestion could not be reached.") from error
    if not 200 <= response.status_code < 300:
        raise IngestError(f"Metrics ingestion refused the result with status {response.status_code}.")
