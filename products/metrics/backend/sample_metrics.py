"""Realistic sample metrics for a dev stack: an Envoy proxy, two hosts, Redis, a Go checkout service and an
inference gateway. They go through the real OTLP capture path, so every table and view fills as in production.

Each counter follows a closed-form curve, so a later run continues the same cumulative values: a slow daily
wave, a faster wobble, and short incidents that repeat. Envoy, the hosts, Redis and the Go runtime match
dashboards in the curated bank. The checkout and inference metrics match nothing, so they make the
suggested dashboards generate new ones.
"""

from __future__ import annotations

import math
import zlib
import datetime as dt
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import field

import requests
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.metrics.v1 import metrics_pb2
from opentelemetry.proto.resource.v1.resource_pb2 import Resource

from posthog.dataclasses import frozen

DAY = 86_400.0
# Counters start here, so that any two runs agree on the cumulative values.
EPOCH = dt.datetime(2026, 1, 1, tzinfo=dt.UTC).timestamp()
CUMULATIVE = metrics_pb2.AggregationTemporality.AGGREGATION_TEMPORALITY_CUMULATIVE


@frozen(kw_only=False)
class Incident:
    """A burst of extra rate that repeats: `extra` per second for `duration` seconds, every `every` seconds."""

    every: float
    duration: float
    extra: float
    offset: float = 0.0

    def rate(self, t: float) -> float:
        return self.extra if (t - EPOCH - self.offset) % self.every < self.duration else 0.0

    def cumulative(self, t: float) -> float:
        elapsed = t - EPOCH - self.offset
        whole, rest = divmod(elapsed, self.every)
        return self.extra * (whole * self.duration + min(rest, self.duration))


@frozen(kw_only=False)
class Wave:
    """A rate in units per second: a base, a daily wave, a faster wobble and incidents."""

    base: float
    daily: float = 0.25
    wobble: float = 0.06
    wobble_period: float = 420.0
    phase: float = 0.0
    incidents: tuple[Incident, ...] = ()

    def rate(self, t: float) -> float:
        value = self.base * (
            1
            + self.daily * math.sin(2 * math.pi * (t / DAY) + self.phase)
            + self.wobble * math.sin(2 * math.pi * t / self.wobble_period + self.phase)
        )
        return max(value + sum(incident.rate(t) for incident in self.incidents), 0.0)

    def cumulative(self, t: float) -> float:
        def integral(x: float) -> float:
            return self.base * (
                x
                - self.daily * DAY / (2 * math.pi) * math.cos(2 * math.pi * (x / DAY) + self.phase)
                - self.wobble
                * self.wobble_period
                / (2 * math.pi)
                * math.cos(2 * math.pi * x / self.wobble_period + self.phase)
            )

        return integral(t) - integral(EPOCH) + sum(incident.cumulative(t) for incident in self.incidents)


def _jitter(key: str, t: float, step: float = 15.0) -> float:
    """A repeatable number in [-1, 1) for a series and a moment."""
    return (zlib.crc32(f"{key}:{int(t // step)}".encode()) % 2000) / 1000.0 - 1.0


@frozen(kw_only=False)
class Counter:
    name: str
    wave: Wave
    labels: dict[str, str] = field(default_factory=dict)
    unit: str = ""


@frozen(kw_only=False)
class Gauge:
    name: str
    value: Callable[[float], float]
    labels: dict[str, str] = field(default_factory=dict)
    unit: str = ""


@frozen(kw_only=False)
class Histogram:
    name: str
    wave: Wave
    bounds: tuple[float, ...]
    # The share of observations in each bucket, one more than the bounds. An incident moves its extra
    # observations into the slow shares.
    shares: tuple[float, ...]
    slow_shares: tuple[float, ...]
    labels: dict[str, str] = field(default_factory=dict)
    unit: str = ""


Instrument = Counter | Gauge | Histogram


@frozen(kw_only=False)
class Service:
    name: str
    instruments: tuple[Instrument, ...]


def _constant(value: float) -> Callable[[float], float]:
    return lambda t: value


def _queue_depth(queue: Incident, base: float, model: str) -> Callable[[float], float]:
    return lambda t: base + 40 * queue.rate(t) / max(queue.extra, 1) + 2 * _jitter(f"q-{model}", t)


def _gpu_utilization(gpu: str) -> Callable[[float], float]:
    def value(t: float) -> float:
        wave = 0.62 + 0.2 * math.sin(2 * math.pi * t / DAY) + 0.08 * _jitter(f"gpu-{gpu}", t)
        return min(0.98, max(0.05, wave))

    return value


def _gauge(
    base: float, *, daily: float = 0.1, noise: float = 0.03, key: str, floor: float = 0.0
) -> Callable[[float], float]:
    def value(t: float) -> float:
        wave = base * (1 + daily * math.sin(2 * math.pi * t / DAY) + noise * _jitter(key, t))
        return max(wave, floor)

    return value


def _envoy() -> Service:
    clusters = {"checkout": 140.0, "inference": 45.0, "catalog": 310.0}
    instruments: list[Instrument] = []
    for index, (cluster, rps) in enumerate(clusters.items()):
        labels = {"envoy_cluster_name": cluster}
        phase = index * 0.7
        errors = (Incident(every=4 * 3600, duration=900, extra=rps * 0.08, offset=index * 1800),)
        instruments += [
            Counter("envoy_cluster_upstream_rq_total", Wave(rps, phase=phase, incidents=errors), labels),
            Counter(
                "envoy_cluster_upstream_rq_xx",
                Wave(rps * 0.955, phase=phase),
                {**labels, "envoy_response_code_class": "2"},
            ),
            Counter(
                "envoy_cluster_upstream_rq_xx",
                Wave(rps * 0.04, phase=phase, wobble=0.2),
                {**labels, "envoy_response_code_class": "4"},
            ),
            Counter(
                "envoy_cluster_upstream_rq_xx",
                Wave(rps * 0.005, phase=phase, wobble=0.3, incidents=errors),
                {**labels, "envoy_response_code_class": "5"},
            ),
            Histogram(
                "envoy_cluster_upstream_rq_time",
                Wave(rps, phase=phase, incidents=errors),
                bounds=(1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000),
                shares=(0.02, 0.18, 0.25, 0.25, 0.15, 0.08, 0.04, 0.02, 0.007, 0.002, 0.001, 0.0),
                slow_shares=(0.0, 0.0, 0.02, 0.05, 0.08, 0.15, 0.25, 0.25, 0.12, 0.06, 0.02, 0.0),
                labels=labels,
                unit="ms",
            ),
            Gauge("envoy_cluster_upstream_cx_active", _gauge(rps / 6, key=f"cx-{cluster}"), labels),
            Gauge("envoy_cluster_membership_healthy", _constant(float(3 + index % 2)), labels),
            Counter("envoy_cluster_upstream_rq_retry", Wave(rps * 0.004, wobble=0.4, incidents=errors), labels),
            Counter("envoy_cluster_upstream_rq_timeout", Wave(rps * 0.0008, wobble=0.5), labels),
            Counter("envoy_cluster_upstream_cx_connect_fail", Wave(0.05, wobble=0.8), labels),
        ]
    for prefix, rps in (("ingress_http", 495.0), ("admin", 0.4)):
        instruments.append(
            Counter("envoy_http_downstream_rq_total", Wave(rps), {"envoy_http_conn_manager_prefix": prefix})
        )
    instruments.append(Gauge("envoy_server_live", lambda t: 1.0))
    return Service("edge-proxy", tuple(instruments))


GIB = 1024**3


def _hosts() -> Service:
    instruments: list[Instrument] = []
    for index, host in enumerate(("web-1:9100", "web-2:9100")):
        labels = {"instance": host}
        busy = 0.35 + 0.15 * index
        for mode, share in (("user", 0.7), ("system", 0.22), ("iowait", 0.08)):
            instruments.append(
                Counter("node_cpu_seconds_total", Wave(4 * busy * share, daily=0.35), {**labels, "mode": mode}, "s")
            )
        instruments.append(
            Counter("node_cpu_seconds_total", Wave(4 * (1 - busy), daily=-0.25), {**labels, "mode": "idle"}, "s")
        )
        instruments += [
            Gauge("node_memory_MemTotal_bytes", lambda t: 16.0 * GIB, labels, "By"),
            Gauge(
                "node_memory_MemAvailable_bytes",
                _gauge((6.5 - 2 * index) * GIB, daily=-0.12, key=f"mem-{host}"),
                labels,
                "By",
            ),
            Gauge("node_load1", _gauge(1.4 + index, daily=0.4, noise=0.15, key=f"load1-{host}"), labels),
            Gauge("node_load5", _gauge(1.3 + index, daily=0.35, noise=0.06, key=f"load5-{host}"), labels),
            Gauge("node_load15", _gauge(1.2 + index, daily=0.3, noise=0.02, key=f"load15-{host}"), labels),
        ]
        for mount, size, free in (("/", 80, 31 - 6 * index), ("/data", 500, 210 + 40 * index)):
            mount_labels = {**labels, "mountpoint": mount, "fstype": "ext4"}
            instruments += [
                Gauge("node_filesystem_size_bytes", _constant(size * GIB), mount_labels, "By"),
                Gauge(
                    "node_filesystem_avail_bytes",
                    _gauge(free * GIB, daily=0.01, noise=0.002, key=f"fs-{host}-{mount}"),
                    mount_labels,
                    "By",
                ),
            ]
        device = {**labels, "device": "eth0"}
        disk = {**labels, "device": "nvme0n1"}
        instruments += [
            Counter("node_network_receive_bytes_total", Wave(9.5e6 + 3e6 * index, daily=0.4), device, "By"),
            Counter("node_network_transmit_bytes_total", Wave(6.1e6 + 2e6 * index, daily=0.4), device, "By"),
            Counter("node_disk_read_bytes_total", Wave(2.2e6, wobble=0.3), disk, "By"),
            Counter("node_disk_written_bytes_total", Wave(4.8e6, wobble=0.25), disk, "By"),
        ]
    return Service("node-exporter", tuple(instruments))


def _redis() -> Service:
    labels = {"instance": "redis-1:6379"}
    commands = Wave(5200.0, daily=0.35)
    instruments: list[Instrument] = [
        Gauge("redis_connected_clients", _gauge(84, daily=0.2, noise=0.05, key="redis-clients"), labels),
        Gauge("redis_blocked_clients", _gauge(2, daily=0.0, noise=0.5, key="redis-blocked"), labels),
        Counter("redis_commands_processed_total", commands, labels),
        Counter("redis_keyspace_hits_total", Wave(3900.0, daily=0.35), labels),
        Counter(
            "redis_keyspace_misses_total",
            Wave(260.0, daily=0.3, incidents=(Incident(every=6 * 3600, duration=1200, extra=900.0),)),
            labels,
        ),
        Gauge("redis_memory_used_bytes", _gauge(2.6 * GIB, daily=0.05, noise=0.01, key="redis-mem"), labels, "By"),
        Gauge("redis_memory_max_bytes", lambda t: 4.0 * GIB, labels, "By"),
        Counter("redis_evicted_keys_total", Wave(3.0, wobble=0.6), labels),
        Counter("redis_expired_keys_total", Wave(41.0, wobble=0.2), labels),
        Counter("redis_net_input_bytes_total", Wave(1.9e6, daily=0.35), labels, "By"),
        Counter("redis_net_output_bytes_total", Wave(7.4e6, daily=0.35), labels, "By"),
    ]
    for db, keys in (("db0", 1_240_000), ("db1", 88_000)):
        instruments.append(
            Gauge("redis_db_keys", _gauge(keys, daily=0.03, noise=0.002, key=f"keys-{db}"), {**labels, "db": db})
        )
    return Service("redis-exporter", tuple(instruments))


def _go_runtime(service: str, scale: float) -> list[Instrument]:
    return [
        Gauge("go_goroutines", _gauge(420 * scale, daily=0.3, noise=0.08, key=f"goroutines-{service}")),
        Gauge("go_threads", _gauge(18, daily=0.0, noise=0.05, key=f"threads-{service}")),
        Gauge(
            "go_memstats_heap_inuse_bytes",
            _gauge(310e6 * scale, daily=0.2, noise=0.1, key=f"heap-{service}"),
            unit="By",
        ),
        Gauge(
            "go_memstats_heap_alloc_bytes",
            _gauge(260e6 * scale, daily=0.2, noise=0.12, key=f"alloc-{service}"),
            unit="By",
        ),
        Counter("go_memstats_alloc_bytes_total", Wave(48e6 * scale, daily=0.3), unit="By"),
        Counter("process_cpu_seconds_total", Wave(0.9 * scale, daily=0.35), unit="s"),
        Gauge(
            "process_resident_memory_bytes",
            _gauge(520e6 * scale, daily=0.1, noise=0.03, key=f"rss-{service}"),
            unit="By",
        ),
        Gauge("process_open_fds", _gauge(212, daily=0.15, noise=0.05, key=f"fds-{service}")),
        Gauge("process_max_fds", lambda t: 65536.0),
    ]


def _checkout() -> Service:
    declines = (Incident(every=5 * 3600, duration=1500, extra=1.6, offset=2400),)
    instruments: list[Instrument] = []
    for method, rate in (("card", 3.1), ("paypal", 0.9), ("wallet", 1.4)):
        instruments.append(Counter("checkout_orders_created_total", Wave(rate, daily=0.45), {"payment_method": method}))
    for provider, share in (("stripe", 0.75), ("adyen", 0.25)):
        provider_labels = {"provider": provider}
        instruments += [
            Counter(
                "checkout_payment_attempts_total",
                Wave(5.8 * share, daily=0.45),
                {**provider_labels, "result": "succeeded"},
            ),
            Counter(
                "checkout_payment_attempts_total",
                Wave(0.35 * share, daily=0.4, wobble=0.3, incidents=declines if provider == "adyen" else ()),
                {**provider_labels, "result": "declined"},
            ),
            Counter(
                "checkout_payment_attempts_total",
                Wave(0.04 * share, wobble=0.6),
                {**provider_labels, "result": "error"},
            ),
            Histogram(
                "checkout_payment_duration_seconds",
                Wave(6.2 * share, daily=0.45, incidents=declines if provider == "adyen" else ()),
                bounds=(0.05, 0.1, 0.25, 0.5, 1, 2, 5),
                shares=(0.05, 0.2, 0.4, 0.22, 0.09, 0.03, 0.01, 0.0),
                slow_shares=(0.0, 0.0, 0.05, 0.15, 0.3, 0.3, 0.15, 0.05),
                labels=provider_labels,
                unit="s",
            ),
        ]
    instruments += [
        Histogram(
            "checkout_cart_value_dollars",
            Wave(5.4, daily=0.45),
            bounds=(10, 25, 50, 100, 250, 500),
            shares=(0.08, 0.22, 0.3, 0.24, 0.12, 0.03, 0.01),
            slow_shares=(0.08, 0.22, 0.3, 0.24, 0.12, 0.03, 0.01),
            unit="USD",
        ),
        Gauge("checkout_inventory_reservations_active", _gauge(37, daily=0.5, noise=0.2, key="reservations")),
        Counter("checkout_abandoned_carts_total", Wave(2.2, daily=0.4, wobble=0.15)),
        Counter("checkout_webhook_deliveries_total", Wave(6.0, daily=0.45), {"status": "delivered"}),
        Counter("checkout_webhook_deliveries_total", Wave(0.07, wobble=0.7), {"status": "failed"}),
    ]
    for verdict, rate in (("approved", 5.5), ("review", 0.3), ("rejected", 0.08)):
        instruments.append(Counter("checkout_fraud_checks_total", Wave(rate, daily=0.45), {"verdict": verdict}))
    return Service("checkout-service", tuple(instruments + _go_runtime("checkout", 1.0)))


def _inference() -> Service:
    slow = (Incident(every=3 * 3600, duration=600, extra=3.0, offset=900),)
    instruments: list[Instrument] = []
    for index, (model, rps) in enumerate((("small", 7.5), ("large", 2.1))):
        labels = {"model": model}
        queue = Incident(every=3 * 3600, duration=600, extra=rps * 0.6, offset=900 + index * 300)
        instruments += [
            Counter("inference_requests_total", Wave(rps, daily=0.5), {**labels, "status": "ok"}),
            Counter("inference_requests_total", Wave(rps * 0.01, wobble=0.5), {**labels, "status": "error"}),
            Counter(
                "inference_requests_total",
                Wave(0.001, wobble=0.0, daily=0.0, incidents=(queue,)),
                {**labels, "status": "rate_limited"},
            ),
            Counter("inference_tokens_total", Wave(rps * 850, daily=0.5), {**labels, "direction": "input"}),
            Counter("inference_tokens_total", Wave(rps * 310, daily=0.5), {**labels, "direction": "output"}),
            Histogram(
                "inference_request_duration_seconds",
                Wave(rps, daily=0.5, incidents=(queue,)),
                bounds=(0.1, 0.25, 0.5, 1, 2, 4, 8, 16),
                shares=(0.02, 0.1, 0.25, 0.3, 0.2, 0.09, 0.03, 0.01, 0.0)
                if model == "small"
                else (0.0, 0.01, 0.05, 0.14, 0.3, 0.3, 0.15, 0.04, 0.01),
                slow_shares=(0.0, 0.0, 0.01, 0.04, 0.15, 0.3, 0.3, 0.15, 0.05),
                labels=labels,
                unit="s",
            ),
            Histogram(
                "inference_time_to_first_token_seconds",
                Wave(rps, daily=0.5, incidents=(queue,)),
                bounds=(0.05, 0.1, 0.2, 0.4, 0.8, 1.6),
                shares=(0.1, 0.35, 0.3, 0.15, 0.07, 0.02, 0.01),
                slow_shares=(0.0, 0.02, 0.08, 0.2, 0.35, 0.25, 0.1),
                labels=labels,
                unit="s",
            ),
            Gauge("inference_queue_depth", _queue_depth(queue, 3.0 + 4 * index, model), labels),
        ]
    for gpu in ("0", "1"):
        instruments.append(Gauge("inference_gpu_utilization_ratio", _gpu_utilization(gpu), {"gpu": gpu}, "1"))
    instruments += [
        Counter("inference_cache_hits_total", Wave(2.7, daily=0.5)),
        Counter("inference_cache_misses_total", Wave(6.9, daily=0.5, incidents=slow)),
    ]
    return Service("inference-gateway", tuple(instruments))


SERVICES: tuple[Callable[[], Service], ...] = (_envoy, _hosts, _redis, _checkout, _inference)


def _attributes(values: dict[str, str]) -> list[KeyValue]:
    return [KeyValue(key=key, value=AnyValue(string_value=value)) for key, value in sorted(values.items())]


def _nanos(t: float) -> int:
    return int(t * 1e9)


def _histogram_counts(histogram: Histogram, t: float) -> tuple[list[int], int, float]:
    total = histogram.wave.cumulative(t)
    incident = sum(incident.cumulative(t) for incident in histogram.wave.incidents)
    normal = total - incident
    counts = [int(normal * share + incident * slow) for share, slow in zip(histogram.shares, histogram.slow_shares)]
    edges = (0.0, *histogram.bounds)
    mids = [(edges[i] + edges[i + 1]) / 2 for i in range(len(histogram.bounds))] + [histogram.bounds[-1] * 1.5]
    return counts, sum(counts), sum(count * mid for count, mid in zip(counts, mids))


def _metric(instrument: Instrument, times: Sequence[float]) -> metrics_pb2.Metric:
    attributes = _attributes(instrument.labels)
    metric = metrics_pb2.Metric(name=instrument.name, unit=instrument.unit)
    if isinstance(instrument, Counter):
        metric.sum.aggregation_temporality = CUMULATIVE
        metric.sum.is_monotonic = True
        for t in times:
            metric.sum.data_points.append(
                metrics_pb2.NumberDataPoint(
                    attributes=attributes,
                    start_time_unix_nano=_nanos(EPOCH),
                    time_unix_nano=_nanos(t),
                    as_double=instrument.wave.cumulative(t),
                )
            )
    elif isinstance(instrument, Gauge):
        for t in times:
            metric.gauge.data_points.append(
                metrics_pb2.NumberDataPoint(
                    attributes=attributes, time_unix_nano=_nanos(t), as_double=float(instrument.value(t))
                )
            )
    else:
        metric.histogram.aggregation_temporality = CUMULATIVE
        for t in times:
            counts, count, total = _histogram_counts(instrument, t)
            metric.histogram.data_points.append(
                metrics_pb2.HistogramDataPoint(
                    attributes=attributes,
                    start_time_unix_nano=_nanos(EPOCH),
                    time_unix_nano=_nanos(t),
                    count=count,
                    sum=total,
                    bucket_counts=counts,
                    explicit_bounds=list(histogram_bounds(instrument)),
                )
            )
    return metric


def histogram_bounds(histogram: Histogram) -> tuple[float, ...]:
    return tuple(float(bound) for bound in histogram.bounds)


def export_request(services: Iterable[Service], times: Sequence[float]) -> ExportMetricsServiceRequest:
    request = ExportMetricsServiceRequest()
    for service in services:
        resource_metrics = request.resource_metrics.add()
        resource_metrics.resource.CopyFrom(Resource(attributes=_attributes({"service.name": service.name})))
        scope = resource_metrics.scope_metrics.add()
        scope.scope.name = "posthog-sample-metrics"
        scope.metrics.extend(_metric(instrument, times) for instrument in service.instruments)
    return request


def sample_services() -> list[Service]:
    return [build() for build in SERVICES]


def time_steps(start: float, end: float, step: float) -> Iterator[float]:
    t = start - start % step
    while t <= end:
        yield t
        t += step


def send(url: str, token: str, request: ExportMetricsServiceRequest) -> None:
    response = requests.post(
        url.rstrip("/") + "/i/v1/metrics",
        data=request.SerializeToString(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/x-protobuf"},
        timeout=60,
    )
    response.raise_for_status()
