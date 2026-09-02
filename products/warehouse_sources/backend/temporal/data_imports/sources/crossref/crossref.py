import dataclasses
from collections.abc import Iterator
from datetime import date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.crossref.settings import (
    CROSSREF_BASE_URL,
    ENDPOINTS,
    INCREMENTAL_OPTIONS,
    MAX_PAGE_SIZE,
)

# Crossref's dynamic rate limit (advertised per-response via X-Rate-Limit-* headers) is typically
# ~1 req/s on the public pool and higher on the polite pool (a mailto param). The tracked
# session's default retry policy already honors 429 + Retry-After, so no extra throttling here.
REQUEST_TIMEOUT_SECONDS = 30


@dataclasses.dataclass(frozen=True)
class CrossrefResumeConfig:
    cursor: str


def _build_url(path: str, params: dict[str, Any]) -> str:
    query = urlencode({key: value for key, value in params.items() if value is not None})
    return f"{CROSSREF_BASE_URL}{path}?{query}" if query else f"{CROSSREF_BASE_URL}{path}"


def _build_scope_filter(member_id: Optional[str], funder_id: Optional[str], issn: Optional[str]) -> Optional[str]:
    clauses = []
    if member_id:
        clauses.append(f"member:{member_id}")
    if funder_id:
        clauses.append(f"funder:{funder_id}")
    if issn:
        clauses.append(f"issn:{issn}")
    return ",".join(clauses) if clauses else None


def _format_filter_value(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return str(value)


def _flatten_date(item: dict[str, Any], key: str, target: str) -> None:
    value = item.get(key)
    if isinstance(value, dict) and value.get("date-time"):
        item[target] = value["date-time"]


def _normalize_work(item: dict[str, Any]) -> dict[str, Any]:
    """Mirror Crossref's nested date objects onto flat, sortable columns.

    `indexed`/`deposited`/`created` each come back as `{"date-time": ..., "date-parts": ...}`;
    the incremental watermark and partitioning need a scalar column to compare against.
    """
    _flatten_date(item, "indexed", "indexed_date")
    _flatten_date(item, "deposited", "deposited_date")
    _flatten_date(item, "created", "created_date")
    return item


def validate_credentials(mailto: Optional[str]) -> bool:
    params: dict[str, Any] = {"rows": 0}
    if mailto:
        params["mailto"] = mailto
    url = _build_url("/works", params)
    try:
        # mailto isn't a credential, but it's still a contact email a source admin typed in — keep
        # it out of the URL the tracked session logs/captures, the same way secrets are redacted.
        redact_values = (mailto,) if mailto else ()
        response = make_tracked_session(redact_values=redact_values).get(url, timeout=REQUEST_TIMEOUT_SECONDS)
        return response.status_code == 200
    except Exception:
        return False


def _build_params(
    endpoint: str,
    mailto: Optional[str],
    member_id: Optional[str],
    funder_id: Optional[str],
    issn: Optional[str],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: Optional[str],
) -> dict[str, Any]:
    params: dict[str, Any] = {"rows": MAX_PAGE_SIZE}
    if mailto:
        params["mailto"] = mailto

    filters = []
    if endpoint == "Works":
        scope_filter = _build_scope_filter(member_id, funder_id, issn)
        if scope_filter:
            filters.append(scope_filter)

        incremental_option = INCREMENTAL_OPTIONS.get(incremental_field or "")
        if should_use_incremental_field and incremental_option:
            # Sort must match the filter field even on the first (unwatermarked) sync, so the
            # pipeline's ascending-watermark assumption (SourceResponse.sort_mode="asc") holds
            # from the very first page.
            params["sort"] = incremental_option.sort
            params["order"] = "asc"
            if db_incremental_field_last_value:
                formatted_value = _format_filter_value(db_incremental_field_last_value)
                filters.append(f"{incremental_option.filter_prefix}:{formatted_value}")

    if filters:
        params["filter"] = ",".join(filters)

    return params


def get_rows(
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CrossrefResumeConfig],
    mailto: Optional[str],
    member_id: Optional[str],
    funder_id: Optional[str],
    issn: Optional[str],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: Optional[str] = None,
) -> Iterator[Any]:
    config = ENDPOINTS[endpoint]
    # mailto isn't a credential, but it's still a contact email a source admin typed in — keep
    # it out of the URL the tracked session logs/captures, the same way secrets are redacted.
    session = make_tracked_session(redact_values=(mailto,) if mailto else ())
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)

    params = _build_params(
        endpoint,
        mailto,
        member_id,
        funder_id,
        issn,
        should_use_incremental_field,
        db_incremental_field_last_value,
        incremental_field,
    )

    if not config.supports_cursor:
        # /types has no cursor: it always returns its full ~30-row vocabulary in one response.
        response = session.get(_build_url(config.path, params), timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        for item in response.json()["message"]["items"]:
            batcher.batch(item)
        if batcher.should_yield(include_incomplete_chunk=True):
            yield batcher.get_table()
        return

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor = resume_config.cursor if resume_config is not None else "*"

    while True:
        page_params = {**params, "cursor": cursor}
        response = session.get(_build_url(config.path, page_params), timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        message = response.json().get("message", {})
        items = message.get("items", [])

        # Crossref cursors can keep returning a (possibly stale) next-cursor even once there's
        # nothing left, so an empty page — not just a missing next-cursor — ends the sync.
        if not items:
            break

        next_cursor = message.get("next-cursor")

        for item in items:
            batcher.batch(_normalize_work(item) if endpoint == "Works" else item)

            if batcher.should_yield():
                yield batcher.get_table()
                # Save AFTER yielding so a crash re-yields (and re-merges) the last batch instead
                # of skipping it.
                if next_cursor:
                    resumable_source_manager.save_state(CrossrefResumeConfig(cursor=next_cursor))

        if not next_cursor:
            break
        cursor = next_cursor

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def crossref_source(
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CrossrefResumeConfig],
    mailto: Optional[str],
    member_id: Optional[str],
    funder_id: Optional[str],
    issn: Optional[str],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: Optional[str] = None,
) -> SourceResponse:
    endpoint_config = ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            mailto=mailto,
            member_id=member_id,
            funder_id=funder_id,
            issn=issn,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=endpoint_config.primary_keys,
        sort_mode="asc",
        partition_count=1 if endpoint_config.partition_key else None,
        partition_size=1 if endpoint_config.partition_key else None,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
