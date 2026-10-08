from collections.abc import Callable, Iterator
from dataclasses import field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from structlog.types import FilteringBoundLogger

from posthog.dataclasses import frozen

if TYPE_CHECKING:
    from products.warehouse_sources.backend.temporal.data_imports.sources.datadog.settings import DatadogEndpointConfig

SEARCH_BATCH_SIZE = 500


@frozen
class DatadogIssueSearchConfig:
    """Request and response shape of Datadog's Error Tracking issue search.

    The endpoint is a POST with a JSON body, returns at most ``max_results_per_request`` issues and
    has no pagination, so the sync covers a lookback window by halving it until no slice is capped.
    """

    query: str = "*"
    # ``ALL`` covers APM traces, logs and RUM in one call, so one request grades every source of errors.
    persona: str = "ALL"
    order_by: str = "TOTAL_COUNT"
    # Resolved, ignored and excluded issues never become signals, so Datadog filters them out. They
    # would otherwise fill the capped result list and force needless window splits.
    states: tuple[str, ...] = ("OPEN", "ACKNOWLEDGED")
    # The ``included`` object type that carries the issue attributes (error type, message, state, ...).
    included_type: str = "issue"
    # Issue attributes Datadog returns as epoch milliseconds. They become ISO strings so they
    # partition and parse like every other timestamp column in this source.
    epoch_ms_fields: tuple[str, ...] = ("first_seen", "last_seen")
    max_results_per_request: int = 100
    # Smallest slice worth splitting further. A slice this small that is still capped is reported
    # loudly instead of split forever.
    min_window_seconds: int = 3600
    # Hard cap on search requests in one sync. Past it the remaining windows are not split, so a busy
    # org gets a partial answer and a warning instead of an unbounded run of requests.
    max_requests_per_sync: int = 60
    # Issue attributes in Datadog's ``IssueAttributes`` schema. Every row carries each of them, empty
    # when Datadog omits it, so the table keeps the same columns whatever the window holds.
    issue_fields: tuple[str, ...] = (
        "error_message",
        "error_type",
        "file_path",
        "first_seen",
        "first_seen_version",
        "function_name",
        "is_crash",
        "languages",
        "last_seen",
        "last_seen_version",
        "platform",
        "regression",
        "service",
        "state",
    )
    # Counts that add up across slices. The other counts are distinct counts, so the same user or
    # session can appear in two slices and only the largest slice value is a safe lower bound.
    additive_count_columns: tuple[str, ...] = ("window_total_count",)
    # Search-result count attribute -> column. The counts cover the queried window only, so the
    # columns say so.
    count_fields: dict[str, str] = field(
        default_factory=lambda: {
            "total_count": "window_total_count",
            "impacted_sessions": "window_impacted_sessions",
            "impacted_users": "window_impacted_users",
        }
    )


def _epoch_ms_to_iso(value: Any) -> Any:
    """Render epoch milliseconds like the event endpoints' timestamps (UTC ISO 8601, ms, ``Z``)."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return value
    try:
        dt = datetime.fromtimestamp(int(value) // 1000, UTC).replace(microsecond=(int(value) % 1000) * 1000)
    except (OverflowError, OSError, ValueError):
        return value
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _build_search_body(search: DatadogIssueSearchConfig, from_ms: int, to_ms: int) -> dict[str, Any]:
    """Body of an Error Tracking issue search. ``from`` is inclusive and ``to`` is exclusive."""
    return {
        "data": {
            "type": "search_request",
            "attributes": {
                "query": search.query,
                "persona": search.persona,
                "order_by": search.order_by,
                "states": list(search.states),
                "from": from_ms,
                "to": to_ms,
            },
        }
    }


def _join_included(response_json: Any, search: DatadogIssueSearchConfig) -> list[dict[str, Any]]:
    """Turn search results into one flat row per issue.

    A result only carries window counts and a link to its issue. The issue attributes sit in the
    ``included`` list, which mixes issue, case, user and team objects, so only the issue type is used.
    """
    if not isinstance(response_json, dict):
        return []

    included = response_json.get("included")
    issue_attributes: dict[Any, dict[str, Any]] = {}
    if isinstance(included, list):
        for inc in included:
            if isinstance(inc, dict) and inc.get("type") == search.included_type:
                attributes = inc.get("attributes")
                issue_attributes[inc.get("id")] = attributes if isinstance(attributes, dict) else {}

    results = response_json.get("data")
    rows: list[dict[str, Any]] = []
    for result in results if isinstance(results, list) else []:
        if not isinstance(result, dict):
            continue
        relationship = (result.get("relationships") or {}).get(search.included_type) or {}
        related = relationship.get("data") if isinstance(relationship, dict) else None
        issue_id = related.get("id") if isinstance(related, dict) else None
        issue_id = issue_id or result.get("id")
        if not issue_id:
            continue

        # Seeding every known attribute keeps the same columns in the table when a window has no value for one.
        row: dict[str, Any] = dict.fromkeys(search.issue_fields)
        row.update(issue_attributes.get(issue_id, {}))
        counts = result.get("attributes")
        counts = counts if isinstance(counts, dict) else {}
        for source_field, column in search.count_fields.items():
            row[column] = counts.get(source_field)
        row["id"] = issue_id
        rows.append(row)
    return rows


def _merge_issue_rows(
    merged: dict[Any, dict[str, Any]], rows: list[dict[str, Any]], search: DatadogIssueSearchConfig
) -> None:
    """Fold rows from one slice into the per-issue totals.

    Slices do not overlap, so event counts add up. Distinct user and session counts do not, because
    one user can appear in two slices, so they keep the largest slice value. ``first_seen`` and
    ``last_seen`` describe the whole issue and are the same in every slice, so the min and max only
    guard against a stale value.
    """
    count_columns = list(search.count_fields.values())
    for row in rows:
        existing = merged.get(row["id"])
        if existing is None:
            merged[row["id"]] = row
            continue
        for column in count_columns:
            if column in search.additive_count_columns:
                existing[column] = (existing.get(column) or 0) + (row.get(column) or 0)
            else:
                existing[column] = max(existing.get(column) or 0, row.get(column) or 0)
        if row.get("last_seen") is not None:
            existing["last_seen"] = max(existing.get("last_seen") or 0, row["last_seen"])
        if row.get("first_seen") is not None:
            existing["first_seen"] = min(existing.get("first_seen") or row["first_seen"], row["first_seen"])


@frozen(frozen=False)
class _SearchBudget:
    """Search requests a sync may still start, beyond the one already made for the current window.

    A split reserves both of its requests up front, so the total never passes the configured cap.
    """

    remaining: int


def _search_window(
    fetch_page: Callable[..., Any],
    url: str,
    search: DatadogIssueSearchConfig,
    from_ms: int,
    to_ms: int,
    merged: dict[Any, dict[str, Any]],
    logger: FilteringBoundLogger,
    budget: _SearchBudget,
) -> None:
    data = fetch_page(url, False, _build_search_body(search, from_ms, to_ms))
    rows = _join_included(data, search)
    result_count = len(data.get("data") or []) if isinstance(data, dict) else 0

    # Both truncation paths below warn instead of raising, unlike the fan-out limit. The search has no
    # pagination, so a busy account would otherwise fail every sync. The table can miss some issues
    # in the window, and the next sync reads the window again.
    if result_count >= search.max_results_per_request:
        if to_ms - from_ms > search.min_window_seconds * 1000:
            if budget.remaining < 2:
                logger.warning(
                    "datadog.search_request_cap_reached",
                    max_requests=search.max_requests_per_sync,
                    from_ms=from_ms,
                    to_ms=to_ms,
                )
            else:
                # The API has no pagination, so a full response may hide issues. Halve the window until
                # no slice is full. Earlier half first, so rows arrive in time order.
                budget.remaining -= 2
                midpoint = from_ms + (to_ms - from_ms) // 2
                _search_window(fetch_page, url, search, from_ms, midpoint, merged, logger, budget)
                _search_window(fetch_page, url, search, midpoint, to_ms, merged, logger, budget)
                return
        else:
            logger.warning(
                "datadog.search_window_truncated",
                max_results=search.max_results_per_request,
                from_ms=from_ms,
                to_ms=to_ms,
            )

    _merge_issue_rows(merged, rows, search)


def search_issue_rows(
    config: "DatadogEndpointConfig",
    fetch_page: Callable[..., Any],
    url: str,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    """Read Error Tracking issues for the lookback window, merged into one row per issue."""
    search = config.search
    assert search is not None

    to_ms = int(datetime.now(UTC).timestamp() * 1000)
    from_ms = to_ms - (config.default_lookback_days or 1) * 24 * 3600 * 1000

    # Counts for a split issue only add up across the whole window, so rows are held until every
    # slice has been read. One row per issue keeps this small.
    merged: dict[Any, dict[str, Any]] = {}
    budget = _SearchBudget(remaining=search.max_requests_per_sync - 1)
    _search_window(fetch_page, url, search, from_ms, to_ms, merged, logger, budget)

    rows = list(merged.values())
    for row in rows:
        for column in search.epoch_ms_fields:
            if column in row:
                row[column] = _epoch_ms_to_iso(row[column])
    for start in range(0, len(rows), SEARCH_BATCH_SIZE):
        yield rows[start : start + SEARCH_BATCH_SIZE]
