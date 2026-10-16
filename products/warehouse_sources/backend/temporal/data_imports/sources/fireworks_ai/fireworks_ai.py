import re
import hashlib
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.fireworks_ai.settings import (
    ACCOUNT_USAGE,
    FIREWORKS_AI_ENDPOINTS,
    PAGE_SIZE,
    USAGE_BACKFILL_DAYS,
    USAGE_MAX_WINDOW_DAYS,
    FireworksAIEndpointConfig,
)

FIREWORKS_AI_BASE_URL = "https://api.fireworks.ai/v1"

_ACCOUNT_ID_REGEX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")

# The billingUsage response splits its buckets across three arrays, one per billed surface, each
# with its own field set. They become one table keyed on a synthesized `id`, with `usageCategory`
# naming which array a row came from.
_USAGE_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("serverlessCosts", "serverless"),
    ("dedicatedCosts", "dedicated"),
    ("trainingCosts", "training"),
)

# Fields that identify a usage bucket within its category, per the billingUsage response schema.
# Only these, the window and the `group` map feed the synthesized id, never the metric values, so a
# bucket whose metrics are restated between syncs keeps its id and merge updates it in place
# instead of inserting a duplicate.
_USAGE_DIMENSIONS: dict[str, tuple[str, ...]] = {
    "serverless": ("modelName", "usageType", "apiKeyId"),
    "dedicated": ("deploymentId", "acceleratorType", "baseModel", "usageType", "placement"),
    "training": ("jobId", "trainingSessionId", "jobType", "usageType", "acceleratorType", "baseModel"),
}


@frozen
class FireworksAIResumeConfig:
    # Opaque nextPageToken from the last committed page. The API requires all other params to
    # match the original call, so the transport re-sends the same pageSize alongside it.
    page_token: str = ""
    # ISO 8601 start of the first billingUsage window not yet yielded. The usage report paginates
    # by time window rather than page token, so it checkpoints on its own field.
    usage_window_start: str = ""


@frozen
class UsageWindow:
    """One billingUsage request range. `end` is exclusive, matching the API's endTime."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.start >= self.end:
            raise ValueError(f"Usage window must start before it ends, got {self.start} to {self.end}")


def normalize_account_id(account_id: str) -> str:
    """Reduce whatever the user entered to the bare Fireworks account id.

    Users may paste the full resource prefix ("accounts/my-account") shown throughout the
    Fireworks docs and firectl output. Without normalizing, the request path becomes
    /v1/accounts/accounts/my-account/... which can never resolve.
    """
    account_id = account_id.strip().strip("/")
    if account_id.startswith("accounts/"):
        account_id = account_id[len("accounts/") :]
    return account_id


def is_valid_account_id(account_id: str) -> bool:
    return _ACCOUNT_ID_REGEX.match(account_id) is not None


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _format_rfc3339(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _as_utc_datetime(value: Any) -> datetime:
    """Resolve an incremental watermark to an aware UTC datetime."""
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    # datetime subclasses date, so a bare date only reaches here after the check above.
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    return datetime.fromisoformat(str(value).strip().replace("Z", "+00:00")).astimezone(UTC)


def _usage_row_id(category: str, item: dict[str, Any]) -> str:
    parts: list[Any] = [category, item.get("startTime"), item.get("endTime")]
    parts.extend(item.get(name) for name in _USAGE_DIMENSIONS[category])
    group = item.get("group")
    if isinstance(group, dict):
        parts.extend(f"{key}={group[key]}" for key in sorted(group))
    # Sentinel for None so a missing dimension cannot collide with an empty-string value.
    joined = "|".join("\x00" if part is None else str(part) for part in parts)
    return hashlib.sha256(joined.encode()).hexdigest()


def _usage_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for data_key, category in _USAGE_CATEGORIES:
        for item in payload.get(data_key) or []:
            rows.append({**item, "id": _usage_row_id(category, item), "usageCategory": category})
    # The three arrays are ordered independently, and the batcher can split one window across
    # several chunks. The watermark takes the maximum startTime of each chunk it writes, so
    # without this sort a chunk holding the window's newest bucket would advance the watermark
    # past buckets still waiting in a later chunk, and a crash in between would lose them.
    rows.sort(key=lambda row: str(row.get("startTime") or ""))
    return rows


def _usage_windows(
    db_incremental_field_last_value: Optional[Any],
    now: datetime,
    resume_from: Optional[datetime] = None,
) -> list[UsageWindow]:
    """Resolve the request windows to walk, oldest first.

    A full refresh reaches back `USAGE_BACKFILL_DAYS`; an incremental run starts at the watermark,
    and a resumed run at its checkpoint.
    """
    start = now - timedelta(days=USAGE_BACKFILL_DAYS)
    if db_incremental_field_last_value is not None:
        start = _as_utc_datetime(db_incremental_field_last_value)
    if resume_from is not None:
        start = max(start, resume_from)
    # The newest bucket keeps accumulating until its day closes, so a watermark that has caught up
    # with the clock still has to re-read the current day rather than request an empty window.
    start = min(start, now - timedelta(days=1))

    windows: list[UsageWindow] = []
    while start < now:
        window_end = min(start + timedelta(days=USAGE_MAX_WINDOW_DAYS), now)
        windows.append(UsageWindow(start=start, end=window_end))
        start = window_end
    return windows


def _fetch_usage_window(session: Any, api_key: str, url: str, window: UsageWindow) -> dict[str, Any]:
    response = session.get(
        url,
        params={"startTime": _format_rfc3339(window.start), "endTime": _format_rfc3339(window.end)},
        headers=_get_headers(api_key),
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def _iter_usage_windows(
    api_key: str,
    url: str,
    windows: list[UsageWindow],
    resumable_source_manager: ResumableSourceManager[FireworksAIResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    session = make_tracked_session(redact_values=(api_key,))
    for index, window in enumerate(windows):
        yield _usage_rows(_fetch_usage_window(session, api_key, url, window))
        if index + 1 < len(windows):
            # Checkpoint names the first window not yet yielded, so a restart replays at most the
            # window that was in progress and merge dedupes it on the synthesized id.
            resumable_source_manager.save_state(
                FireworksAIResumeConfig(usage_window_start=windows[index + 1].start.isoformat())
            )


def _resume_usage_window_start(
    resumable_source_manager: ResumableSourceManager[FireworksAIResumeConfig],
) -> Optional[datetime]:
    if not resumable_source_manager.can_resume():
        return None
    resume = resumable_source_manager.load_state()
    if resume is None or not resume.usage_window_start:
        return None
    return _as_utc_datetime(resume.usage_window_start)


def _source_response(
    endpoint_config: FireworksAIEndpointConfig,
    items: Any,
    column_hints: Any = None,
) -> SourceResponse:
    return SourceResponse(
        name=endpoint_config.name,
        items=items,
        primary_keys=endpoint_config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[endpoint_config.partition_key],
        column_hints=column_hints,
    )


def _account_usage_source(
    api_key: str,
    account_id: str,
    endpoint_config: FireworksAIEndpointConfig,
    resumable_source_manager: ResumableSourceManager[FireworksAIResumeConfig],
    db_incremental_field_last_value: Optional[Any],
) -> SourceResponse:
    url = f"{FIREWORKS_AI_BASE_URL}/accounts/{normalize_account_id(account_id)}/{endpoint_config.path}"
    windows = _usage_windows(
        db_incremental_field_last_value,
        datetime.now(UTC),
        resume_from=_resume_usage_window_start(resumable_source_manager),
    )
    return _source_response(
        endpoint_config,
        lambda: _iter_usage_windows(api_key, url, windows, resumable_source_manager),
    )


def fireworks_ai_source(
    api_key: str,
    account_id: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[FireworksAIResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    endpoint_config = FIREWORKS_AI_ENDPOINTS[endpoint]
    if endpoint == ACCOUNT_USAGE:
        return _account_usage_source(
            api_key, account_id, endpoint_config, resumable_source_manager, db_incremental_field_last_value
        )

    path = f"accounts/{normalize_account_id(account_id)}/{endpoint_config.path}"

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": FIREWORKS_AI_BASE_URL,
            # Auth (Bearer) is supplied via the framework auth config so the key is redacted from
            # logs and raised error messages; only the non-secret Accept header is set here.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "bearer", "token": api_key},
            # AIP list pagination: nextPageToken in the body echoed back as the pageToken query
            # param; an absent/empty token ends the walk.
            "paginator": JSONResponseCursorPaginator(cursor_path="nextPageToken", cursor_param="pageToken"),
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": path,
                    # pageSize is re-sent on every page; the API requires it to match the original
                    # call alongside the pageToken.
                    "params": {"pageSize": PAGE_SIZE},
                    # Proto3 JSON omits empty repeated fields, so a missing collection key is a
                    # legitimate empty page (not a shape error) — no data_selector_required.
                    "data_selector": endpoint_config.data_key,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.page_token:
            initial_paginator_state = {"cursor": resume.page_token}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(FireworksAIResumeConfig(page_token=str(state["cursor"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return _source_response(endpoint_config, lambda: resource, column_hints=resource.column_hints)


def get_status_code(api_key: str, account_id: str, endpoint: str | None = None) -> int:
    """Cheap probe used by credential validation. Returns the HTTP status code."""
    endpoint_config = FIREWORKS_AI_ENDPOINTS.get(endpoint) if endpoint is not None else None
    if endpoint_config is None:
        # Models is account-scoped and readable by any key — a cheap token + account check.
        endpoint_config = FIREWORKS_AI_ENDPOINTS["models"]

    if endpoint_config.name == ACCOUNT_USAGE:
        # billingUsage rejects a call with no window, so probe the last day instead of asking the
        # collection endpoints' single row.
        now = datetime.now(UTC)
        params: dict[str, Any] = {
            "startTime": _format_rfc3339(now - timedelta(days=1)),
            "endTime": _format_rfc3339(now),
        }
    else:
        params = {"pageSize": 1}

    url = f"{FIREWORKS_AI_BASE_URL}/accounts/{normalize_account_id(account_id)}/{endpoint_config.path}"
    response = make_tracked_session(redact_values=(api_key,)).get(
        url, params=params, headers=_get_headers(api_key), timeout=10
    )
    return response.status_code
