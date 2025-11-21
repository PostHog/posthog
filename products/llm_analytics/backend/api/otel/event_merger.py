"""
Event merger for combining OTEL log and trace events using Redis.

V2 instrumentation sends traces (with metadata) and logs (with message content)
as separate HTTP requests. The order varies - sometimes traces first, sometimes logs first.

This module uses Redis to cache and merge them bidirectionally with NO BLOCKING:
- First arrival (trace OR log): Cache in Redis, don't send
- Second arrival (log OR trace): Find cached partner, merge, and send

This eliminates the thread starvation problem of blocking with time.sleep().
"""

import json
import logging
from typing import Any, Optional

from posthog.redis import get_client

logger = logging.getLogger(__name__)

_CACHE_TTL = 60  # seconds - Redis will auto-expire after this


def cache_and_merge_properties(
    trace_id: str, span_id: str, properties: dict[str, Any], is_trace: bool = True
) -> Optional[dict[str, Any]]:
    """
    Cache properties and merge with any existing cached properties for the same span.

    Uses separate cache keys for traces and logs to properly accumulate multiple log events:
    - Trace cache: otel_merge:trace:{trace_id}:{span_id}
    - Logs cache: otel_merge:logs:{trace_id}:{span_id}

    Flow:
    1. Logs accumulate in logs cache (multiple logs merge together)
    2. When trace arrives, merge all accumulated logs with trace and send
    3. When log arrives after trace, merge immediately and send

    Args:
        trace_id: Trace ID
        span_id: Span ID
        properties: Properties dict to cache/merge
        is_trace: True if trace properties, False if log properties

    Returns:
        - None if waiting for more data (cached, not sent)
        - Merged properties if ready to send (send to capture)
    """
    redis_client = get_client()
    trace_cache_key = f"otel_merge:trace:{trace_id}:{span_id}"
    logs_cache_key = f"otel_merge:logs:{trace_id}:{span_id}"

    try:
        if is_trace:
            # Trace arriving - check if logs are already cached
            logs_json = redis_client.get(logs_cache_key)

            if logs_json:
                # Logs already cached - merge and send
                logs_properties = json.loads(logs_json)
                merged = {**logs_properties, **properties}  # Trace props override

                # Clean up logs cache
                redis_client.delete(logs_cache_key)

                logger.info("event_merger_success: Merged trace+logs", extra={"trace_id": trace_id, "span_id": span_id})

                return merged
            else:
                # No logs yet - cache trace
                redis_client.setex(trace_cache_key, _CACHE_TTL, json.dumps(properties))

                logger.info(
                    "event_merger_cache: Cached trace properties", extra={"trace_id": trace_id, "span_id": span_id}
                )

                return None
        else:
            # Log arriving - accumulate with other logs first
            logs_json = redis_client.get(logs_cache_key)

            if logs_json:
                # Another log already cached - accumulate
                existing_logs = json.loads(logs_json)
                merged_logs = {**existing_logs, **properties}  # Later log props override

                # Re-cache accumulated logs
                redis_client.setex(logs_cache_key, _CACHE_TTL, json.dumps(merged_logs))

                logger.info(
                    "event_merger_accumulate: Accumulated log properties",
                    extra={"trace_id": trace_id, "span_id": span_id},
                )

                # Check if trace is ready
                trace_json = redis_client.get(trace_cache_key)
                if trace_json:
                    # Trace is ready - merge and send
                    trace_properties = json.loads(trace_json)
                    final_merged = {**merged_logs, **trace_properties}  # Trace props override

                    # Clean up both caches
                    redis_client.delete(logs_cache_key)
                    redis_client.delete(trace_cache_key)

                    logger.info(
                        "event_merger_success: Merged accumulated logs+trace",
                        extra={"trace_id": trace_id, "span_id": span_id},
                    )

                    return final_merged

                # Trace not ready yet - wait for it
                return None
            else:
                # First log - check if trace is already cached
                trace_json = redis_client.get(trace_cache_key)

                if trace_json:
                    # Trace already cached - merge and send
                    trace_properties = json.loads(trace_json)
                    merged = {**properties, **trace_properties}  # Trace props override

                    # Clean up trace cache
                    redis_client.delete(trace_cache_key)

                    logger.info(
                        "event_merger_success: Merged logs+trace", extra={"trace_id": trace_id, "span_id": span_id}
                    )

                    return merged
                else:
                    # No trace yet - cache this log
                    redis_client.setex(logs_cache_key, _CACHE_TTL, json.dumps(properties))

                    logger.info(
                        "event_merger_cache: Cached log properties", extra={"trace_id": trace_id, "span_id": span_id}
                    )

                    return None

    except Exception as e:
        # Redis error - log and fall back to sending immediately
        logger.exception(
            f"event_merger_error: Redis error during merge, sending immediately",
            extra={
                "trace_id": trace_id,
                "span_id": span_id,
                "error": str(e),
                "is_trace": is_trace,
            },
        )
        # Fallback: send immediately without merging
        return properties
