"""Generates realistic demo log entries for local development.

Inserts OpenTelemetry-shaped rows directly into the ClickHouse `logs` table
(bypassing Kafka) so that `generate_demo_data` can seed any team with logs
that look like a small Kubernetes-deployed app stack.
"""

import json
import random
import datetime as dt
from collections.abc import Iterable
from typing import Any

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.workload import Workload
from posthog.models.utils import uuid7

# Sentence-cased severity_text plus OTel severity_number.
# https://opentelemetry.io/docs/specs/otel/logs/data-model/#field-severitynumber
_SEVERITY_NUMBERS = {
    "trace": 1,
    "debug": 5,
    "info": 9,
    "warn": 13,
    "error": 17,
    "fatal": 21,
}

# Weighted severity distribution — info dominates, errors are rare.
_SEVERITY_DISTRIBUTION: list[tuple[str, float]] = [
    ("info", 0.65),
    ("debug", 0.18),
    ("warn", 0.10),
    ("error", 0.06),
    ("fatal", 0.01),
]


# A small fictional service mesh themed around the Hedgebox demo product.
# Each service has a few representative log templates per severity.
_SERVICES: list[dict[str, Any]] = [
    {
        "name": "hedgebox-web",
        "namespace": "hedgebox",
        "container": "hedgebox-web",
        "deployment": "hedgebox-web",
        "image": "ghcr.io/hedgebox/web",
        "image_tag": "v2.41.0",
        "templates": {
            "info": [
                ("GET {path} 200 in {duration_ms}ms", {"http.method": "GET", "http.status_code": "200"}),
                ("POST {path} 201 in {duration_ms}ms", {"http.method": "POST", "http.status_code": "201"}),
                ("GET {path} 304 in {duration_ms}ms", {"http.method": "GET", "http.status_code": "304"}),
                ("Authenticated user user_{user_id}", {"event": "user_authenticated"}),
            ],
            "debug": [
                ("Cache hit on key user:{user_id}:profile", {"cache.key": "user_profile"}),
                ("Resolved feature flag new-share-flow=true for user_{user_id}", {"flag": "new-share-flow"}),
            ],
            "warn": [
                ("Slow query (>500ms) on /api/files: {duration_ms}ms", {"db.statement": "SELECT files"}),
                ("Rate limit approaching for user_{user_id}: 90/100 req/min", {"event": "rate_limit_warning"}),
            ],
            "error": [
                (
                    "Internal Server Error: {path}",
                    {"event": "server_error", "exception": "RuntimeError: connection reset by peer"},
                ),
                ("Failed to process upload for user_{user_id}: storage backend timeout", {"event": "upload_failed"}),
            ],
            "fatal": [
                ("Worker pid {pid} died unexpectedly, restarting", {"event": "worker_died"}),
            ],
        },
    },
    {
        "name": "hedgebox-worker",
        "namespace": "hedgebox",
        "container": "hedgebox-worker",
        "deployment": "hedgebox-worker",
        "image": "ghcr.io/hedgebox/worker",
        "image_tag": "v2.41.0",
        "templates": {
            "info": [
                ("Task hedgebox.tasks.scan_file[{task_id}] succeeded in {duration_ms}ms", {"task.name": "scan_file"}),
                (
                    "Task hedgebox.tasks.send_share_email[{task_id}] succeeded in {duration_ms}ms",
                    {"task.name": "send_share_email"},
                ),
                ("Acquired lock daily-cleanup", {"event": "lock_acquired"}),
            ],
            "debug": [
                ("Polling for next task (queue=default)", {"queue": "default"}),
                ("Heartbeat OK", {"event": "heartbeat"}),
            ],
            "warn": [
                (
                    "Task hedgebox.tasks.scan_file[{task_id}] retry 1/3 after timeout",
                    {"task.name": "scan_file", "task.retry": "1"},
                ),
                ("Queue depth high: default has {queue_depth} pending tasks", {"queue": "default"}),
            ],
            "error": [
                (
                    "Task hedgebox.tasks.scan_file[{task_id}] failed: virus scan service unreachable",
                    {"task.name": "scan_file", "exception": "ConnectionError: virus scan service unreachable"},
                ),
            ],
        },
    },
    {
        "name": "hedgebox-uploader",
        "namespace": "hedgebox",
        "container": "hedgebox-uploader",
        "deployment": "hedgebox-uploader",
        "image": "ghcr.io/hedgebox/uploader",
        "image_tag": "v0.18.2",
        "templates": {
            "info": [
                ("Started multipart upload for file_{file_id} ({size_mb}MB)", {"event": "upload_started"}),
                ("Completed multipart upload for file_{file_id} in {duration_ms}ms", {"event": "upload_completed"}),
                ("Generated presigned URL for file_{file_id}", {"event": "presigned_url"}),
            ],
            "warn": [
                (
                    "Retrying S3 PutObject for file_{file_id} (attempt 2)",
                    {"s3.bucket": "hedgebox-storage", "retry": "2"},
                ),
            ],
            "error": [
                (
                    "S3 PutObject failed for file_{file_id}: SlowDown",
                    {"s3.bucket": "hedgebox-storage", "exception": "ClientError: SlowDown"},
                ),
            ],
        },
    },
    {
        "name": "hedgebox-billing",
        "namespace": "hedgebox",
        "container": "hedgebox-billing",
        "deployment": "hedgebox-billing",
        "image": "ghcr.io/hedgebox/billing",
        "image_tag": "v1.7.3",
        "templates": {
            "info": [
                ("Charged customer cus_{customer_id} ${amount} for plan_pro", {"stripe.customer_id": "cus_xxx"}),
                ("Issued invoice inv_{invoice_id} to cus_{customer_id}", {"stripe.invoice_id": "inv_xxx"}),
            ],
            "warn": [
                ("Webhook signature validation took {duration_ms}ms (threshold: 200ms)", {"event": "slow_webhook"}),
                ("Card expiring soon for cus_{customer_id}", {"event": "card_expiring"}),
            ],
            "error": [
                ("Failed to charge cus_{customer_id}: card_declined", {"stripe.error": "card_declined"}),
            ],
        },
    },
    {
        "name": "hedgebox-mailer",
        "namespace": "hedgebox",
        "container": "hedgebox-mailer",
        "deployment": "hedgebox-mailer",
        "image": "ghcr.io/hedgebox/mailer",
        "image_tag": "v0.5.1",
        "templates": {
            "info": [
                ("Delivered template share_invite to user_{user_id}@example.com", {"email.template": "share_invite"}),
                ("Delivered template welcome to user_{user_id}@example.com", {"email.template": "welcome"}),
            ],
            "warn": [
                ("SES throttled, requeueing message msg_{task_id}", {"event": "ses_throttle"}),
            ],
            "error": [
                ("Hard bounce for user_{user_id}@example.com: 5.1.1 mailbox not found", {"event": "hard_bounce"}),
            ],
        },
    },
    {
        "name": "pgbouncer",
        "namespace": "hedgebox",
        "container": "pgbouncer",
        "deployment": "pgbouncer",
        "image": "edoburu/pgbouncer",
        "image_tag": "1.22.0",
        "templates": {
            "info": [
                ("stats: {duration_ms} xacts/s, 0 conn/s, in 12 KB/s, out 18 KB/s, query 8 us", {"event": "stats"}),
                (
                    "C-0x7f: hedgebox/hedgebox@10.30.{octet1}.{octet2}:5432 closing because: client unexpected eof",
                    {"event": "client_disconnected"},
                ),
            ],
            "warn": [
                ("connection pool nearly exhausted: {queue_depth}/100 active", {"event": "pool_pressure"}),
            ],
            "error": [
                (
                    "server connect failed: server closed the connection unexpectedly",
                    {"exception": "OperationalError: server closed the connection unexpectedly"},
                ),
            ],
        },
    },
    {
        "name": "nginx-ingress",
        "namespace": "ingress-nginx",
        "container": "controller",
        "deployment": "nginx-ingress-controller",
        "image": "registry.k8s.io/ingress-nginx/controller",
        "image_tag": "v1.10.1",
        "templates": {
            "info": [
                (
                    '10.30.{octet1}.{octet2} - - "GET {path} HTTP/2.0" 200 {size_mb} "-" "Mozilla/5.0" {duration_ms}',
                    {"http.method": "GET", "http.status_code": "200"},
                ),
                (
                    '10.30.{octet1}.{octet2} - - "POST {path} HTTP/2.0" 201 {size_mb} "-" "Mozilla/5.0" {duration_ms}',
                    {"http.method": "POST", "http.status_code": "201"},
                ),
            ],
            "warn": [
                (
                    "upstream timed out (110: Connection timed out) while reading response header from upstream, client: 10.30.{octet1}.{octet2}",
                    {"event": "upstream_timeout"},
                ),
            ],
            "error": [
                (
                    "connect() failed (111: Connection refused) while connecting to upstream",
                    {"exception": "connect() failed: connection refused"},
                ),
            ],
        },
    },
]


_PATHS = [
    "/api/files",
    "/api/files/upload",
    "/api/shares",
    "/api/account",
    "/api/billing/invoices",
    "/api/notifications",
    "/dashboard",
    "/login",
    "/signup",
    "/files/recent",
]


def _zero_padded_trace_id() -> str:
    return "00000000000000000000000000000000"


def _zero_padded_span_id() -> str:
    return "0000000000000000"


def _hex(rng: random.Random, length: int) -> str:
    return "".join(rng.choices("0123456789abcdef", k=length))


def _format_template(template: str, rng: random.Random) -> str:
    return template.format(
        path=rng.choice(_PATHS),
        duration_ms=rng.randint(2, 1800),
        user_id=rng.randint(1000, 99999),
        task_id=_hex(rng, 8),
        file_id=_hex(rng, 12),
        size_mb=rng.randint(1, 250),
        customer_id=_hex(rng, 12),
        invoice_id=_hex(rng, 12),
        amount=rng.choice([19, 49, 99, 199, 499]),
        queue_depth=rng.randint(50, 500),
        pid=rng.randint(20, 32000),
        octet1=rng.randint(0, 255),
        octet2=rng.randint(0, 255),
    )


def _pick_severity(rng: random.Random) -> str:
    roll = rng.random()
    cumulative = 0.0
    for severity, weight in _SEVERITY_DISTRIBUTION:
        cumulative += weight
        if roll <= cumulative:
            return severity
    return "info"


def _pod_name(rng: random.Random, deployment: str) -> str:
    suffix = "".join(rng.choices("0123456789abcdef", k=10))
    short = "".join(rng.choices("0123456789abcdefghijklmnopqrstuvwxyz", k=5))
    return f"{deployment}-{suffix}-{short}"


def _stable_pod_pool(rng: random.Random, service: dict[str, Any]) -> list[dict[str, str]]:
    """Each service gets 1-3 pods that persist across the whole window — matches real
    deployments where pods rarely cycle within a demo timeframe."""
    pod_count = rng.randint(1, 3)
    return [
        {
            "k8s.cluster.name": "demo",
            "k8s.namespace.name": service["namespace"],
            "k8s.deployment.name": service["deployment"],
            "k8s.replicaset.name": f"{service['deployment']}-{''.join(rng.choices('0123456789abcdef', k=10))}",
            "k8s.container.name": service["container"],
            "k8s.container.restart_count": "0",
            "k8s.pod.name": _pod_name(rng, service["deployment"]),
            "k8s.pod.uid": str(_uuid4(rng)),
            "k8s.node.name": f"ip-10-22-{rng.randint(0, 255)}-{rng.randint(0, 255)}.ec2.internal",
            "container.image.name": service["image"],
            "container.image.tag": service["image_tag"],
            "service.name": service["name"],
        }
        for _ in range(pod_count)
    ]


def _uuid4(rng: random.Random) -> str:
    """Deterministic UUID4 from a seeded RNG."""
    return f"{rng.getrandbits(32):08x}-{rng.getrandbits(16):04x}-{rng.getrandbits(16):04x}-{rng.getrandbits(16):04x}-{rng.getrandbits(48):012x}"


def _row_for(
    rng: random.Random,
    timestamp: dt.datetime,
    team_id: int,
    service: dict[str, Any],
    pod: dict[str, str],
) -> dict[str, Any]:
    severity = _pick_severity(rng)
    templates = service["templates"].get(severity)
    # Not every service has every severity — fall back to info if missing.
    if not templates:
        severity = "info"
        templates = service["templates"]["info"]
    body_template, base_attrs = rng.choice(templates)
    body = _format_template(body_template, rng)

    # Attribute keys must end with `__str` to match the in-table materialized
    # representation that demo writes target. This mirrors the existing test
    # fixtures in test_logs.jsonnd.
    attributes_map_str = {f"{k}__str": v for k, v in base_attrs.items()}
    attributes_map_str["log.iostream__str"] = "stdout" if severity in ("info", "debug") else "stderr"
    attributes_map_str["logtag__str"] = "F"
    attributes_map_str["pid__str"] = str(rng.randint(20, 32000))

    observed = timestamp + dt.timedelta(milliseconds=rng.randint(50, 800))

    return {
        "uuid": str(uuid7(int(timestamp.timestamp() * 1000), random=rng)),
        "team_id": team_id,
        "trace_id": _zero_padded_trace_id(),
        "span_id": _zero_padded_span_id(),
        "trace_flags": 0,
        "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S.%f"),
        "observed_timestamp": observed.strftime("%Y-%m-%d %H:%M:%S.%f"),
        "body": body,
        "severity_text": severity,
        "severity_number": _SEVERITY_NUMBERS[severity],
        "service_name": service["name"],
        "resource_attributes": pod,
        "instrumentation_scope": "@",
        "event_name": "",
        "attributes_map_str": attributes_map_str,
    }


def _iter_rows(
    *,
    team_id: int,
    start: dt.datetime,
    end: dt.datetime,
    rng: random.Random,
    logs_per_minute: int,
) -> Iterable[dict[str, Any]]:
    pods_by_service = {service["name"]: _stable_pod_pool(rng, service) for service in _SERVICES}

    # Walk minute-by-minute so timestamps are realistic (and so log volume
    # follows wall-clock time for demo dashboards).
    current = start
    one_minute = dt.timedelta(minutes=1)
    while current < end:
        for _ in range(logs_per_minute):
            service = rng.choice(_SERVICES)
            pod = rng.choice(pods_by_service[service["name"]])
            offset = dt.timedelta(seconds=rng.uniform(0, 60))
            yield _row_for(rng, current + offset, team_id, service, pod)
        current += one_minute


def generate_demo_logs(
    team_id: int,
    *,
    now: dt.datetime,
    days_past: int,
    days_future: int = 0,
    seed: str | None = None,
    logs_per_minute: int = 6,
    batch_size: int = 5000,
) -> int:
    """Generate and insert realistic demo log rows for the given team.

    Returns the number of rows inserted. Future-dated rows are NOT generated —
    logs are inherently retrospective and demo dashboards default to past
    windows.
    """
    if days_past <= 0:
        return 0
    end = now
    start = now - dt.timedelta(days=days_past)
    rng = random.Random(seed)

    total = 0
    batch: list[dict[str, Any]] = []
    for row in _iter_rows(team_id=team_id, start=start, end=end, rng=rng, logs_per_minute=logs_per_minute):
        batch.append(row)
        if len(batch) >= batch_size:
            _insert_batch(batch)
            total += len(batch)
            batch = []
    if batch:
        _insert_batch(batch)
        total += len(batch)
    return total


def _insert_batch(rows: list[dict[str, Any]]) -> None:
    payload = "\n".join(json.dumps(row) for row in rows)
    sync_execute(
        f"INSERT INTO logs FORMAT JSONEachRow\n{payload}",
        workload=Workload.LOGS,
    )
