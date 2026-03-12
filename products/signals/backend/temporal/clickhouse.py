import random
import asyncio
from typing import Any

import structlog
from asgiref.sync import sync_to_async

from posthog.hogql.query import execute_hogql_query

from posthog.errors import CH_TRANSIENT_ERRORS
from posthog.exceptions import ClickHouseAtCapacity
from posthog.models import Team

# Errors worth retrying
RETRIABLE_ERRORS = (ClickHouseAtCapacity, *CH_TRANSIENT_ERRORS)

logger = structlog.get_logger(__name__)

MAX_RETRIES = 3
BASE_DELAY_SECONDS = 10.0


async def execute_hogql_query_with_retry(
    *,
    query_type: str,
    query: str,
    team: Team,
    placeholders: dict[str, Any] | None = None,
    max_retries: int = MAX_RETRIES,
    base_delay: float = BASE_DELAY_SECONDS,
):
    """Execute a HogQL query, retrying on transient ClickHouse errors with exponential backoff and jitter."""
    for attempt in range(max_retries + 1):
        try:
            return await sync_to_async(execute_hogql_query, thread_sensitive=False)(
                query_type=query_type,
                query=query,
                team=team,
                placeholders=placeholders or {},
            )
        except RETRIABLE_ERRORS as e:
            if attempt >= max_retries:
                raise
            # Exponential backoff with full jitter to avoid thundering herd
            max_delay = base_delay * (2**attempt)
            delay = random.uniform(max_delay / 2, max_delay)
            logger.warning(
                "Transient ClickHouse error, retrying",
                error=str(e),
                delay=round(delay, 1),
                attempt=attempt + 1,
                max_retries=max_retries,
                query_type=query_type,
            )
            await asyncio.sleep(delay)
        # Fail loudly on unexpected errors
