"""Sample capture for tracked HTTP requests.

When the singleton Redis key `data_imports:http_sample_capture` is set,
matching outbound requests are anonymized and uploaded to object storage
under `warehouse-sources-http-samples/{capture_id}/{source_type}/{seq}.json`.

Operator workflow:

1. `python manage.py warehouse_sources_capture_http_samples ...` writes the
   config + TTL into Redis.
2. Active syncs see the config (refresh window ~30s) and start writing
   matching samples to S3.
3. After TTL expiry the config disappears; capture stops automatically.
4. Operator pulls the samples down and uses them as test fixtures.

Goals:

- Zero hot-path cost when capture is disabled (one Redis GET every 30s
  per worker, served from an in-process cache).
- Filtering on `(source_type, response_code, team_id, schema_id)` with
  `*` defaults.
- Per-rule capture limit enforced via Redis `INCR` so multiple workers
  share the same counter.
- Response values pass through `scrubadub`; auth-bearing JSON keys
  (`access_token`, `client_secret`, …) are dropped wholesale by name.
  Known auth headers are dropped wholesale; auth-bearing query params
  are scrubbed by `url_utils.scrub_url`.
"""

from __future__ import annotations

import json
import time
import uuid
import logging
import threading
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qsl, urlencode

from django.conf import settings

from posthog.redis import get_client
from posthog.storage import object_storage

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.context import JobContext
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.url_utils import (
    _REDACT_PARAM_NAMES,
    redact_literal_values,
    scrub_url,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sample_scrub import (
    REDACT_FIELD_NAMES,
    CaptureConfig,
    CaptureRule,
    scrub_string as _scrub_string,
    scrub_value as _scrub_value,
)

if TYPE_CHECKING:
    from requests import PreparedRequest, Response

    from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.observer import RequestRecord

logger = logging.getLogger(__name__)

CAPTURE_CONFIG_REDIS_KEY = "data_imports:http_sample_capture"
CAPTURE_COUNTER_KEY_PREFIX = "data_imports:http_sample_capture:counter"
S3_PREFIX = "warehouse-sources-http-samples"
CONFIG_CACHE_TTL_SECONDS = 30
MAX_CONFIG_TTL_SECONDS = 24 * 60 * 60

_REDACTED_HEADER = "REDACTED"
_REDACTED_FORM_VALUE = "REDACTED"
_AUTH_HEADER_NAMES: frozenset[str] = frozenset(
    {
        "authorization",
        "x-api-key",
        "x-sn-apikey",
        "x-ck-api-key",
        "x-auth-token",
        "x-metabase-session",
        "ob-token-v1",
        "cookie",
        "set-cookie",
        "proxy-authorization",
    }
)

__all__ = ["CaptureConfig", "CaptureRule", "maybe_capture"]


# In-process cache of the parsed Redis config. Thread-safe because the
# tracked transport is invoked from worker threads in the source iterator
# pool (see pipeline.py). The cache is intentionally per-process —
# refreshing every 30s in N workers is cheap.
_CONFIG_LOCK = threading.Lock()
_cached_config: CaptureConfig | None = None
_cached_config_fetched_at: float = 0.0


def _now() -> float:
    return time.monotonic()


def _load_config() -> CaptureConfig | None:
    global _cached_config, _cached_config_fetched_at

    with _CONFIG_LOCK:
        if _now() - _cached_config_fetched_at < CONFIG_CACHE_TTL_SECONDS:
            return _cached_config

        try:
            raw = get_client().get(CAPTURE_CONFIG_REDIS_KEY)
        except Exception:
            logger.debug("Capture-config Redis fetch failed", exc_info=True)
            # Keep the previously-cached value if any — beats hammering on errors.
            _cached_config_fetched_at = _now()
            return _cached_config

        _cached_config_fetched_at = _now()
        if raw is None:
            _cached_config = None
            return None

        config = CaptureConfig.from_json(raw)
        _cached_config = config
        return config


def _reset_cache_for_tests() -> None:
    """Test hook — clears the in-process cache."""
    global _cached_config, _cached_config_fetched_at
    with _CONFIG_LOCK:
        _cached_config = None
        _cached_config_fetched_at = 0.0


def _counter_key(capture_id: str, rule_index: int) -> str:
    return f"{CAPTURE_COUNTER_KEY_PREFIX}:{capture_id}:{rule_index}"


def _try_reserve_slot(capture_id: str, rule_index: int, limit: int) -> bool:
    """Atomically claim a sample slot. Returns True if the sample should be kept."""
    if limit <= 0:
        return False
    try:
        client = get_client()
        key = _counter_key(capture_id, rule_index)
        new_value = client.incr(key)
        try:
            ttl = client.ttl(CAPTURE_CONFIG_REDIS_KEY)
            client.expire(key, max(int(ttl) if isinstance(ttl, int) and ttl > 0 else MAX_CONFIG_TTL_SECONDS, 60))
        except Exception:
            logger.debug("Failed to set TTL on capture counter", exc_info=True)
        return int(new_value) <= limit
    except Exception:
        logger.debug("Failed to reserve sample slot", exc_info=True)
        return False


def _sample_object_key(capture_id: str, source_type: str, sequence: int) -> str:
    return f"{S3_PREFIX}/{capture_id}/{source_type}/{sequence:06d}.json"


def maybe_capture(
    *,
    request: PreparedRequest,
    response: Response | None,
    record: RequestRecord,
    ctx: JobContext,
    redact_values: tuple[str, ...] = (),
) -> None:
    """Entry point used by the observer. No-op when no rule matches.

    `redact_values` are credential strings masked from the captured sample on
    top of the name-based header/URL/body scrubbers.
    """
    if response is None:
        return

    config = _load_config()
    if config is None:
        return

    matching = _first_match(
        config.rules,
        source_type=ctx.source_type,
        status_code=record.status_code,
        team_id=ctx.team_id,
        schema_id=ctx.external_data_schema_id,
    )
    if matching is None:
        return

    rule_index, rule = matching
    if not _try_reserve_slot(config.capture_id, rule_index, rule.limit):
        return

    payload = _build_sample_payload(request=request, response=response, record=record, ctx=ctx)
    if redact_values:
        # Final value-based pass over the fully serialized sample: catches the
        # credential wherever it landed (query param, custom header, cookie,
        # body) regardless of the name-based scrubbers above.
        payload = redact_literal_values(payload, redact_values)
    sequence = _next_sequence(config.capture_id, ctx.source_type)
    key = _sample_object_key(config.capture_id, ctx.source_type, sequence)
    bucket = settings.OBJECT_STORAGE_BUCKET
    try:
        object_storage.write(key, payload, bucket=bucket)
    except Exception:
        logger.debug("Failed to write HTTP sample to object storage", exc_info=True)


def _first_match(
    rules: tuple[CaptureRule, ...],
    *,
    source_type: str,
    status_code: int | None,
    team_id: int,
    schema_id: str,
) -> tuple[int, CaptureRule] | None:
    for index, rule in enumerate(rules):
        if rule.matches(
            source_type=source_type,
            status_code=status_code,
            team_id=team_id,
            schema_id=schema_id,
        ):
            return index, rule
    return None


def _next_sequence(capture_id: str, source_type: str) -> int:
    """Per-source monotonic sequence — used only to give each S3 key a unique suffix."""
    try:
        client = get_client()
        return int(client.incr(f"{CAPTURE_COUNTER_KEY_PREFIX}:{capture_id}:seq:{source_type}"))
    except Exception:
        # Fall back to a random tail; we only need uniqueness, not ordering.
        return int(uuid.uuid4().int >> 96)


def _build_sample_payload(
    *,
    request: PreparedRequest,
    response: Response,
    record: RequestRecord,
    ctx: JobContext,
) -> str:
    request_headers = _scrub_headers(dict(request.headers or {}))
    response_headers = _scrub_headers(dict(response.headers or {}))
    request_body = _scrub_body(request.body)
    response_body = _scrub_body(_safe_response_text(response))

    sample = {
        "captured_at_unix_ms": int(time.time() * 1000),
        "context": ctx.as_log_fields(),
        "request": {
            "method": (request.method or "GET").upper(),
            "url": scrub_url(request.url or ""),
            "headers": request_headers,
            "body": request_body,
        },
        "response": {
            "status": response.status_code,
            "headers": response_headers,
            "body": response_body,
            "elapsed_ms": record.latency_ms,
        },
    }
    return json.dumps(sample, default=str)


def _safe_response_text(response: Response) -> str | None:
    try:
        return response.text
    except Exception:
        return None


def _scrub_headers(headers: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for name, value in headers.items():
        if name.lower() in _AUTH_HEADER_NAMES:
            cleaned[name] = _REDACTED_HEADER
            continue
        cleaned[name] = _scrub_string(str(value))
    return cleaned


def _scrub_body(body: Any) -> Any:
    if body is None:
        return None
    if isinstance(body, bytes | bytearray):
        try:
            body = body.decode("utf-8")
        except UnicodeDecodeError:
            return f"<binary {len(body)} bytes>"
    if isinstance(body, str):
        parsed = _try_json(body)
        if parsed is not None:
            # Drop auth-bearing keys (e.g. an OAuth token-exchange response's
            # `access_token`) before scrubadub, which can't recognise opaque
            # tokens by value alone.
            return _scrub_value(_redact_field_keys(parsed))
        # OAuth token-exchange / refresh / authorization-code flows post
        # `application/x-www-form-urlencoded` bodies like
        # `grant_type=refresh_token&client_id=...&client_secret=...&refresh_token=...`.
        # scrubadub treats those as opaque text and won't recognise OAuth
        # secrets, so we detect form-shaped bodies up front and redact by
        # key name against the same denylist used for URL query params.
        form = _try_form_urlencoded(body)
        if form is not None:
            return form
        return _scrub_string(body)
    return _scrub_value(body)


def _redact_field_keys(value: Any) -> Any:
    """Recursively replace auth-bearing dict values (matched by key name against
    `REDACT_FIELD_NAMES`) with a placeholder — mirrors the gRPC sample path."""
    if isinstance(value, dict):
        return {
            k: (_REDACTED_FORM_VALUE if str(k).lower() in REDACT_FIELD_NAMES else _redact_field_keys(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact_field_keys(item) for item in value]
    return value


def _try_json(text: str) -> Any | None:
    text_stripped = text.lstrip()
    if not text_stripped or text_stripped[0] not in "{[":
        return None
    try:
        return json.loads(text)
    except (ValueError, json.JSONDecodeError):
        return None


def _try_form_urlencoded(text: str) -> str | None:
    """Detect `application/x-www-form-urlencoded` bodies and scrub auth params.

    Returns the scrubbed body as a string, or `None` if the input doesn't
    look like a form-encoded payload (in which case the caller falls back
    to scrubadub on the raw text).
    """
    stripped = text.strip()
    if not stripped or "=" not in stripped or "\n" in stripped or " " in stripped.split("=", 1)[0]:
        return None
    try:
        pairs = parse_qsl(stripped, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        return None
    # Require at least one key=value pair to call this a form body.
    if not pairs:
        return None
    scrubbed = [
        (name, _REDACTED_FORM_VALUE if name.lower() in _REDACT_PARAM_NAMES else _scrub_string(value))
        for name, value in pairs
    ]
    return urlencode(scrubbed, doseq=False)
