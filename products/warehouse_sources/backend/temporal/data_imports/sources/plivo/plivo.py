import dataclasses
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

from dateutil import parser as dateutil_parser

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import HttpBasicAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.plivo.settings import (
    MAX_QUERY_RANGE_DAYS,
    PAGE_SIZE,
    PLIVO_BASE_URL,
    PLIVO_ENDPOINTS,
    RETENTION_DAYS,
    PlivoEndpointConfig,
)


@dataclasses.dataclass
class PlivoResumeConfig:
    # ISO start/end of the <=30-day window being paged. Both None for non-windowed endpoints.
    # window_end pins the resumed window's upper bound so re-deriving it against a later "now"
    # can't shift offsets mid-window.
    window_start: str | None = None
    window_end: str | None = None
    # Next page offset within the current window/listing.
    offset: int = 0


def _coerce_datetime(value: Any) -> datetime:
    """Coerce an incremental cursor / resume value into an aware UTC datetime."""
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    parsed = dateutil_parser.parse(str(value))
    return parsed.astimezone(UTC) if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _format_filter_value(dt: datetime) -> str:
    """Plivo time filters take `yyyy-MM-dd HH:mm:ss` in UTC."""
    return dt.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")


def _build_windows(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """Contiguous (start, end] slices of at most MAX_QUERY_RANGE_DAYS covering [start, end]."""
    windows: list[tuple[datetime, datetime]] = []
    window_start = start
    step = timedelta(days=MAX_QUERY_RANGE_DAYS)
    while window_start < end:
        window_end = min(window_start + step, end)
        windows.append((window_start, window_end))
        window_start = window_end
    return windows


def _normalize_row(row: dict[str, Any], config: PlivoEndpointConfig) -> dict[str, Any]:
    """Parse Plivo's timestamp strings into datetimes so incremental watermarks and datetime
    partitioning operate on real timestamps rather than lexicographic strings."""
    for field_name in config.datetime_fields:
        value = row.get(field_name)
        if isinstance(value, str) and value:
            try:
                row[field_name] = dateutil_parser.parse(value)
            except (ValueError, OverflowError):
                pass  # leave the raw string for a value we can't parse
    return row


def _make_client(auth_id: str, auth_token: str) -> RESTClient:
    return RESTClient(base_url=PLIVO_BASE_URL, auth=HttpBasicAuth(auth_id, auth_token))


def _paginate(
    client: RESTClient,
    path: str,
    params: dict[str, Any],
    config: PlivoEndpointConfig,
    initial_offset: int,
    on_checkpoint: Callable[[int | None], None],
) -> Iterator[list[dict[str, Any]]]:
    """Walk one offset-paginated listing, yielding normalized row pages.

    `on_checkpoint(offset | None)` fires after each yielded page has been consumed downstream —
    with the next page's offset while more pages remain, then `None` once the listing is done.
    """
    paginator = OffsetPaginator(
        limit=PAGE_SIZE,
        offset=initial_offset,
        total_path="meta.total_count",
    )

    def resume_hook(state: Optional[dict[str, Any]]) -> None:
        on_checkpoint(int(state["offset"]) if state else None)

    for page in client.paginate(
        path=path,
        params=params,
        paginator=paginator,
        data_selector="objects",
        resume_hook=resume_hook,
    ):
        yield [_normalize_row(row, config) for row in page]


def get_rows(
    auth_id: str,
    auth_token: str,
    endpoint: str,
    resumable_source_manager: ResumableSourceManager[PlivoResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = PLIVO_ENDPOINTS[endpoint]
    client = _make_client(auth_id, auth_token)
    path = f"Account/{auth_id}/{config.path}"
    now = datetime.now(UTC)

    filter_field = incremental_field if should_use_incremental_field and incremental_field else config.time_filter_field

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if not config.windowed:
        params: dict[str, Any] = {}
        if should_use_incremental_field and db_incremental_field_last_value is not None and filter_field:
            params[f"{filter_field}__gt"] = _format_filter_value(_coerce_datetime(db_incremental_field_last_value))

        def checkpoint(offset: int | None) -> None:
            # Save AFTER each yielded page so a crash re-yields the last page (merge dedupes on
            # the primary key). Nothing to checkpoint once the listing is exhausted.
            if offset is not None:
                resumable_source_manager.save_state(PlivoResumeConfig(offset=offset))

        yield from _paginate(client, path, params, config, resume.offset if resume else 0, checkpoint)
        return

    # Windowed endpoints (MDRs/CDRs): Plivo rejects list requests spanning more than 30 days and
    # only retains 90 days, so fetch contiguous <=30-day windows from the effective start to now.
    if resume is not None and resume.window_start:
        start = _coerce_datetime(resume.window_start)
    elif should_use_incremental_field and db_incremental_field_last_value is not None:
        # Records older than the retention window are gone server-side; don't request them.
        start = max(_coerce_datetime(db_incremental_field_last_value), now - timedelta(days=RETENTION_DAYS))
    else:
        start = now - timedelta(days=RETENTION_DAYS)

    windows = _build_windows(start, now)
    if resume is not None and resume.window_end and windows:
        # Pin the resumed window's saved upper bound so its page offsets stay aligned.
        resumed_end = _coerce_datetime(resume.window_end)
        windows[0] = (windows[0][0], resumed_end)
        windows[1:] = _build_windows(resumed_end, now)

    for index, (window_start, window_end) in enumerate(windows):
        params = {
            f"{filter_field}__gt": _format_filter_value(window_start),
            f"{filter_field}__lte": _format_filter_value(window_end),
        }
        # The saved page offset only applies to the window the crashed attempt was mid-way through.
        initial_offset = resume.offset if (index == 0 and resume is not None and resume.window_start) else 0

        window_start_iso = window_start.isoformat()
        window_end_iso = window_end.isoformat()

        def window_checkpoint(
            offset: int | None, window_start_iso: str = window_start_iso, window_end_iso: str = window_end_iso
        ) -> None:
            if offset is not None:
                resumable_source_manager.save_state(
                    PlivoResumeConfig(window_start=window_start_iso, window_end=window_end_iso, offset=offset)
                )
            else:
                # Window exhausted: point the checkpoint at the next window's start so a retry
                # skips everything already synced. For the final window this leaves a checkpoint
                # at "now", so a late retry only fetches the gap since this run.
                resumable_source_manager.save_state(PlivoResumeConfig(window_start=window_end_iso, offset=0))

        yield from _paginate(client, path, params, config, initial_offset, window_checkpoint)


def plivo_source(
    auth_id: str,
    auth_token: str,
    endpoint: str,
    resumable_source_manager: ResumableSourceManager[PlivoResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = PLIVO_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            auth_id=auth_id,
            auth_token=auth_token,
            endpoint=endpoint,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=config.primary_keys,
        # Plivo lists return newest-first within a listing/window and expose no sort param, so the
        # stream is not globally ascending. "desc" makes the pipeline persist the incremental
        # watermark only after a fully successful run instead of checkpointing per batch.
        sort_mode="desc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(auth_id: str, auth_token: str) -> bool:
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(auth_token,)),
        f"{PLIVO_BASE_URL}/Account/{auth_id}/",
        auth=HttpBasicAuth(auth_id, auth_token),
    )
    return ok
