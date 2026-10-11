"""Write gauges that PostHog computes on a team's behalf into that team's Metrics, at their own timestamps.

`posthog/otel_metrics.py` cannot do this: the OTel SDK stamps a gauge at export time and sends to one
fixed project. This module builds the OTLP protobuf by hand, so each point keeps the timestamp it
describes, and it sends with the destination team's project token.
"""

import datetime as dt
from collections.abc import Iterator, Sequence
from itertools import groupby

from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, InstrumentationScope, KeyValue
from opentelemetry.proto.metrics.v1.metrics_pb2 import Gauge, Metric, NumberDataPoint, ResourceMetrics, ScopeMetrics
from opentelemetry.proto.resource.v1.resource_pb2 import Resource

from posthog.security.outbound_proxy import internal_requests_session

from products.metrics.backend.facade.contracts import GaugeSample, GaugeWriteResult

# The capture service moves a point older than its past window to the ingest time and keeps its series
# fingerprint, so the point lands at the wrong time with no error. The margin covers clock skew and
# the time a request waits before the service reads it.
DEFAULT_PAST_WINDOW = dt.timedelta(hours=24)
PAST_WINDOW_MARGIN = dt.timedelta(hours=1)
# The capture service rejects a body over 2 MB. One point with its labels is a few hundred bytes.
MAX_POINTS_PER_REQUEST = 2000
REQUEST_TIMEOUT_SECONDS = 10


def build_export_request(samples: Sequence[GaugeSample], *, service_name: str) -> ExportMetricsServiceRequest:
    by_name = sorted(samples, key=lambda sample: sample.name)
    metrics = [
        Metric(name=name, gauge=Gauge(data_points=[_data_point(sample) for sample in group]))
        for name, group in groupby(by_name, key=lambda sample: sample.name)
    ]
    return ExportMetricsServiceRequest(
        resource_metrics=[
            ResourceMetrics(
                resource=Resource(attributes=[_attribute("service.name", service_name)]),
                scope_metrics=[ScopeMetrics(scope=InstrumentationScope(name=service_name), metrics=metrics)],
            )
        ]
    )


def write_gauges(
    samples: Sequence[GaugeSample],
    *,
    endpoint: str,
    token: str,
    service_name: str,
    now: dt.datetime,
    backfill_days: int = 0,
) -> GaugeWriteResult:
    """POST the samples to the metrics capture service. Raises on a non-2xx response.

    `backfill_days` above 0 widens the capture service's past window to that many days. The service
    rejects a value above its MAX_METRICS_BACKFILL_DAYS with a 400.
    """
    past_window = dt.timedelta(days=backfill_days) if backfill_days > 0 else DEFAULT_PAST_WINDOW
    earliest = now - past_window + PAST_WINDOW_MARGIN
    fresh = [sample for sample in samples if sample.timestamp >= earliest]
    params = {"backfill_days": str(backfill_days)} if backfill_days > 0 else None
    session = internal_requests_session()
    for chunk in _chunks(fresh, MAX_POINTS_PER_REQUEST):
        body = build_export_request(chunk, service_name=service_name).SerializeToString()
        # capture-logs is a private in-cluster service, which the egress proxy refuses with a 407.
        # internal_requests_session ignores the proxy environment variables.
        response = session.post(
            endpoint,
            params=params,
            data=body,
            headers={"content-type": "application/x-protobuf", "authorization": f"Bearer {token}"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    return GaugeWriteResult(written=len(fresh), dropped_stale=len(samples) - len(fresh))


def _data_point(sample: GaugeSample) -> NumberDataPoint:
    return NumberDataPoint(
        time_unix_nano=int(sample.timestamp.timestamp() * 1_000_000_000),
        as_double=sample.value,
        attributes=[_attribute(key, value) for key, value in sorted(sample.labels.items())],
    )


def _attribute(key: str, value: str) -> KeyValue:
    return KeyValue(key=key, value=AnyValue(string_value=value))


def _chunks(samples: Sequence[GaugeSample], size: int) -> Iterator[Sequence[GaugeSample]]:
    for start in range(0, len(samples), size):
        yield samples[start : start + size]
