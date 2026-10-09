import json
import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import UTC, datetime

import structlog
from asgiref.sync import sync_to_async

from posthog.storage import object_storage

from products.signals.backend.temporal import llm
from products.signals.backend.temporal.types import EmitSignalInputs

logger = structlog.get_logger(__name__)

MAX_REFUSAL_ATTEMPTS = 3


def refusal_review_key(signal: EmitSignalInputs) -> str:
    fingerprint = hashlib.sha256(json.dumps(asdict(signal), sort_keys=True).encode()).hexdigest()
    return f"signals/refusal_review/{signal.team_id}/{fingerprint}.json"


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
