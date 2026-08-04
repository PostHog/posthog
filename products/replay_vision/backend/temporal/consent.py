"""Resilient wrapper around the fail-closed AI-consent check for Temporal activities.

Consent is re-checked at each egress boundary under a provider-facing RetryPolicy whose backoff is
tuned to outlast the Gemini quota window (`_UPLOAD_RETRY` / `_PROVIDER_CALL_RETRY` in workflow.py) —
a handful of long, expensive attempts. A Postgres pool blip on this read must not spend one of those,
so a couple of quick retries are absorbed here first.
"""

import asyncio

import structlog
from asgiref.sync import sync_to_async

from products.replay_vision.backend.consent import is_ai_data_processing_approved
from products.replay_vision.backend.temporal.db_errors import is_transient_db_error

logger = structlog.get_logger(__name__)

_TRANSIENT_RETRY_ATTEMPTS = 3
_TRANSIENT_RETRY_DELAY_SECONDS = 1.0


async def is_ai_data_processing_approved_resilient(team_id: int) -> bool:
    """Same fail-closed consent check, absorbing a few short retries on a transient DB error."""
    for attempt in range(1, _TRANSIENT_RETRY_ATTEMPTS + 1):
        try:
            return await sync_to_async(is_ai_data_processing_approved)(team_id)
        except Exception as e:
            if attempt == _TRANSIENT_RETRY_ATTEMPTS or not is_transient_db_error(e):
                raise
            logger.warning(
                "replay_vision.consent_check.transient_db_retry", team_id=team_id, attempt=attempt, error=str(e)
            )
            await asyncio.sleep(_TRANSIENT_RETRY_DELAY_SECONDS)
    raise AssertionError("unreachable")  # the loop above always returns or raises


__all__ = ["is_ai_data_processing_approved_resilient"]
