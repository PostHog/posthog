from collections.abc import Iterator
from datetime import date, datetime
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.skio.settings import (
    ENDPOINTS,
    SKIO_GRAPHQL_URL,
    SKIO_PAGE_SIZE,
    SkioEndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 60

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
    field's value on that row, unset on full refresh (which pages on `id` alone)."""

    last_id: str | None = None
    last_value: str | None = None


def _headers(api_token: str) -> dict[str, str]:
    # Skio's documented header is `authorization: API <token>` (case sensitive).
    return {"authorization": f"API {api_token}"}


def _format_timestamp(value: Any) -> str:
    if isinstance(value, datetime | date):
        return value.isoformat()
    return str(value)


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
    document = config.query_document
    # One session for every page so urllib3 keeps the connection alive; the token is redacted from
    # tracked-transport samples because it rides in a non-standard `authorization` header value.
    session = make_tracked_session(redact_values=(api_token,))

    field = incremental_field if should_use_incremental_field else None
    cursor = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    order_by = _build_order_by(field)

    while True:
        variables: dict[str, Any] = {"limit": SKIO_PAGE_SIZE, "orderBy": order_by}
        where = _build_where(field, db_incremental_field_last_value if field else None, cursor)
        if where is not None:
            variables["where"] = where

        data = _post_query(session, api_token, document, variables, logger)
        rows = data.get(config.query_name) or []
        if not rows:
            break

        last_row = rows[-1]
        cursor = SkioResumeConfig(
            last_id=str(last_row["id"]),
            last_value=str(last_row[field]) if field and last_row.get(field) is not None else None,
        )
        # Staged before the yield it covers: the pipeline commits right after it writes these rows,
        # so a resumed run picks up exactly after the last written batch.
        resumable_source_manager.save_state(cursor)
        yield rows

        if len(rows) < SKIO_PAGE_SIZE:
            break


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
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        # The physical Delta column: the pipeline snake_cases API field names before partitioning.
        partition_keys=["created_at"],
    )
