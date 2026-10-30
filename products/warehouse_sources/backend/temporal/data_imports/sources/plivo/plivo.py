import json
import hashlib
import dataclasses
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

from dateutil import parser as dateutil_parser

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import HttpBasicAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.config_setup import (
    create_response_hooks,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
    OffsetPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.plivo.settings import (
    MAX_QUERY_RANGE_DAYS,
    MULTI_PARTY_CALL_PARTICIPANTS,
    MULTI_PARTY_CALLS,
    PAGE_SIZE,
    PLIVO_BASE_URL,
    PLIVO_ENDPOINTS,
    RETENTION_DAYS,
    USAGE_BACKFILL_DAYS,
    USAGE_MAX_QUERY_RANGE_DAYS,
    USAGE_METRIC_FIELDS,
    USAGE_PAGE_SIZE,
    USAGE_SUMMARY,
    PlivoEndpointConfig,
)


@dataclasses.dataclass(frozen=True)
class PlivoResumeConfig:
    # ISO start/end of the <=30-day window being paged. Both None for non-windowed endpoints.
    # window_end pins the resumed window's upper bound so re-deriving it against a later "now"
    # can't shift offsets mid-window.
    window_start: str | None = None
    window_end: str | None = None
    # Next page offset within the current window/listing.
    offset: int = 0
    # Next page cursor within the current window, for cursor-paginated endpoints (UsageSummary).
    page_token: str | None = None
    # Index of the next parent row to fan out within the parent page at `offset`.
    parent_index: int = 0


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


def _usage_row_id(row: dict[str, Any]) -> str:
    """Deterministic id for a usage row. UsageSummary rows have no id, and optional dimensions
    (subaccount, error code) can be absent, so a composite primary key could hold nulls."""
    dimensions = {key: value for key, value in row.items() if key not in USAGE_METRIC_FIELDS}
    return hashlib.sha256(json.dumps(dimensions, sort_keys=True, default=str).encode()).hexdigest()


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
        total_path=config.total_path,
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


def _get_participant_rows(
    client: RESTClient,
    auth_id: str,
    parent_params: dict[str, Any],
    resume: PlivoResumeConfig | None,
    resumable_source_manager: ResumableSourceManager[PlivoResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    parent = PLIVO_ENDPOINTS[MULTI_PARTY_CALLS]
    child = PLIVO_ENDPOINTS[MULTI_PARTY_CALL_PARTICIPANTS]
    # An MPC listed by the parent can have no participant listing any more; skip it rather than fail the run.
    child_hooks = create_response_hooks(
        [{"status_code": 404, "action": "ignore"}], resource_name=MULTI_PARTY_CALL_PARTICIPANTS
    )

    parent_offset = resume.offset if resume else 0
    skip_parents = resume.parent_index if resume else 0
    parent_pages = client.paginate(
        path=f"Account/{auth_id}/{parent.path}",
        params=parent_params,
        paginator=OffsetPaginator(limit=PAGE_SIZE, offset=parent_offset, total_path=parent.total_path),
        data_selector="objects",
    )
    for mpcs in parent_pages:
        for index, raw_mpc in enumerate(mpcs):
            if index < skip_parents:
                continue
            mpc = _normalize_row(raw_mpc, parent)
            mpc_uuid = mpc["mpc_uuid"]
            # Stage the position after this MPC before yielding its participants, so a resume
            # starts at the next MPC and never writes these participants twice.
            resumable_source_manager.save_state(PlivoResumeConfig(offset=parent_offset, parent_index=index + 1))
            child_path = f"Account/{auth_id}/{child.path}".replace("{mpc_uuid}", mpc_uuid)
            participants = [
                {**participant, "mpc_uuid": mpc_uuid, "mpc_end_time": mpc.get("end_time")}
                for page in client.paginate(
                    path=child_path,
                    # The participant listing takes no limit or offset and returns every participant.
                    paginator=SinglePagePaginator(),
                    data_selector="objects",
                    hooks=child_hooks,
                )
                for participant in page
            ]
            if participants:
                yield [_normalize_row(participant, child) for participant in participants]
            else:
                resumable_source_manager.safe_point()
        skip_parents = 0
        parent_offset += PAGE_SIZE


def _get_usage_rows(
    client: RESTClient,
    path: str,
    resume: PlivoResumeConfig | None,
    resumable_source_manager: ResumableSourceManager[PlivoResumeConfig],
    last_value: Any,
    now: datetime,
) -> Iterator[list[dict[str, Any]]]:
    config = PLIVO_ENDPOINTS[USAGE_SUMMARY]
    # to_date is exclusive, so ending at today's date syncs complete days only.
    end = datetime.combine(now.date(), datetime.min.time(), tzinfo=UTC)
    if resume is not None and resume.window_start:
        start = _coerce_datetime(resume.window_start)
    elif last_value is not None:
        # from_date is inclusive: re-read the watermark day so a late restatement merges in place.
        watermark = _coerce_datetime(last_value)
        start = datetime.combine(watermark.date(), datetime.min.time(), tzinfo=UTC)
    else:
        start = end - timedelta(days=USAGE_BACKFILL_DAYS)

    # Pin the resumed window's saved upper bound so its page token stays valid.
    resumed_end = _coerce_datetime(resume.window_end) if resume is not None and resume.window_end else None
    window_start = start
    index = 0
    while window_start < end:
        if index == 0 and resumed_end is not None:
            window_end = resumed_end
        else:
            window_end = min(window_start + timedelta(days=USAGE_MAX_QUERY_RANGE_DAYS), end)
        params = {
            "granularity": "day",
            "from_date": window_start.strftime("%Y-%m-%d"),
            "to_date": window_end.strftime("%Y-%m-%d"),
            "page_size": USAGE_PAGE_SIZE,
        }
        resumed_token = resume.page_token if (index == 0 and resume is not None and resume.window_start) else None

        window_start_iso = window_start.isoformat()
        window_end_iso = window_end.isoformat()

        def window_checkpoint(
            state: Optional[dict[str, Any]],
            _has_next_page: bool,
            window_start_iso: str = window_start_iso,
            window_end_iso: str = window_end_iso,
        ) -> None:
            if state:
                resumable_source_manager.save_state(
                    PlivoResumeConfig(
                        window_start=window_start_iso, window_end=window_end_iso, page_token=state["cursor"]
                    )
                )
            else:
                resumable_source_manager.save_state(PlivoResumeConfig(window_start=window_end_iso))

        for page in client.paginate(
            path=path,
            params=params,
            paginator=JSONResponseCursorPaginator(
                cursor_path="meta.next_page_token", cursor_param="page_token", raise_on_repeated_cursor=True
            ),
            # Staged before the page is yielded, so a hand-off after the write resumes past it.
            page_state_hook=window_checkpoint,
            initial_paginator_state={"cursor": resumed_token} if resumed_token else None,
        ):
            rows: list[dict[str, Any]] = []
            for body in page:
                rows.extend({**row, "charge_type": "usage"} for row in body.get("usage") or [])
                # Rentals, fees, taxes and adjustments arrive only on a window's first page.
                rows.extend({**charge, "charge_type": "other_charge"} for charge in body.get("other_charges") or [])
            yield [_normalize_row({**row, "id": _usage_row_id(row)}, config) for row in rows]

        window_start = window_end
        index += 1


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

    if endpoint == USAGE_SUMMARY:
        last_value = db_incremental_field_last_value if should_use_incremental_field else None
        yield from _get_usage_rows(client, path, resume, resumable_source_manager, last_value, now)
        return

    if endpoint == MULTI_PARTY_CALL_PARTICIPANTS:
        parent_params: dict[str, Any] = {}
        if should_use_incremental_field and db_incremental_field_last_value is not None and config.time_filter_field:
            parent_params[f"{config.time_filter_field}__gt"] = _format_filter_value(
                _coerce_datetime(db_incremental_field_last_value)
            )
        yield from _get_participant_rows(client, auth_id, parent_params, resume, resumable_source_manager)
        return

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
