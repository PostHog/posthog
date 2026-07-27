"""Sample capture for tracked gRPC calls.

Mirrors `common/http/sampling.py` but for protobuf. When the singleton Redis
key `data_imports:grpc_sample_capture` is set, matching gRPC calls are
anonymized (protobuf → scrubbed JSON) and uploaded to object storage under
`warehouse-sources-grpc-samples/{capture_id}/{source_type}/{seq}.json`.

Operator workflow:

1. `python manage.py warehouse_sources_capture_grpc_samples ...` writes the
   config + TTL into Redis.
2. Active syncs see the config (refresh window ~30s) and start writing matching
   samples to S3.
3. After TTL expiry the config disappears; capture stops automatically.

`response_code` in a rule matches the gRPC status class (`ok`, `unavailable`,
`resource_exhausted`, `client_error`, `server_error`, `error`) or the numeric
gRPC status code (0-16). Streaming responses are truncated to the first few
messages and the whole payload is capped to keep S3 objects small.
"""

from __future__ import annotations

import json
import time
import uuid
import logging
import threading
from typing import TYPE_CHECKING, Any

from django.conf import settings

from posthog.redis import get_client
from posthog.storage import object_storage

from products.warehouse_sources.backend.temporal.data_imports.sources.common.grpc.proto_utils import (
    message_to_scrubbed_dict,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sample_scrub import (
    WILDCARD,
    CaptureConfig,
    CaptureRule,
)

if TYPE_CHECKING:
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.grpc.observer import GrpcRequestRecord
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.job_context import JobContext

logger = logging.getLogger(__name__)

CAPTURE_CONFIG_REDIS_KEY = "data_imports:grpc_sample_capture"
CAPTURE_COUNTER_KEY_PREFIX = "data_imports:grpc_sample_capture:counter"
S3_PREFIX = "warehouse-sources-grpc-samples"
CONFIG_CACHE_TTL_SECONDS = 30
MAX_CONFIG_TTL_SECONDS = 24 * 60 * 60
# Number of streamed response messages retained for a captured sample, and the
# byte ceiling for the whole serialized payload. Streaming reads (e.g. BigQuery
# Storage) can return huge volumes; we keep only a small head for fixture use.
MAX_CAPTURED_RESPONSE_MESSAGES = 3
MAX_SAMPLE_BYTES = 256 * 1024


def is_capture_armed() -> bool:
    """Cheap check used by the stream interceptor to decide whether to retain messages."""
    return _load_config() is not None


# In-process cache of the parsed Redis config — separate from the HTTP cache so
# the two key spaces don't collide. Thread-safe because the interceptor runs
# from worker threads in the source iterator pool.
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


def _matches_grpc_status(rule_value: str, status_class: str, status_code_num: int | None) -> bool:
    if rule_value == WILDCARD:
        return True
    if rule_value == status_class:
        return True
    if status_code_num is not None and rule_value == str(status_code_num):
        return True
    return False


def _first_match(
    rules: tuple[CaptureRule, ...],
    *,
    source_type: str,
    status_class: str,
    status_code_num: int | None,
    team_id: int,
    schema_id: str,
) -> tuple[int, CaptureRule] | None:
    for index, rule in enumerate(rules):
        if rule.matches_dimensions(
            source_type=source_type, team_id=team_id, schema_id=schema_id
        ) and _matches_grpc_status(rule.response_code, status_class, status_code_num):
            return index, rule
    return None


def _next_sequence(capture_id: str, source_type: str) -> int:
    """Per-source monotonic sequence — used only to give each S3 key a unique suffix."""
    try:
        client = get_client()
        return int(client.incr(f"{CAPTURE_COUNTER_KEY_PREFIX}:{capture_id}:seq:{source_type}"))
    except Exception:
        return int(uuid.uuid4().int >> 96)


def maybe_capture(
    *,
    request: Any,
    response_messages: list[Any],
    record: GrpcRequestRecord,
    ctx: JobContext,
) -> None:
    """Entry point used by the observer. No-op when no rule matches."""
    config = _load_config()
    if config is None:
        return

    matching = _first_match(
        config.rules,
        source_type=ctx.source_type,
        status_class=record.status_class,
        status_code_num=record.status_code_num,
        team_id=ctx.team_id,
        schema_id=ctx.external_data_schema_id,
    )
    if matching is None:
        return

    rule_index, rule = matching
    if not _try_reserve_slot(config.capture_id, rule_index, rule.limit):
        return

    payload = _build_sample_payload(request=request, response_messages=response_messages, record=record, ctx=ctx)
    sequence = _next_sequence(config.capture_id, ctx.source_type)
    key = _sample_object_key(config.capture_id, ctx.source_type, sequence)
    bucket = settings.OBJECT_STORAGE_BUCKET
    try:
        object_storage.write(key, payload, bucket=bucket)
    except Exception:
        logger.debug("Failed to write gRPC sample to object storage", exc_info=True)


def _build_sample_payload(
    *,
    request: Any,
    response_messages: list[Any],
    record: GrpcRequestRecord,
    ctx: JobContext,
) -> str:
    retained = response_messages[:MAX_CAPTURED_RESPONSE_MESSAGES]
    response_truncated = (record.message_count is not None and record.message_count > len(retained)) or len(
        response_messages
    ) > len(retained)

    sample: dict[str, Any] = {
        "captured_at_unix_ms": int(time.time() * 1000),
        "context": ctx.as_log_fields(),
        "request": {
            "method": record.method,
            "host": record.host,
            "message": message_to_scrubbed_dict(request),
        },
        "response": {
            "status_class": record.status_class,
            "status_code": record.status_code_num,
            "messages": [message_to_scrubbed_dict(m) for m in retained],
            "message_count": record.message_count,
            "truncated": response_truncated,
            "latency_ms": record.latency_ms,
        },
    }

    serialized = json.dumps(sample, default=str)
    if len(serialized.encode("utf-8", errors="ignore")) <= MAX_SAMPLE_BYTES:
        return serialized

    # Over the byte ceiling — drop response message bodies but keep the shape /
    # metadata so the sample is still useful as a fixture skeleton.
    sample["response"]["messages"] = []
    sample["response"]["truncated"] = True
    sample["response"]["dropped_for_size"] = True
    return json.dumps(sample, default=str)
