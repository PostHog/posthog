import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode

import orjson
import structlog
from dateutil import parser as dateutil_parser
from requests import Session
from requests.exceptions import RequestException

from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import (
    coerce_datetime_to_utc,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.debugbear.settings import (
    BEFORE_PARAM,
    RUM_BACKFILL_DAYS,
    RUM_GROUP_BY_TIME,
    RUM_PAGE_VIEWS_PAGE_SIZE,
)

logger = structlog.get_logger(__name__)

BASE_URL = "https://www.debugbear.com/api/v1"
_REQUEST_TIMEOUT = 30
# DebugBear's `before` cursor only has day-level granularity (see `_date_only`), so a project
# with many builds landing on the same date could otherwise never make backward progress.
# Bound the walk defensively rather than looping forever.
_MAX_PAGES_PER_PROJECT = 500
# `rumMetrics` returns one array per metric alongside an `info` object describing the query.
_RUM_METRICS_INFO_KEY = "info"


def _auth_headers(api_key: str) -> dict[str, str]:
    return {"x-api-key": api_key, "Accept": "application/json"}


def _session(api_key: str) -> Session:
    # The API key rides in a custom `x-api-key` header the tracked transport's denylist
    # scrubber wouldn't otherwise recognize, so redact it explicitly. `requests` replays
    # custom headers across cross-origin redirects, so a 3xx from the upstream could forward
    # the key to another host — disable redirects to keep it pinned to the validated origin.
    return make_tracked_session(redact_values=(api_key,), allow_redirects=False)


def _get_json(session: Session, path: str, headers: dict[str, str], params: dict[str, Any] | None = None) -> Any:
    url = f"{BASE_URL}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"
    response = session.get(url, headers=headers, timeout=_REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    try:
        response = _session(api_key).get(
            f"{BASE_URL}/projects", headers=_auth_headers(api_key), timeout=_REQUEST_TIMEOUT
        )
    except RequestException as exc:
        return False, str(exc)

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid DebugBear API key."
    if response.status_code == 403:
        return (
            False,
            "This DebugBear API key can't list projects. Use an Admin API key (Account settings > API Keys).",
        )
    return False, f"DebugBear credential check failed with status {response.status_code}."


def _iter_projects(session: Session, headers: dict[str, str]) -> list[dict[str, Any]]:
    payload = _get_json(session, "/projects", headers)
    if not isinstance(payload, list):
        return []
    return [project for project in payload if isinstance(project, dict)]


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, str):
        try:
            parsed = dateutil_parser.parse(value)
        except (ValueError, TypeError):
            return None
        return coerce_datetime_to_utc(parsed)
    return coerce_datetime_to_utc(value)


def _date_only(value: str) -> str | None:
    """DebugBear's `before` param only documents a plain YYYY-MM-DD date, not a full timestamp."""
    if not value:
        return None
    return value[:10]


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _content_id(row: dict[str, Any]) -> str:
    """Deterministic id for a record the API returns without one.

    Identical payloads — the same record re-fetched across overlapping windows — collapse to
    one row on merge, while any field difference yields a distinct key. Two genuinely
    identical records collapse too, an accepted tradeoff versus unbounded duplication.
    """
    return hashlib.sha256(orjson.dumps(row, option=orjson.OPT_SORT_KEYS)).hexdigest()


def _project_fields(project: dict[str, Any]) -> dict[str, Any] | None:
    project_id = project.get("id")
    if project_id is None:
        return None
    return {"project_id": str(project_id), "project_name": project.get("name")}


def _flatten_page_metrics_item(project: dict[str, Any], item: dict[str, Any]) -> dict[str, Any] | None:
    """Shape a `{page, metrics}` pageMetrics entry into a flat row.

    DebugBear reports metrics as dotted keys (e.g. `"performance.score"`, `"analysis.date"`);
    flatten those into safe column names (`performance_score`, `analysis_date`).
    """
    raw_page = item.get("page")
    page = raw_page if isinstance(raw_page, dict) else {}
    raw_metrics = item.get("metrics")
    metrics = raw_metrics if isinstance(raw_metrics, dict) else {}

    page_id = page.get("id")
    if page_id is None:
        return None

    row: dict[str, Any] = {
        "project_id": str(project.get("id")),
        "project_name": project.get("name"),
        "page_id": str(page_id),
        "page_name": page.get("name"),
        "page_url": page.get("url"),
    }
    for key, value in metrics.items():
        row[key.replace(".", "_")] = value

    if not row.get("analysis_date"):
        return None
    return row


def _iter_page_metrics_for_project(
    session: Session,
    headers: dict[str, str],
    project: dict[str, Any],
    stop_when_older_than: datetime | None,
) -> Iterator[dict[str, Any]]:
    """Walk a project's build history backward via the `before` cutoff.

    DebugBear returns the most recent results by default; passing `before=<date>` fetches
    older builds (see https://www.debugbear.com/docs/lab-test-api). There is no forward
    `since`/`after` filter, so an incremental sync still starts from the most recent page and
    stops as soon as a whole page is no newer than the watermark, rather than asking the API
    to filter server-side.
    """
    project_id = project.get("id")
    if project_id is None:
        return

    before: str | None = None
    last_before_sent: str | None = None

    for _ in range(_MAX_PAGES_PER_PROJECT):
        params = {BEFORE_PARAM: before} if before else None
        payload = _get_json(session, f"/projects/{project_id}/pageMetrics", headers, params=params)
        if not isinstance(payload, list) or not payload:
            return

        rows = [
            row
            for row in (_flatten_page_metrics_item(project, item) for item in payload if isinstance(item, dict))
            if row is not None
        ]
        if not rows:
            return

        yield from rows

        parsed_dates = [_parse_datetime(row["analysis_date"]) for row in rows]
        valid_dates: list[datetime] = [d for d in parsed_dates if d is not None]
        if not valid_dates:
            return

        if stop_when_older_than is not None and max(valid_dates) <= stop_when_older_than:
            return

        next_before = _date_only(min(row["analysis_date"] for row in rows))
        if not next_before or next_before == last_before_sent:
            # No backward progress possible (day-granularity cutoff can't move further) —
            # stop rather than re-fetching the same page forever.
            return
        last_before_sent = next_before
        before = next_before


def _iter_pages(session: Session, headers: dict[str, str]) -> Iterator[dict[str, Any]]:
    """Yield every monitored page, read from the pages nested in the projects listing.

    DebugBear documents `/projects/{id}/pages` for creating a page only; the readable
    representation of a page is the `pages` array each project carries.
    """
    for project in _iter_projects(session, headers):
        project_fields = _project_fields(project)
        if project_fields is None:
            continue
        raw_pages = project.get("pages")
        if not isinstance(raw_pages, list):
            continue
        for page in raw_pages:
            if not isinstance(page, dict) or page.get("id") is None:
                continue
            yield {**page, "id": str(page["id"]), **project_fields}


def _flatten_rum_metrics(project_fields: dict[str, Any], payload: Any) -> Iterator[dict[str, Any]]:
    """Turn the `{info, lcp: [...], cls: [...]}` rumMetrics body into one row per metric bucket."""
    if not isinstance(payload, dict):
        return
    raw_info = payload.get(_RUM_METRICS_INFO_KEY)
    info = raw_info if isinstance(raw_info, dict) else {}

    for metric, series in payload.items():
        if metric == _RUM_METRICS_INFO_KEY or not isinstance(series, list):
            continue
        for bucket in series:
            if not isinstance(bucket, dict):
                continue
            date = bucket.get("date")
            if not date:
                continue
            yield {
                **project_fields,
                "metric": metric,
                "date": date,
                "value": bucket.get("value"),
                "count": bucket.get("count"),
                "stat": info.get("stat"),
            }


def _iter_rum_metrics_for_project(
    session: Session,
    headers: dict[str, str],
    project: dict[str, Any],
    since: datetime | None,
) -> Iterator[dict[str, Any]]:
    project_fields = _project_fields(project)
    if project_fields is None:
        return

    start = since or datetime.now(UTC) - timedelta(days=RUM_BACKFILL_DAYS)
    params = {"groupByTime": RUM_GROUP_BY_TIME, "from": _iso(start)}
    payload = _get_json(session, f"/project/{project['id']}/rumMetrics", headers, params=params)
    yield from _flatten_rum_metrics(project_fields, payload)


def _normalize_rum_page_view(project_fields: dict[str, Any], item: dict[str, Any]) -> dict[str, Any] | None:
    if not item.get("date"):
        return None
    row = {**item, **project_fields}
    # The endpoint returns no identifier for a page view, so key rows on their content.
    row["id"] = _content_id(row)
    return row


def _iter_rum_page_views_for_project(
    session: Session,
    headers: dict[str, str],
    project: dict[str, Any],
    since: datetime | None,
) -> Iterator[dict[str, Any]]:
    """Walk a project's page views backward, newest first, by moving the `to` cutoff.

    The endpoint returns at most 5000 rows ordered by date descending with no cursor, so each
    request asks for everything older than the oldest row seen so far. An incremental sync
    also passes `from`, which the server applies, so the walk ends at the watermark.
    """
    project_fields = _project_fields(project)
    if project_fields is None:
        return

    to_cutoff: str | None = None
    last_to_sent: str | None = None

    for _ in range(_MAX_PAGES_PER_PROJECT):
        params: dict[str, Any] = {"count": RUM_PAGE_VIEWS_PAGE_SIZE}
        if since is not None:
            params["from"] = _iso(since)
        if to_cutoff:
            params["to"] = to_cutoff

        payload = _get_json(session, f"/project/{project['id']}/rumPageViews", headers, params=params)
        if not isinstance(payload, list) or not payload:
            return

        rows = [
            row
            for row in (_normalize_rum_page_view(project_fields, item) for item in payload if isinstance(item, dict))
            if row is not None
        ]
        if not rows:
            return

        yield from rows

        next_to = min(row["date"] for row in rows)
        if next_to == last_to_sent:
            # The oldest row didn't move, so the next request would return the same page.
            return
        last_to_sent = next_to
        to_cutoff = next_to
    else:
        # The watermark still advances to the newest row, so anything older than this cutoff
        # is never fetched again — say so rather than truncating quietly.
        logger.warning(
            "DebugBear page view cap reached; truncating project history",
            project_id=project_fields["project_id"],
            pages=_MAX_PAGES_PER_PROJECT,
            to_cutoff=to_cutoff,
        )


def _iter_annotations_for_project(
    session: Session, headers: dict[str, str], project: dict[str, Any]
) -> Iterator[dict[str, Any]]:
    project_fields = _project_fields(project)
    if project_fields is None:
        return

    payload = _get_json(session, f"/project/{project['id']}/annotations", headers)
    if isinstance(payload, dict):
        payload = payload.get("annotations")
    if not isinstance(payload, list):
        return

    for annotation in payload:
        if not isinstance(annotation, dict):
            continue
        row = {**annotation, **project_fields}
        annotation_id = annotation.get("id")
        # The list response shape isn't documented, so fall back to a content id rather than
        # dropping an annotation that arrives without one.
        row["id"] = str(annotation_id) if annotation_id is not None else _content_id(row)
        yield row


def debugbear_source(
    api_key: str,
    endpoint: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    headers = _auth_headers(api_key)
    session = _session(api_key)

    incremental_since: datetime | None = None
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        incremental_since = _parse_datetime(db_incremental_field_last_value)

    if endpoint == "Projects":

        def _iter_project_rows() -> Iterator[dict[str, Any]]:
            yield from _iter_projects(session, headers)

        return SourceResponse(
            name="projects",
            items=_iter_project_rows,
            primary_keys=["id"],
            sort_mode="asc",
        )

    if endpoint == "Pages":

        def _iter_page_rows() -> Iterator[dict[str, Any]]:
            yield from _iter_pages(session, headers)

        return SourceResponse(
            name="pages",
            items=_iter_page_rows,
            primary_keys=["project_id", "id"],
            sort_mode="asc",
        )

    if endpoint == "PageMetrics":

        def _iter_page_metrics_rows() -> Iterator[dict[str, Any]]:
            for project in _iter_projects(session, headers):
                yield from _iter_page_metrics_for_project(session, headers, project, incremental_since)

        return SourceResponse(
            name="page_metrics",
            items=_iter_page_metrics_rows,
            primary_keys=["project_id", "page_id", "analysis_date"],
            sort_mode="desc",
            partition_count=1,
            partition_size=1,
            partition_mode="datetime",
            partition_format="week",
            partition_keys=["analysis_date"],
        )

    if endpoint == "RumMetrics":

        def _iter_rum_metrics_rows() -> Iterator[dict[str, Any]]:
            for project in _iter_projects(session, headers):
                yield from _iter_rum_metrics_for_project(session, headers, project, incremental_since)

        return SourceResponse(
            name="rum_metrics",
            items=_iter_rum_metrics_rows,
            primary_keys=["project_id", "metric", "date"],
            # Buckets ascend within a project but the stream restarts at each project, so the
            # watermark must only advance once every project has been read.
            sort_mode="desc",
            partition_count=1,
            partition_size=1,
            partition_mode="datetime",
            partition_format="month",
            partition_keys=["date"],
        )

    if endpoint == "RumPageViews":

        def _iter_rum_page_view_rows() -> Iterator[dict[str, Any]]:
            for project in _iter_projects(session, headers):
                yield from _iter_rum_page_views_for_project(session, headers, project, incremental_since)

        return SourceResponse(
            name="rum_page_views",
            items=_iter_rum_page_view_rows,
            primary_keys=["project_id", "id"],
            sort_mode="desc",
            partition_count=1,
            partition_size=1,
            partition_mode="datetime",
            partition_format="week",
            partition_keys=["date"],
        )

    if endpoint == "Annotations":

        def _iter_annotation_rows() -> Iterator[dict[str, Any]]:
            for project in _iter_projects(session, headers):
                yield from _iter_annotations_for_project(session, headers, project)

        return SourceResponse(
            name="annotations",
            items=_iter_annotation_rows,
            primary_keys=["project_id", "id"],
            sort_mode="asc",
        )

    raise ValueError(f"Unknown DebugBear endpoint: {endpoint}")
