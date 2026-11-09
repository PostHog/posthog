from collections.abc import Iterator
from datetime import date, datetime
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.sources.sdk import (
    ResumableSourceManager,
    SourceResponse,
    frozen,
    make_tracked_session,
    retry_with_deadline,
)
from products.warehouse_sources.sources.skio.settings import (
    ENDPOINTS,
    SKIO_GRAPHQL_URL,
    SKIO_PAGE_SIZE,
    SKIO_PARENT_PAGE_SIZE,
    SkioEndpointConfig,
    SkioParentConfig,
)

REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRY_ATTEMPTS = 5

# Skio's Hasura instance answers an invalid or revoked token with HTTP 200 and this message in the
# GraphQL errors body (verified against the live API), so credential failures are classified on the
# error text rather than the status code.
INVALID_TOKEN_ERROR = "Invalid response from authorization hook"
# A field the token's role can't see fails validation with this fragment (verified against the
# live API with no token); the query is the same on every retry, so it can never self-heal.
FIELD_NOT_FOUND_ERROR = "not found in type: 'query_root'"


class SkioAPIError(Exception):
    """A GraphQL-level error from Skio. Hasura returns these with HTTP 200, so the tracked
    transport's status-code retries never see them; permanent ones are matched by message in
    `get_non_retryable_errors`."""


@frozen
class SkioResumeConfig:
    """Keyset cursor: the last row already yielded. The next page filters strictly past it, so a
    resumed run continues exactly after the last committed batch. `last_value` is the incremental
    field's value on that row, unset on full refresh (which pages on `id` alone).

    For an endpoint read through a parent, `parent_id` is the last parent whose rows were yielded,
    and `last_id` / `last_value` locate the last row within that parent, unset once it is done."""

    last_id: str | None = None
    last_value: str | None = None
    parent_id: str | None = None


def _headers(api_token: str) -> dict[str, str]:
    # Skio's documented header is `authorization: API <token>` (case sensitive).
    return {"authorization": f"API {api_token}"}


def _format_timestamp(value: Any) -> str:
    if isinstance(value, datetime | date):
        return value.isoformat()
    return str(value)


@retry_with_deadline(
    # Skio's GraphQL endpoint is queried over POST, which the tracked session's transport-level
    # retry does not cover (it only retries idempotent methods), so a read timeout or dropped
    # connection would otherwise fail the whole import attempt on the first blip.
    retry=retry_if_exception_type((requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
    wait=wait_exponential_jitter(initial=2, max=60),
    reraise=True,
)
def _post_query(
    session: requests.Session,
    api_token: str,
    document: str,
    variables: dict[str, Any],
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    response = session.post(
        SKIO_GRAPHQL_URL,
        json={"query": document, "variables": variables},
        headers=_headers(api_token),
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()

    payload = response.json()
    errors = payload.get("errors")
    if errors:
        messages = "; ".join(str(error.get("message", error)) for error in errors if isinstance(error, dict))
        logger.error(f"Skio API error: {messages}")
        raise SkioAPIError(f"Skio API error: {messages or errors}")

    return payload.get("data") or {}


def _build_order_by(incremental_field: str | None) -> list[dict[str, str]]:
    # `id` breaks ties between rows sharing a timestamp so the keyset cursor never skips or
    # revisits rows within one value.
    if incremental_field:
        return [{incremental_field: "asc"}, {"id": "asc"}]
    return [{"id": "asc"}]


def _build_where(
    incremental_field: str | None,
    db_incremental_field_last_value: Any,
    cursor: SkioResumeConfig | None,
) -> dict[str, Any] | None:
    """Combine the incremental watermark with the keyset-continuation predicate.

    The watermark uses `_gte` rather than `_gt` so rows written at exactly the stored value after
    the previous run read it are re-pulled; merge dedupes them on `id`.
    """
    clauses: list[dict[str, Any]] = []

    if incremental_field and db_incremental_field_last_value is not None:
        clauses.append({incremental_field: {"_gte": _format_timestamp(db_incremental_field_last_value)}})

    if cursor is not None and cursor.last_id is not None:
        if incremental_field and cursor.last_value is not None:
            clauses.append(
                {
                    "_or": [
                        {incremental_field: {"_gt": cursor.last_value}},
                        {
                            "_and": [
                                {incremental_field: {"_eq": cursor.last_value}},
                                {"id": {"_gt": cursor.last_id}},
                            ]
                        },
                    ]
                }
            )
        else:
            clauses.append({"id": {"_gt": cursor.last_id}})

    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"_and": clauses}


def validate_credentials(api_token: str) -> tuple[bool, str | None]:
    """One cheap authenticated probe. It must select a real collection: Skio's Hasura answers
    bare `{ __typename }` even with no token, so only a table read exercises the auth hook."""
    config = ENDPOINTS["subscriptions"]
    document = f"query ValidateCredentials {{ {config.query_name}(limit: 1) {{ id }} }}"
    session = make_tracked_session(redact_values=(api_token,))
    try:
        response = session.post(
            SKIO_GRAPHQL_URL,
            json={"query": document},
            headers=_headers(api_token),
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return False, "Could not connect to the Skio API"

    errors = payload.get("errors")
    if not errors:
        return True, None

    messages = "; ".join(str(error.get("message", "")) for error in errors if isinstance(error, dict))
    if INVALID_TOKEN_ERROR in messages or FIELD_NOT_FOUND_ERROR in messages:
        return False, "Invalid Skio API token"
    return False, f"Skio API error: {messages}"


def _row_cursor(row: dict[str, Any], field: str | None, parent_id: str | None = None) -> SkioResumeConfig:
    return SkioResumeConfig(
        last_id=str(row["id"]),
        last_value=str(row[field]) if field and row.get(field) is not None else None,
        parent_id=parent_id,
    )


def _get_top_level_rows(
    session: requests.Session,
    api_token: str,
    config: SkioEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SkioResumeConfig],
    field: str | None,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    document = config.query_document
    cursor = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    order_by = _build_order_by(field)

    while True:
        variables: dict[str, Any] = {"limit": SKIO_PAGE_SIZE, "orderBy": order_by}
        where = _build_where(field, db_incremental_field_last_value, cursor)
        if where is not None:
            variables["where"] = where

        data = _post_query(session, api_token, document, variables, logger)
        rows = data.get(config.query_name) or []
        if not rows:
            break

        cursor = _row_cursor(rows[-1], field)
        # Staged before the yield it covers: the pipeline commits right after it writes these rows,
        # so a resumed run picks up exactly after the last written batch.
        resumable_source_manager.save_state(cursor)
        yield rows

        if len(rows) < SKIO_PAGE_SIZE:
            break


def _get_nested_rows(
    session: requests.Session,
    api_token: str,
    config: SkioEndpointConfig,
    parent: SkioParentConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SkioResumeConfig],
    field: str | None,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    """Read an array relationship a page of parents at a time, each parent with up to one page of
    rows. Rows are ordered per parent, not across the table."""
    document = config.query_document
    order_by = _build_order_by(field)
    row_filter = _build_where(field, db_incremental_field_last_value, None)
    # Restrict parents to those with at least one matching row, so full refresh skips the parents
    # without any and incremental reads only the parents with changes since the watermark.
    has_rows = {config.query_name: row_filter or {"id": {"_is_null": False}}}

    def fetch_rows_of(parent_id: str, cursor: SkioResumeConfig) -> list[dict[str, Any]]:
        variables: dict[str, Any] = {
            "parentLimit": 1,
            "parentWhere": {"id": {"_eq": parent_id}},
            "limit": SKIO_PAGE_SIZE,
            "orderBy": order_by,
        }
        where = _build_where(field, db_incremental_field_last_value, cursor)
        if where is not None:
            variables["where"] = where
        parents = _post_query(session, api_token, document, variables, logger).get(parent.query_name) or []
        return (parents[0].get(config.query_name) or []) if parents else []

    def read_parent(parent_id: str, rows: list[dict[str, Any]]) -> Iterator[list[dict[str, Any]]]:
        while rows:
            if len(rows) < SKIO_PAGE_SIZE:
                resumable_source_manager.save_state(SkioResumeConfig(parent_id=parent_id))
                yield rows
                return
            cursor = _row_cursor(rows[-1], field, parent_id)
            resumable_source_manager.save_state(cursor)
            yield rows
            rows = fetch_rows_of(parent_id, cursor)

        # The parent's rows ended exactly on a page boundary; nothing is buffered here.
        resumable_source_manager.save_state(SkioResumeConfig(parent_id=parent_id))
        resumable_source_manager.safe_point()

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    after_parent = resume.parent_id if resume is not None else None
    if resume is not None and resume.parent_id is not None and resume.last_id is not None:
        yield from read_parent(resume.parent_id, fetch_rows_of(resume.parent_id, resume))

    while True:
        parent_where: dict[str, Any] = (
            has_rows if after_parent is None else {"_and": [{"id": {"_gt": after_parent}}, has_rows]}
        )
        variables: dict[str, Any] = {
            "parentLimit": SKIO_PARENT_PAGE_SIZE,
            "parentWhere": parent_where,
            "limit": SKIO_PAGE_SIZE,
            "orderBy": order_by,
        }
        if row_filter is not None:
            variables["where"] = row_filter
        parents = _post_query(session, api_token, document, variables, logger).get(parent.query_name) or []
        if not parents:
            break

        for parent_row in parents:
            yield from read_parent(str(parent_row["id"]), parent_row.get(config.query_name) or [])

        after_parent = str(parents[-1]["id"])
        if len(parents) < SKIO_PARENT_PAGE_SIZE:
            break


def get_rows(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SkioResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config: SkioEndpointConfig = ENDPOINTS[endpoint]
    # One session for every page so urllib3 keeps the connection alive; the token is redacted from
    # tracked-transport samples because it rides in a non-standard `authorization` header value.
    session = make_tracked_session(redact_values=(api_token,))

    field = incremental_field if should_use_incremental_field else None
    watermark = db_incremental_field_last_value if field else None

    if config.parent is not None:
        yield from _get_nested_rows(
            session, api_token, config, config.parent, logger, resumable_source_manager, field, watermark
        )
    else:
        yield from _get_top_level_rows(session, api_token, config, logger, resumable_source_manager, field, watermark)


def skio_source(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SkioResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=["id"],
        # A nested endpoint's rows are ordered per parent, so they are not one ascending series.
        sort_mode=None if ENDPOINTS[endpoint].parent is not None else "asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        # The physical Delta column: the pipeline snake_cases API field names before partitioning.
        partition_keys=["created_at"],
    )
