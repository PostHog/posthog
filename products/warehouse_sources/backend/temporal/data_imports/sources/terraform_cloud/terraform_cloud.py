import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import quote, urlencode, urljoin

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.terraform_cloud.settings import (
    TERRAFORM_CLOUD_ENDPOINTS,
    TerraformCloudEndpointConfig,
)

TERRAFORM_CLOUD_HOST = "https://app.terraform.io"
TERRAFORM_CLOUD_BASE_URL = f"{TERRAFORM_CLOUD_HOST}/api/v2"
PAGE_SIZE = 100  # API maximum for page[size]


class TerraformCloudRetryableError(Exception):
    """Raised for responses that are safe to retry (429 / 5xx)."""


@dataclasses.dataclass
class TerraformCloudResumeConfig:
    # Next page URL to fetch. None means "start the current list at its first page" — used when
    # the fan-out bookmark advances to a workspace whose first page URL is built when reached.
    next_url: str | None = None
    # The workspace currently being processed during a fan-out. A stable id bookmark (not a
    # positional index) so workspaces added/removed between a crash and the retry can't resume
    # us into the wrong workspace. None for top-level endpoints.
    workspace_id: str | None = None


def _get_headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_token}",
        "Accept": "application/vnd.api+json",
    }


def _make_session(api_token: str) -> requests.Session:
    """Session for all HCP Terraform traffic. The bearer token is set once on the session so its
    redaction policy applies everywhere, redirects are pinned off so a credentialed request can't
    be replayed against another host, and response capture is disabled because state-version rows
    carry signed state-file download URLs (valid ~25h) that must not land in captured samples."""
    return make_tracked_session(
        headers=_get_headers(api_token),
        redact_values=(api_token,),
        allow_redirects=False,
        capture=False,
    )


@retry(
    retry=retry_if_exception_type(
        (
            TerraformCloudRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_json(session: requests.Session, url: str, logger: FilteringBoundLogger) -> dict[str, Any]:
    # The API throttles at ~30 req/s per token and signals it with a 429.
    response = session.get(url, timeout=60)

    if response.status_code == 429 or response.status_code >= 500:
        raise TerraformCloudRetryableError(
            f"HCP Terraform API error (retryable): status={response.status_code}, url={url}"
        )

    if not response.ok:
        # 404 is expected during the fan-out (a workspace deleted mid-sync) and handled there.
        log = logger.warning if response.status_code == 404 else logger.error
        log(f"HCP Terraform API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _normalize_key(key: str) -> str:
    return key.replace("-", "_")


def _normalize_keys(value: Any) -> Any:
    """JSON:API attribute keys are kebab-case ("created-at"); normalize them (recursively) to
    snake_case so warehouse columns are queryable and incremental fields match row keys."""
    if isinstance(value, dict):
        return {_normalize_key(k): _normalize_keys(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize_keys(v) for v in value]
    return value


def _flatten_item(item: dict[str, Any], drop_fields: tuple[str, ...] = ()) -> dict[str, Any]:
    """Flatten a JSON:API resource object into a row: id + type + normalized attributes, with
    each to-one relationship reduced to a `<name>_id` column (e.g. plan_id, workspace_id).
    `drop_fields` removes attributes that must never be persisted — state versions carry signed
    state-file download/upload URLs that would grant raw state access to anyone who can query
    the warehouse table."""
    row: dict[str, Any] = {"id": item["id"], "type": item.get("type")}
    attributes = item.get("attributes") or {}
    if isinstance(attributes, dict):
        row.update(_normalize_keys(attributes))
    for field in drop_fields:
        row.pop(field, None)
    relationships = item.get("relationships") or {}
    if isinstance(relationships, dict):
        for rel_name, rel in relationships.items():
            data = rel.get("data") if isinstance(rel, dict) else None
            if isinstance(data, dict) and data.get("id"):
                row[f"{_normalize_key(rel_name)}_id"] = data["id"]
    return row


def _data_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    """JSON:API `data` is a list for collection endpoints but a single resource object for
    individual-resource endpoints (e.g. the configured organization); normalize both to a list."""
    payload = data.get("data")
    if isinstance(payload, dict):
        return [payload]
    return payload or []


def _next_url(data: dict[str, Any]) -> str | None:
    """Resolve the JSON:API `links.next` pagination URL, tolerating both the absolute URLs the
    API returns today and spec-allowed relative ones."""
    next_link = (data.get("links") or {}).get("next")
    if not next_link:
        return None
    return urljoin(TERRAFORM_CLOUD_HOST, next_link)


def _build_url(path: str, params: dict[str, Any]) -> str:
    return f"{TERRAFORM_CLOUD_BASE_URL}{path}?{urlencode(params)}"


def _parse_created_at(row: dict[str, Any]) -> datetime | None:
    value = row.get("created_at")
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _incremental_cutoff(last_value: Any, lookback: timedelta | None) -> datetime | None:
    """Turn the persisted watermark into the datetime below which pagination stops."""
    if isinstance(last_value, str):
        try:
            last_value = datetime.fromisoformat(last_value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if isinstance(last_value, datetime):
        cutoff = last_value if last_value.tzinfo else last_value.replace(tzinfo=UTC)
    elif isinstance(last_value, date):
        cutoff = datetime.combine(last_value, datetime.min.time(), tzinfo=UTC)
    else:
        return None
    return cutoff - lookback if lookback else cutoff


def _page_predates_cutoff(rows: list[dict[str, Any]], cutoff: datetime | None) -> bool:
    """True when every parseable created_at on the page is older than the cutoff — the signal to
    stop paginating a newest-first list on an incremental sync. Yielding the boundary page itself
    is harmless: merge dedupes re-pulled rows on the primary key."""
    if cutoff is None:
        return False
    parsed = [ts for ts in (_parse_created_at(row) for row in rows) if ts is not None]
    return bool(parsed) and max(parsed) < cutoff


def _iter_workspaces(
    session: requests.Session, organization: str, logger: FilteringBoundLogger
) -> Iterator[dict[str, Any]]:
    """Page through the organization's workspaces, yielding raw JSON:API workspace objects."""
    url: str | None = _build_url(f"/organizations/{quote(organization, safe='')}/workspaces", {"page[size]": PAGE_SIZE})
    while url:
        data = _fetch_json(session, url, logger)
        yield from _data_items(data)
        url = _next_url(data)


def _get_top_level_rows(
    session: requests.Session,
    organization: str,
    config: TerraformCloudEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[TerraformCloudResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.next_url:
        url: str | None = resume.next_url
        logger.debug(f"HCP Terraform: resuming {config.name} from URL: {resume.next_url}")
    else:
        path = config.path.format(organization=quote(organization, safe=""))
        url = _build_url(path, {"page[size]": PAGE_SIZE})

    while url:
        data = _fetch_json(session, url, logger)
        rows = [_flatten_item(item, config.drop_fields) for item in _data_items(data)]
        next_url = _next_url(data)
        if rows:
            yield rows
            # Save AFTER yielding (and only when more pages remain) so a crash re-yields the last
            # page rather than skipping it — merge dedupes on the primary key.
            if next_url:
                resumable_source_manager.save_state(TerraformCloudResumeConfig(next_url=next_url))
        url = next_url


def _first_child_url(
    config: TerraformCloudEndpointConfig, organization: str, workspace_id: str, workspace_name: str
) -> str:
    path = config.path.format(organization=quote(organization, safe=""), workspace_id=quote(workspace_id, safe=""))
    params: dict[str, Any] = {
        key: value.format(organization=organization, workspace_id=workspace_id, workspace_name=workspace_name)
        for key, value in config.params.items()
    }
    params["page[size]"] = PAGE_SIZE
    return _build_url(path, params)


def _get_fan_out_rows(
    session: requests.Session,
    organization: str,
    config: TerraformCloudEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[TerraformCloudResumeConfig],
    cutoff: datetime | None,
) -> Iterator[list[dict[str, Any]]]:
    """Fan out over every workspace in the organization and page through the child endpoint.

    Each row is stamped with `workspace_id`/`workspace_name` so child tables join back to their
    parent workspace without unpacking relationships. Run and state-version ids are globally
    unique, so `id` alone stays a valid table-wide primary key.
    """
    workspaces = list(_iter_workspaces(session, organization, logger))

    # Resolve the saved workspace bookmark to the slice still to process. If the bookmarked
    # workspace no longer exists (deleted between attempts), start over from the first one —
    # merge dedupes the re-pulled rows on the primary key. `resume_url` seeds the first
    # workspace only.
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = workspaces
    resume_url: str | None = None
    if resume is not None and resume.workspace_id is not None:
        workspace_ids = [workspace["id"] for workspace in workspaces]
        if resume.workspace_id in workspace_ids:
            remaining = workspaces[workspace_ids.index(resume.workspace_id) :]
            resume_url = resume.next_url
            logger.debug(
                f"HCP Terraform: resuming {config.name} from workspace_id={resume.workspace_id}, url={resume_url}"
            )

    for index, workspace in enumerate(remaining):
        workspace_id = workspace["id"]
        workspace_name = (workspace.get("attributes") or {}).get("name") or ""

        url: str | None = resume_url or _first_child_url(config, organization, workspace_id, workspace_name)
        resume_url = None  # only the resumed-into workspace uses the saved URL

        try:
            while url:
                data = _fetch_json(session, url, logger)
                rows = []
                for item in _data_items(data):
                    row = _flatten_item(item, config.drop_fields)
                    row["workspace_id"] = workspace_id
                    row["workspace_name"] = workspace_name
                    rows.append(row)
                next_url = _next_url(data)

                if rows:
                    yield rows
                    if next_url:
                        resumable_source_manager.save_state(
                            TerraformCloudResumeConfig(next_url=next_url, workspace_id=workspace_id)
                        )

                # Both child lists return newest-first with no server-side time filter, so an
                # incremental sync must terminate at the watermark client-side — otherwise every
                # sync re-walks each workspace's full history.
                if _page_predates_cutoff(rows, cutoff):
                    break
                url = next_url
        except requests.HTTPError as exc:
            # A workspace deleted between enumeration and this fetch 404s. Skip it rather than
            # failing the whole sync; any other HTTP error is re-raised.
            if exc.response is not None and exc.response.status_code == 404:
                logger.warning(f"HCP Terraform: workspace {workspace_id} not found while fetching {config.name}")
            else:
                raise

        # Advance the bookmark so a crash between workspaces resumes at the next one.
        if index + 1 < len(remaining):
            resumable_source_manager.save_state(
                TerraformCloudResumeConfig(next_url=None, workspace_id=remaining[index + 1]["id"])
            )


def get_rows(
    api_token: str,
    organization: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[TerraformCloudResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = TERRAFORM_CLOUD_ENDPOINTS.get(endpoint)
    if config is None:
        raise ValueError(f"Unknown HCP Terraform endpoint: {endpoint}")

    session = _make_session(api_token)

    if config.fan_out_over_workspaces:
        cutoff = (
            _incremental_cutoff(db_incremental_field_last_value, config.incremental_lookback)
            if should_use_incremental_field
            else None
        )
        yield from _get_fan_out_rows(session, organization, config, logger, resumable_source_manager, cutoff)
    else:
        yield from _get_top_level_rows(session, organization, config, logger, resumable_source_manager)


def terraform_cloud_source(
    api_token: str,
    organization: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[TerraformCloudResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    endpoint_config = TERRAFORM_CLOUD_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            organization=organization,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=endpoint_config.primary_keys,
        # Fan-out lists arrive newest-first per workspace; desc mode makes the pipeline persist
        # the incremental watermark only at successful job end, since a partial run's max says
        # nothing about workspaces it never reached.
        sort_mode=endpoint_config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )


def validate_credentials(api_token: str, organization: str) -> tuple[bool, str | None]:
    """Single cheap probe: show the configured organization. Confirms the token is genuine and
    can see the org in one request. The API returns 404 (not 403) for an organization the token
    can't access, so both "wrong name" and "no access" surface as the same message."""
    try:
        response = _make_session(api_token).get(
            f"{TERRAFORM_CLOUD_BASE_URL}/organizations/{quote(organization, safe='')}", timeout=10
        )
    except Exception:
        return False, "Could not connect to HCP Terraform"

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid HCP Terraform API token"
    if response.status_code == 404:
        return False, f"Organization '{organization}' was not found or your API token cannot access it"
    return False, f"HCP Terraform returned an unexpected status: {response.status_code}"
