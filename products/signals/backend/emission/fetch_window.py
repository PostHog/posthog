from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone

import structlog

from posthog.models import Team

from products.signals.backend.contracts import HOGQL_FILTER_KEY
from products.signals.backend.emission.fetchers.data_warehouse import MALFORMED_COUNT_KEY
from products.signals.backend.emission.registry import SignalSourceTableConfig
from products.signals.backend.source_filters import pending_window_start, record_fetch_failure, record_fetch_success

logger = structlog.get_logger(__name__)


def replay_window_start(
    *, last_synced_at: datetime | None, pending: datetime | None, first_sync_start: Callable[[], datetime]
) -> datetime | None:
    """The lower bound of the fetch window. None keeps the fetcher's first-sync lookback."""
    if pending is None:
        return last_synced_at
    return min(pending, last_synced_at or first_sync_start())


def fetch_records(team: Team, config: SignalSourceTableConfig, context: dict[str, Any]) -> list[dict[str, Any]]:
    """Run the source's fetcher, starting from any window a filtered fetch failed to read."""
    raw_last_synced_at: str | None = context.get("last_synced_at")
    last_synced_at = datetime.fromisoformat(raw_last_synced_at) if raw_last_synced_at else None

    def first_sync_start() -> datetime:
        return timezone.now() - timedelta(days=config.first_sync_lookback_days)

    pending = pending_window_start(
        team_id=team.id, source_product=config.source_product, source_type=config.source_type
    )
    window_start = replay_window_start(
        last_synced_at=last_synced_at, pending=pending, first_sync_start=first_sync_start
    )
    context = {**context, "last_synced_at": window_start.isoformat() if window_start is not None else None}
    if pending is not None:
        logger.info(
            "Replaying a window an earlier fetch failed to read",
            pending_window_start=pending.isoformat(),
            signal_source_product=config.source_product,
            signal_source_type=config.source_type,
            signals_type="data-import-signals",
        )
    source_config = context.get("source_config")
    filtered = isinstance(source_config, dict) and HOGQL_FILTER_KEY in source_config
    try:
        records = config.record_fetcher(team, config, context)
    except Exception as error:
        if filtered:
            try:
                record_fetch_failure(
                    team_id=team.id,
                    source_product=config.source_product,
                    source_type=config.source_type,
                    window_start=window_start or first_sync_start(),
                    error=error,
                )
            except Exception:
                logger.exception(
                    "Could not record a failed fetch window",
                    signal_source_product=config.source_product,
                    signal_source_type=config.source_type,
                    signals_type="data-import-signals",
                )
        raise
    if filtered or pending is not None:
        record_fetch_success(
            team_id=team.id,
            source_product=config.source_product,
            source_type=config.source_type,
            malformed_count=context.get(MALFORMED_COUNT_KEY, 0),
        )
    return records
