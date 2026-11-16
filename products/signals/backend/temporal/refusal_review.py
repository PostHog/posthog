import json
import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

import structlog
from asgiref.sync import sync_to_async

from posthog.storage import object_storage

from products.signals.backend.temporal import llm
from products.signals.backend.temporal.types import EmitSignalInputs

logger = structlog.get_logger(__name__)

MAX_REFUSAL_ATTEMPTS = 3
SAFETY_FILTER_EMPTY_RESPONSE_REASON = "safety_filter_empty_response"


def refusal_review_key(signal: Any) -> str:
    if hasattr(signal, "__dataclass_fields__"):
        payload = asdict(signal)
    elif isinstance(signal, dict):
        payload = dict(signal)
    else:
        raise TypeError(f"Unsupported signal type for refusal review key: {type(signal)}")

    payload.pop("signal_id", None)
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    team_id = payload.get("team_id")
    team_slug = str(team_id) if team_id is not None else "unassigned"
    return f"signals/refusal_review/{team_slug}/{fingerprint}.json"


async def preserve_signal_for_review(
    signal: Any,
    *,
    reason: str = SAFETY_FILTER_EMPTY_RESPONSE_REASON,
    attempts: int = 1,
    status: str = "needs_review",
) -> str:
    """Persist a signal payload to object storage for human or judge review."""
    key = refusal_review_key(signal)
    if hasattr(signal, "__dataclass_fields__"):
        payload = asdict(signal)
    elif isinstance(signal, dict):
        payload = dict(signal)
    else:
        payload = {"description": str(signal)}

    team_id = payload.get("team_id")
    await sync_to_async(object_storage.write, thread_sensitive=False)(
        key,
        json.dumps(
            {
                "signal": payload,
                "reason": reason,
                "attempts": attempts,
                "status": status,
                "updated_at": datetime.now(UTC).isoformat(),
            }
        ),
    )
    logger.warning(
        "signals.signal_preserved_for_review",
        team_id=team_id,
        object_key=key,
        reason=reason,
        attempts=attempts,
        status=status,
    )
    return key


async def reingest_held_signal(
    team_id: int,
    *,
    key: str | None = None,
    fingerprint: str | None = None,
) -> bool:
    """Re-ingest a held signal after confirmation that it is benign."""
    if key is None:
        if fingerprint is None:
            raise ValueError("Either key or fingerprint must be provided")
        key = f"signals/refusal_review/{team_id}/{fingerprint}.json"

    raw = await sync_to_async(object_storage.read, thread_sensitive=False)(key, missing_ok=True)
    if raw is None:
        logger.warning("Held signal not found in object storage", key=key, team_id=team_id)
        return False

    payload = json.loads(raw)
    signal_data = payload.get("signal", {})

    # 1. Pre-populate safety verdict cache as safe so the re-emitted signal bypasses empty-reply filter
    from products.signals.backend.temporal.safety_filter import mark_signal_safe_in_cache

    description = signal_data.get("description", "")
    source_product = signal_data.get("source_product")
    source_type = signal_data.get("source_type")

    await mark_signal_safe_in_cache(
        team_id=team_id,
        description=description,
        source_product=source_product,
        source_type=source_type,
    )

    # 2. Delete the held signal record from object storage
    await sync_to_async(object_storage.delete, thread_sensitive=False)(key)

    # 3. Emit the signal into the active pipeline
    from posthog.models import Team
    from products.signals.backend.facade.api import emit_signal

    team = await Team.objects.aget(pk=team_id)
    await emit_signal(
        team=team,
        source_product=source_product or "unknown",
        source_type=source_type or "unknown",
        source_id=signal_data.get("source_id") or "reingested",
        description=description,
        weight=float(signal_data.get("weight") or 0.5),
        extra=signal_data.get("extra"),
    )

    logger.info(
        "Re-ingested held signal into active pipeline",
        team_id=team_id,
        key=key,
        source_product=source_product,
    )
    return True


async def generate_queries_or_preserve_refusal(
    signal: EmitSignalInputs, generate: Callable[[], Awaitable[list[str]]]
) -> list[str] | None:
    key = refusal_review_key(signal)
    raw = await sync_to_async(object_storage.read, thread_sensitive=False)(key, missing_ok=True)
    attempts = int(json.loads(raw)["attempts"]) if raw is not None else 0

    # Persist the count between batch retries: another signal can fail after this one finishes.
    while attempts < MAX_REFUSAL_ATTEMPTS:
        try:
            queries = await generate()
        except llm.LLMRefusalError:
            attempts += 1
            await sync_to_async(object_storage.write, thread_sensitive=False)(
                key,
                json.dumps(
                    {
                        "signal": asdict(signal),
                        "reason": "query_generation_refusal",
                        "attempts": attempts,
                        "status": "needs_review" if attempts == MAX_REFUSAL_ATTEMPTS else "retrying",
                        "updated_at": datetime.now(UTC).isoformat(),
                    }
                ),
            )
        else:
            if attempts:
                await sync_to_async(object_storage.delete, thread_sensitive=False)(key)
            return queries

    logger.warning(
        "signals_grouping.signal_preserved_for_review",
        team_id=signal.team_id,
        object_key=key,
        reason="query_generation_refusal",
        attempts=attempts,
    )
    return None
