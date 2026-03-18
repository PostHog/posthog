"""
Business logic for tracing.

Validation, calculations, business rules, ORM queries.
Called by facade/api.py.
"""

import uuid
import random
import datetime as dt
from collections import Counter


def _random_uuid(rng: random.Random) -> str:
    return uuid.UUID(int=rng.getrandbits(128), version=4).hex


def _span(
    rng: random.Random,
    trace_id: str,
    span_id: str,
    parent_span_id: str,
    name: str,
    kind: int,
    service_name: str,
    status_code: int,
    start: dt.datetime,
    duration_ms: float,
) -> dict:
    duration_nano = int(duration_ms * 1_000_000)
    return {
        "uuid": _random_uuid(rng),
        "trace_id": trace_id,
        "span_id": span_id,
        "parent_span_id": parent_span_id,
        "name": name,
        "kind": kind,
        "service_name": service_name,
        "status_code": status_code,
        "timestamp": start.isoformat(),
        "end_time": (start + dt.timedelta(milliseconds=duration_ms)).isoformat(),
        "duration_nano": duration_nano,
    }


# Each trace template is a list of (offset_ms, duration_ms, name, kind, service, status_code) tuples.
# The first entry is the root span (parent_span_id=""), subsequent entries are children.
# Children reference their parent by index in the template.
_TRACE_TEMPLATES: list[dict] = [
    {
        "name": "POST /api/checkout",
        "spans": [
            # (offset_ms, duration_ms, name, kind, service, status, parent_idx)
            (0, 320, "POST /api/checkout", 2, "api-gateway", 1, None),
            (2, 18, "authenticate", 3, "auth-service", 1, 0),
            (4, 3, "redis.get token", 3, "redis", 1, 1),
            (22, 45, "validate_cart", 3, "cart-service", 1, 0),
            (25, 12, "SELECT cart_items", 3, "postgres", 1, 3),
            (40, 5, "redis.get pricing", 3, "redis", 1, 3),
            (70, 35, "check_inventory", 3, "inventory-service", 1, 0),
            (73, 28, "SELECT stock WHERE sku IN (...)", 3, "postgres", 1, 6),
            (110, 180, "charge_payment", 3, "payment-service", 1, 0),
            (115, 155, "POST stripe.com/v1/charges", 3, "stripe-client", 1, 8),
            (275, 12, "INSERT payment_records", 3, "postgres", 1, 8),
            (295, 20, "send_confirmation", 3, "notification-service", 1, 0),
            (298, 8, "kafka.produce email.send", 4, "kafka", 1, 11),
        ],
    },
    {
        "name": "GET /api/products",
        "spans": [
            (0, 8, "GET /api/products", 2, "api-gateway", 1, None),
            (1, 2, "redis.get products:featured", 3, "redis", 1, 0),
        ],
    },
    {
        "name": "POST /api/search",
        "spans": [
            (0, 850, "POST /api/search", 2, "api-gateway", 1, None),
            (3, 840, "execute_search", 3, "search-service", 1, 0),
            (5, 502, "elasticsearch.query", 3, "elasticsearch", 2, 1),
            (510, 200, "elasticsearch.query (retry)", 3, "elasticsearch", 1, 1),
            (715, 120, "rank_results", 3, "ranking-service", 1, 1),
            (720, 95, "ml.predict relevance_scores", 1, "ml-model", 1, 4),
        ],
    },
    {
        "name": "kafka.consume order.created",
        "spans": [
            (0, 150, "kafka.consume order.created", 5, "order-processor", 1, None),
            (2, 145, "process_order", 1, "order-processor", 1, 0),
            (5, 15, "SELECT order_details", 3, "postgres", 1, 1),
            (25, 10, "UPDATE orders SET status='processing'", 3, "postgres", 1, 1),
            (40, 95, "s3.putObject invoice.pdf", 3, "s3", 1, 1),
        ],
    },
    {
        "name": "GET /api/user/profile",
        "spans": [
            (0, 45, "GET /api/user/profile", 2, "api-gateway", 2, None),
            (3, 40, "get_user_profile", 3, "user-service", 2, 0),
            (5, 35, "SELECT users WHERE id = $1", 3, "postgres", 2, 1),
        ],
    },
    {
        "name": "GET /api/dashboard",
        "spans": [
            (0, 120, "GET /api/dashboard", 2, "api-gateway", 1, None),
            (2, 25, "redis.get session", 3, "redis", 1, 0),
            (30, 80, "fetch_widgets", 3, "dashboard-service", 1, 0),
            (35, 60, "SELECT dashboards JOIN widgets", 3, "postgres", 1, 2),
            (100, 15, "redis.set cache", 3, "redis", 1, 0),
        ],
    },
    {
        "name": "POST /api/events",
        "spans": [
            (0, 25, "POST /api/events", 2, "api-gateway", 1, None),
            (2, 8, "validate_event", 1, "ingestion-service", 1, 0),
            (12, 10, "kafka.produce events", 4, "kafka", 1, 0),
        ],
    },
    {
        "name": "GET /api/feature-flags",
        "spans": [
            (0, 15, "GET /api/feature-flags", 2, "api-gateway", 1, None),
            (1, 5, "redis.get flags:project_123", 3, "redis", 1, 0),
            (7, 6, "evaluate_flags", 1, "feature-flag-service", 1, 0),
        ],
    },
]


def _instantiate_trace(rng: random.Random, template: dict, start: dt.datetime) -> list[dict]:
    """Create a trace from a template at the given start time."""
    trace_id = _random_uuid(rng)
    span_ids = [_random_uuid(rng)[:16] for _ in template["spans"]]
    spans: list[dict] = []

    for i, (offset_ms, duration_ms, name, kind, service, status_code, parent_idx) in enumerate(template["spans"]):
        parent_span_id = span_ids[parent_idx] if parent_idx is not None else ""
        spans.append(
            _span(
                rng,
                trace_id=trace_id,
                span_id=span_ids[i],
                parent_span_id=parent_span_id,
                name=name,
                kind=kind,
                service_name=service,
                status_code=status_code,
                start=start + dt.timedelta(milliseconds=offset_ms),
                duration_ms=duration_ms,
            )
        )

    return spans


def generate_fixture_spans(*, limit: int | None = None) -> list[dict]:
    """Generate realistic fixture spans spread across the last 24 hours.

    Produces ~500 traces (~2500 spans) with diurnal traffic patterns:
    more traffic during business hours, less at night.
    """
    rng = random.Random(42)  # deterministic so IDs are stable across requests
    # Pin to the start of the current hour so trace IDs stay consistent
    now = dt.datetime.now(tz=dt.UTC).replace(minute=0, second=0, microsecond=0)
    spans: list[dict] = []

    # Generate traces spread across the last 24 hours (most recent first)
    for minutes_ago in range(1, 1441):
        hour = (now - dt.timedelta(minutes=minutes_ago)).hour

        # Diurnal pattern: more traffic 8am-8pm, quieter at night
        if 8 <= hour <= 20:
            traces_this_minute = rng.choices([0, 1, 2, 3], weights=[20, 40, 30, 10])[0]
        else:
            traces_this_minute = rng.choices([0, 1], weights=[70, 30])[0]

        for _ in range(traces_this_minute):
            template = rng.choice(_TRACE_TEMPLATES)
            offset_seconds = rng.uniform(0, 60)
            trace_start = now - dt.timedelta(minutes=minutes_ago) + dt.timedelta(seconds=offset_seconds)
            spans.extend(_instantiate_trace(rng, template, trace_start))

    spans.sort(key=lambda s: s["timestamp"], reverse=True)
    if limit is not None:
        spans = spans[:limit]
    return spans


def get_fixture_trace_spans(trace_id: str) -> list[dict]:
    """Return all spans belonging to a specific trace."""
    all_spans = generate_fixture_spans()
    return [s for s in all_spans if s["trace_id"] == trace_id]


def generate_fixture_sparkline(spans: list[dict]) -> list[dict]:
    """Aggregate fixture spans into sparkline buckets by service."""
    bucket_minutes = 15
    counts: Counter[tuple[str, str]] = Counter()

    for span in spans:
        ts = dt.datetime.fromisoformat(span["timestamp"])
        bucket = ts.replace(second=0, microsecond=0, minute=(ts.minute // bucket_minutes) * bucket_minutes)
        counts[(bucket.isoformat(), span["service_name"])] += 1

    results: list[dict] = []
    for (time, service), count in sorted(counts.items()):
        results.append({"time": time, "service": service, "count": count})

    return results
