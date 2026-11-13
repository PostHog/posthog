from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from django.utils import timezone

import structlog

from posthog.dataclasses import frozen
from posthog.models import Team

from products.signals.backend.contracts import HOGQL_FILTER_KEY
from products.signals.backend.emission.fetchers.data_warehouse import (
    DRAIN_WINDOW_KEY,
    MALFORMED_COUNT_KEY,
    RESUME_AFTER_ID_KEY,
    WINDOW_CAPPED_KEY,
    WINDOW_END_ID_KEY,
    WINDOW_END_KEY,
)
from products.signals.backend.emission.registry import SignalSourceTableConfig
from products.signals.backend.source_filters import (
    FilterStateKey,
    pending_window,
    record_fetch_failure,
    record_window_processed,
)

logger = structlog.get_logger(__name__)


@frozen
class FetchedWindow:
    records: list[dict[str, Any]]
    key: FilterStateKey
    # The lower bound the fetcher read from. None means the fetcher's own first-sync lookback.
    window_start: datetime | None
    malformed_count: int
    tracked: bool
    # Where a capped batch ended. The next fetch resumes there instead of the stored window clearing.
    resume_from: datetime | None
    resume_after_id: str | None


def replay_window_start(
    *, last_synced_at: datetime | None, pending: datetime | None, first_sync_start: datetime | None
) -> datetime | None:
    """The lower bound of the fetch window. None keeps the fetcher's first-sync lookback."""
    if pending is None:
        return last_synced_at or first_sync_start
    return min(pending, last_synced_at or first_sync_start or pending)


def fetch_records(
    team: Team, config: SignalSourceTableConfig, context: dict[str, Any], *, schema_id: UUID
) -> FetchedWindow:
    """Run the source's fetcher, starting from any window a filtered fetch failed to read.

    Call `complete_fetch` once the records are processed. Until then the stored window stays, so a failure
    after the fetch reads it again.
    """
    key = FilterStateKey(
        team_id=team.id, source_product=config.source_product, source_type=config.source_type, schema_id=schema_id
    )
    raw_last_synced_at: str | None = context.get("last_synced_at")
    last_synced_at = datetime.fromisoformat(raw_last_synced_at) if raw_last_synced_at else None
    source_config = context.get("source_config")
    filtered = isinstance(source_config, dict) and HOGQL_FILTER_KEY in source_config
    stored = pending_window(key)
    pending = stored.start if stored is not None else None
    tracked = filtered or pending is not None
    # A tracked first sync reads from a bound taken now, so a failure records the window it tried, not a later one.
    first_sync_start = (
        timezone.now() - timedelta(days=config.first_sync_lookback_days) if tracked and last_synced_at is None else None
    )
    window_start = replay_window_start(
        last_synced_at=last_synced_at, pending=pending, first_sync_start=first_sync_start
    )
    context = {
        **context,
        "last_synced_at": window_start.isoformat() if window_start is not None else None,
        DRAIN_WINDOW_KEY: tracked,
        # Resume after the exact row a capped batch stopped at, when this fetch starts at that position.
        RESUME_AFTER_ID_KEY: (stored.after_id or None) if stored is not None and window_start == stored.start else None,
    }
    if pending is not None:
        logger.info(
            "Replaying a window an earlier fetch failed to read",
            pending_window_start=pending.isoformat(),
            signal_source_product=config.source_product,
            signal_source_type=config.source_type,
            signals_type="data-import-signals",
        )
    try:
        records = config.record_fetcher(team, config, context)
    except Exception as error:
        if filtered and window_start is not None:
            try:
                record_fetch_failure(key, window_start=window_start, error=error)
            except Exception:
                logger.exception(
                    "Could not record a failed fetch window",
                    signal_source_product=config.source_product,
                    signal_source_type=config.source_type,
                    signals_type="data-import-signals",
                )
        raise
    capped = bool(context.get(WINDOW_CAPPED_KEY))
    return FetchedWindow(
        records=records,
        key=key,
        window_start=window_start,
        malformed_count=context.get(MALFORMED_COUNT_KEY, 0),
        resume_from=_aware(context.get(WINDOW_END_KEY)) if capped else None,
        resume_after_id=context.get(WINDOW_END_ID_KEY) if capped else None,
        tracked=tracked,
    )


def complete_fetch(fetched: FetchedWindow) -> None:
    if fetched.tracked:
        record_window_processed(
            fetched.key,
            window_start=fetched.window_start,
            malformed_count=fetched.malformed_count,
            resume_from=fetched.resume_from,
            resume_after_id=fetched.resume_after_id,
        )


def _aware(value: object) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
