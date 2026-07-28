"""Meta Ads connector metrics.

Each metric is emitted twice from one ``record_*`` helper: a Prometheus
instrument (auto-scraped by the worker's combined metrics server, feeds Grafana)
and an OTLP twin with the same name and attributes pushed into the PostHog
Metrics product via posthog/otel_metrics.py (no-op unless
OTEL_METRICS_EXPORT_URL/TOKEN are configured). Recording is swallowed by the
factory so telemetry can never fail a sync.
"""

from prometheus_client import Counter

from posthog.otel_metrics import OtelInstrumentFactory

_otel = OtelInstrumentFactory("meta-ads")

# Meta's `error.code` values the connector explicitly classifies. Anything else
# is bucketed by `_code_label` so a Meta-side change cannot grow the label set
# without bound.
# https://developers.facebook.com/docs/graph-api/guides/error-handling
_KNOWN_ERROR_CODES = frozenset({1, 2, 4, 10, 17, 32, 100, 102, 190, 613, 3018})

# Insights-endpoint subcodes from Meta's error table, plus 99 ("unknown") which
# their generic Graph API errors carry. Same bucketing rationale as the codes
# above.
# https://developers.facebook.com/docs/marketing-api/insights/error-codes
_KNOWN_ERROR_SUBCODES = frozenset(
    {99, 459, 460, 1504018, 1504022, 1504033, 1504038, 1504039, 1504041, 1504042, 1504043, 1504044, 1504045, 3191001}
)

# What recovery the connector attempted for a failure that reached its terminal
# raise. `transient_retry_exhausted` is the misclassification signal: an error we
# treat as a momentary blip that survives every unchanged retry is, by
# definition, not momentary. `unclassified` means no recovery path matched.
DISPOSITION_AUTH = "auth"
DISPOSITION_RATE_LIMIT = "rate_limit"
DISPOSITION_SHRINK = "shrink"
DISPOSITION_SHRINK_EXHAUSTED = "shrink_exhausted"
DISPOSITION_TRANSIENT_EXHAUSTED = "transient_retry_exhausted"
DISPOSITION_UNCLASSIFIED = "unclassified"

FALLBACK_CHUNK_DAYS = "chunk_days"
FALLBACK_PAGE_LIMIT = "page_limit"

META_ADS_API_ERRORS = Counter(
    "meta_ads_api_errors_total",
    "Graph API failures at their terminal raise, by Meta error code and the recovery the connector attempted",
    ["code", "subcode", "disposition"],
)

META_ADS_ADAPTIVE_FALLBACK = Counter(
    "meta_ads_adaptive_fallback_total",
    "Rungs taken on the adaptive fallback ladders that shrink an over-heavy insights request",
    ["dimension", "from_size", "to_size"],
)


def _code_label(code: int | None) -> str:
    if code is None:
        return "none"
    if code in _KNOWN_ERROR_CODES:
        return str(code)
    # Collapse the 200-299 permission range rather than emit a series per code.
    if 200 <= code < 300:
        return "permission_2xx"
    return "other"


def _subcode_label(subcode: object) -> str:
    if isinstance(subcode, int) and subcode in _KNOWN_ERROR_SUBCODES:
        return str(subcode)
    return "none" if subcode is None else "other"


def record_api_error(code: int | None, subcode: object, disposition: str) -> None:
    labels = {"code": _code_label(code), "subcode": _subcode_label(subcode), "disposition": disposition}
    META_ADS_API_ERRORS.labels(**labels).inc()
    _otel.record_counter_twin(META_ADS_API_ERRORS, 1, labels)


def record_adaptive_fallback(dimension: str, from_size: int, to_size: int) -> None:
    labels = {"dimension": dimension, "from_size": str(from_size), "to_size": str(to_size)}
    META_ADS_ADAPTIVE_FALLBACK.labels(**labels).inc()
    _otel.record_counter_twin(META_ADS_ADAPTIVE_FALLBACK, 1, labels)
