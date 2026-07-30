import re
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.prefect_cloud.settings import (
    PAGE_LIMIT,
    PREFECT_CLOUD_ENDPOINTS,
    PrefectCloudEndpointConfig,
)

PREFECT_CLOUD_API_BASE = "https://api.prefect.cloud/api"

# Account and workspace IDs are UUIDs embedded in the request path. Rejecting anything else keeps
# user input from rewriting the path (e.g. `../` traversal into another account's routes).
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class PrefectCloudRetryableError(Exception):
    pass


@dataclasses.dataclass
class PrefectCloudResumeConfig:
    # Row offset of the next page to fetch. 0 means "start from the first page".
    offset: int = 0


def normalize_uuid(value: str, label: str) -> str:
    """Reduce user input to a bare lowercase UUID, raising ``ValueError`` on anything else."""
    cleaned = value.strip().lower()
    if not _UUID_RE.match(cleaned):
        raise ValueError(
            f"Invalid Prefect Cloud {label}: {value!r}. Copy the UUID from your workspace URL: "
            "https://app.prefect.cloud/account/<account ID>/workspace/<workspace ID>."
        )
    return cleaned


def _workspace_url(account_id: str, workspace_id: str) -> str:
    account = normalize_uuid(account_id, "account ID")
    workspace = normalize_uuid(workspace_id, "workspace ID")
    return f"{PREFECT_CLOUD_API_BASE}/accounts/{account}/workspaces/{workspace}"


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}


def _format_after(value: Any) -> str:
    """Format an incremental cursor as the ISO 8601 UTC string Prefect's `after_` filters expect.

    Microseconds are truncated, which can only shift the cursor slightly earlier — the re-pulled
    boundary rows are deduped on the primary key at merge.
    """
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def _resolve_incremental_sort(config: PrefectCloudEndpointConfig, incremental_field: str | None) -> tuple[str, str]:
    """Pick the (filter field, ascending sort) pair, honoring the user's chosen cursor field."""
    if incremental_field and incremental_field in config.incremental_sorts:
        return incremental_field, config.incremental_sorts[incremental_field]
    first = next(iter(config.incremental_sorts))
    return first, config.incremental_sorts[first]


def _build_request_body(
    config: PrefectCloudEndpointConfig,
    offset: int,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    """Build the POST body for one page. Prefect's filter endpoints take filter, sort, limit, and
    offset in the JSON body (not query params), so the same watermark filter rides every page."""
    body: dict[str, Any] = {"limit": PAGE_LIMIT, "offset": offset}
    sort = config.sort

    if (
        config.filter_key
        and config.incremental_sorts
        and should_use_incremental_field
        and db_incremental_field_last_value is not None
    ):
        field_name, sort = _resolve_incremental_sort(config, incremental_field)
        body[config.filter_key] = {field_name: {"after_": _format_after(db_incremental_field_last_value)}}

    if sort:
        body["sort"] = sort
    return body


@retry(
    retry=retry_if_exception_type(
        (PrefectCloudRetryableError, requests.ReadTimeout, requests.ConnectionError),
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    url: str,
    body: dict[str, Any],
    headers: dict[str, str],
    logger: FilteringBoundLogger,
) -> list[dict[str, Any]]:
    response = session.post(url, json=body, headers=headers, timeout=60)

    # Prefect Cloud rate limits per workspace; 429 and transient 5xx are worth backing off on.
    if response.status_code == 429 or response.status_code >= 500:
        raise PrefectCloudRetryableError(
            f"Prefect Cloud API error (retryable): status={response.status_code}, url={url}"
        )

    if not response.ok:
        logger.error(f"Prefect Cloud API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def get_rows(
    account_id: str,
    workspace_id: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PrefectCloudResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[Any]:
    config = PREFECT_CLOUD_ENDPOINTS[endpoint]
    url = f"{_workspace_url(account_id, workspace_id)}{config.path}"
    headers = _headers(api_key)
    session = make_tracked_session()

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    offset = resume.offset if resume is not None else 0
    if offset:
        logger.debug(f"Prefect Cloud: resuming {endpoint} from offset {offset}")

    while True:
        body = _build_request_body(
            config, offset, should_use_incremental_field, db_incremental_field_last_value, incremental_field
        )
        items = _fetch_page(session, url, body, headers, logger)
        if not items:
            break

        yield items
        offset += len(items)

        # A short page is the last one. Checkpoint only while more pages remain, and save AFTER
        # yielding so a crash re-yields the last page rather than skipping it — merge dedupes on
        # the primary key.
        if len(items) < PAGE_LIMIT:
            break
        resumable_source_manager.save_state(PrefectCloudResumeConfig(offset=offset))


def prefect_cloud_source(
    account_id: str,
    workspace_id: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PrefectCloudResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = PREFECT_CLOUD_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            account_id=account_id,
            workspace_id=workspace_id,
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(account_id: str, workspace_id: str, api_key: str) -> tuple[bool, int | None]:
    """Probe the workspace's flows/filter endpoint to confirm the key reaches the workspace.

    Returns ``(ok, status_code)``. ``status_code`` is ``None`` on a transport error. Raises
    ``ValueError`` if either ID is malformed so the caller can surface a precise message.
    """
    url = f"{_workspace_url(account_id, workspace_id)}/flows/filter"
    try:
        response = make_tracked_session().post(url, json={"limit": 1}, headers=_headers(api_key), timeout=10)
    except Exception:
        return False, None
    return response.status_code == 200, response.status_code
