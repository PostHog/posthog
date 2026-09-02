"""Close Advanced Filtering (`POST /data/search/`) walker for Leads and Contacts.

`GET /lead/` and `GET /contact/` accept no filter beyond `_skip`/`_limit`/`_fields`, and Close
caps `_skip` per resource, so on a large org those two tables stop syncing partway through with
no way to window around the cap. Advanced Filtering is the only read path that exposes a
`date_created`/`date_updated` filter for them, which lets us page by keyset — re-querying from
the last timestamp we emitted — instead of by ever-growing offset.

Keyset paging also sidesteps the two limits Advanced Filtering has of its own: cursors expire
after 30s, and a single cursor walk returns at most 10k objects. Every keyset request is a fresh
query for the next page-worth of rows, so neither applies. The cursor is used only to step over a
run of rows sharing one exact timestamp, where moving the filter forward cannot make progress.
"""

import dataclasses
from collections.abc import Callable, Iterator
from typing import Any, Optional

from requests import Session
from structlog.types import FilteringBoundLogger

CLOSE_SEARCH_PATH = "/data/search/"
CUSTOM_FIELD_PATH = "/custom_field/{object_type}/"
REQUEST_TIMEOUT_SECONDS = 60
# Close caps `_limit` per resource and doesn't publish the ceiling for search, so stay at the
# value the list endpoints already accept rather than probing for a higher one.
SEARCH_PAGE_LIMIT = 100
CUSTOM_FIELD_PAGE_LIMIT = 100
# Cap on how many custom-field pages we walk. Orgs have tens of custom fields, not thousands.
MAX_CUSTOM_FIELD_PAGES = 20
# How many consecutive cursor pages we'll follow across a single-timestamp run before giving up.
# At SEARCH_PAGE_LIMIT rows a page this covers 50k rows sharing one exact timestamp; past that
# something is wrong with the data and failing loudly beats looping.
MAX_PLATEAU_PAGES = 500


class CloseSearchError(Exception):
    pass


class CloseCursorExpiredError(CloseSearchError):
    pass


@dataclasses.dataclass(frozen=True)
class SearchPage:
    rows: list[dict[str, Any]]
    cursor: Optional[str]


def _moment(value: str) -> dict[str, str]:
    return {"type": "fixed_utc", "value": value}


def _regular_field(object_type: str, field_name: str) -> dict[str, str]:
    return {"type": "regular_field", "object_type": object_type, "field_name": field_name}


def build_search_body(
    object_type: str,
    fields: list[str],
    cursor_field: str,
    anchor: Optional[str],
    page_cursor: Optional[str] = None,
    limit: int = SEARCH_PAGE_LIMIT,
) -> dict[str, Any]:
    queries: list[dict[str, Any]] = [{"type": "object_type", "object_type": object_type}]
    if anchor is not None:
        queries.append(
            {
                "type": "field_condition",
                "field": _regular_field(object_type, cursor_field),
                # Inclusive so a row sharing the anchor timestamp is never skipped; the walker
                # filters the ones it already emitted.
                "condition": {"type": "moment_range", "on_or_after": _moment(anchor)},
            }
        )

    body: dict[str, Any] = {
        "query": {"type": "and", "queries": queries},
        # Advanced Filtering returns bare IDs unless every wanted field is named explicitly.
        "_fields": {object_type: fields},
        "sort": [{"direction": "asc", "field": _regular_field(object_type, cursor_field)}],
        "_limit": limit,
    }
    if page_cursor:
        body["cursor"] = page_cursor
    return body


def _post_search(session: Session, base_url: str, body: dict[str, Any]) -> SearchPage:
    response = session.post(f"{base_url}{CLOSE_SEARCH_PATH}", json=body, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 400:
        detail = response.text[:500]
        if "cursor" in detail.lower() and "expire" in detail.lower():
            raise CloseCursorExpiredError(detail)
        # The query shape and field selectors are built from a static list, so a 400 means
        # Close's field set drifted. Surface its message rather than a bare status code.
        raise CloseSearchError(f"Close rejected the search query: {detail}")

    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise CloseSearchError(f"Unexpected Close search response: {str(payload)[:200]}")

    raw_rows = payload.get("data")
    rows = [row for row in raw_rows if isinstance(row, dict)] if isinstance(raw_rows, list) else []
    # `id` is the primary key the whole walk dedupes and merges on. A row without one can't be
    # tracked across the inclusive anchor re-reads, so it would silently duplicate — fail instead.
    if any(not row.get("id") for row in rows):
        raise CloseSearchError("Close returned a search row without an id")
    return SearchPage(rows=rows, cursor=payload.get("cursor") or None)


def fetch_custom_field_selectors(
    session: Session, base_url: str, object_type: str, logger: FilteringBoundLogger
) -> list[str]:
    """Name each custom field explicitly so its value comes back as a flat `custom.cf_*` key.

    Best-effort: a key without custom-field read access should still sync the standard columns
    rather than fail the whole table.
    """
    selectors: list[str] = []
    url = f"{base_url}{CUSTOM_FIELD_PATH.format(object_type=object_type)}"

    try:
        for page in range(MAX_CUSTOM_FIELD_PAGES):
            response = session.get(
                url,
                params={"_limit": CUSTOM_FIELD_PAGE_LIMIT, "_skip": page * CUSTOM_FIELD_PAGE_LIMIT},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
            rows = payload.get("data") or []
            selectors.extend(f"custom.{row['id']}" for row in rows if isinstance(row, dict) and row.get("id"))
            if not payload.get("has_more"):
                break
    except Exception as exc:
        logger.warning(
            f"Close: could not list custom fields, syncing standard fields only. object_type={object_type} error={exc}"
        )
        return []

    return selectors


def iter_search_rows(
    session: Session,
    base_url: str,
    object_type: str,
    fields: list[str],
    cursor_field: str,
    start_anchor: Optional[str],
    logger: FilteringBoundLogger,
    on_checkpoint: Optional[Callable[[str], None]] = None,
    limit: int = SEARCH_PAGE_LIMIT,
) -> Iterator[list[dict[str, Any]]]:
    """Walk every object of `object_type` in ascending `cursor_field` order, a page at a time.

    `on_checkpoint(anchor)` is called after each page is yielded, so a crash re-reads the last
    anchor rather than skipping past it. Rows tied to the anchor timestamp are re-read on resume
    and deduped downstream by primary key.
    """
    anchor = start_anchor
    emitted_at_anchor: set[str] = set()
    page_cursor: Optional[str] = None
    plateau_pages = 0

    while True:
        used_cursor = page_cursor is not None
        body = build_search_body(object_type, fields, cursor_field, anchor, page_cursor, limit)

        try:
            page = _post_search(session, base_url, body)
        except CloseCursorExpiredError:
            if not used_cursor:
                raise
            # Downstream Delta writes can stall the walk past the 30s cursor TTL. Re-issue the
            # same query without the cursor; emitted_at_anchor keeps the replay from duplicating.
            logger.warning(f"Close: search cursor expired, re-anchoring. object_type={object_type} anchor={anchor}")
            page_cursor = None
            continue

        if not page.rows:
            return

        fresh = [row for row in page.rows if row["id"] not in emitted_at_anchor]
        if fresh:
            yield fresh

        last_value = page.rows[-1].get(cursor_field)
        if last_value is None:
            raise CloseSearchError(f"Close returned {object_type} rows without a {cursor_field} value")

        if last_value == anchor:
            # Every row on this page shares the anchor timestamp, so advancing the keyset filter
            # would just re-read them. Step over the run with Close's cursor instead.
            plateau_pages += 1
            if plateau_pages > MAX_PLATEAU_PAGES:
                raise CloseSearchError(
                    f"Close returned more than {MAX_PLATEAU_PAGES * limit} {object_type} rows "
                    f"sharing {cursor_field}={anchor}, which cannot be paged past"
                )
            emitted_at_anchor.update(row["id"] for row in page.rows)
            if page.cursor is None:
                return
            page_cursor = page.cursor
            continue

        plateau_pages = 0
        anchor = last_value
        emitted_at_anchor = {row["id"] for row in page.rows if row.get(cursor_field) == last_value}
        page_cursor = None
        if on_checkpoint is not None:
            on_checkpoint(anchor)

        # A short keyset page means we've drained the table. In cursor mode the terminal signal
        # is Close handing back a null cursor instead.
        if used_cursor:
            if page.cursor is None:
                return
        elif len(page.rows) < limit:
            return
