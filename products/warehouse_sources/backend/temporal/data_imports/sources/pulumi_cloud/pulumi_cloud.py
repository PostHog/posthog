import dataclasses
from collections.abc import Iterator
from datetime import date, datetime
from typing import Any, Optional
from urllib.parse import quote

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.pulumi_cloud.settings import (
    PULUMI_CLOUD_ENDPOINTS,
    PulumiCloudEndpointConfig,
)

PULUMI_CLOUD_BASE_URL = "https://api.pulumi.com"
PAGE_SIZE = 100
# Bound every paginator so a misbehaving API can't loop forever.
MAX_PAGES = 10_000
# Incremental stack_updates re-pulls a trailing window below the watermark: the watermark is the max
# startTime seen, and an update that was still in-progress at the previous sync only flips its
# `result` once it completes — without the overlap that completion would never be re-fetched. Merge
# dedupes the re-pulled rows on the primary key. Updates rarely run longer than a day.
STACK_UPDATES_LOOKBACK_SECONDS = 24 * 60 * 60
# Small overlap below the audit-log watermark: the spec doesn't state whether the server-side
# `startTime` lower bound is inclusive, so re-pull a window rather than risk dropping events that
# share the watermark second. Merge dedupes on the composite primary key.
AUDIT_LOGS_LOOKBACK_SECONDS = 15 * 60


class PulumiCloudRetryableError(Exception):
    pass


@dataclasses.dataclass
class PulumiCloudResumeConfig:
    # Opaque pagination token to resume from: the `continuationToken` for stacks/audit logs, or the
    # resource-search `cursor`. None means "start from the first page".
    next_token: str | None = None
    # 1-based page number to resume the deployments listing from.
    page: int | None = None
    # Stable "org/project/stack" keys of the fan-out stacks already fully processed in an earlier
    # attempt of this job. We resume by processing any stack NOT in this set, so a stack created
    # between a crash and the retry is picked up rather than silently skipped (fan-out persists the
    # incremental watermark only at successful job end, so a skipped stack's older updates would
    # never be fetched again outside the trailing lookback window).
    completed_stack_keys: list[str] = dataclasses.field(default_factory=list)


def _get_headers(access_token: str) -> dict[str, str]:
    # Pulumi Cloud requires the versioned vnd.pulumi Accept header alongside the token.
    return {
        "Authorization": f"token {access_token}",
        "Accept": "application/vnd.pulumi+8",
        "Content-Type": "application/json",
    }


def _as_unix_seconds(value: Any) -> int | None:
    """Coerce a stored incremental watermark into unix seconds, or None when not coercible."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return int(value)
    if isinstance(value, datetime):
        return int(value.timestamp())
    if isinstance(value, date):
        return int(datetime(value.year, value.month, value.day).timestamp())
    if isinstance(value, str):
        try:
            return int(float(value))
        except ValueError:
            return None
    return None


@retry(
    retry=retry_if_exception_type(
        (
            PulumiCloudRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    params: Optional[dict[str, Any]] = None,
) -> Any:
    response = session.get(url, headers=headers, params=params, timeout=60)

    if response.status_code == 429 or response.status_code >= 500:
        raise PulumiCloudRetryableError(f"Pulumi Cloud API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        # Log only status and URL — never the response body. Pulumi error bodies can echo
        # request-specific data (stack config keys, audit descriptions), which must not spill into
        # application logs where access is broader than the source data itself.
        logger.error(f"Pulumi Cloud API error: status={response.status_code}, url={url}")
        response.raise_for_status()

    return response.json()


def validate_credentials(access_token: str) -> bool:
    """Probe the token with the cheapest account-level call. GET /api/user needs no org access, so a
    200 confirms the token is genuine; a 401 means it is invalid or revoked."""
    try:
        response = make_tracked_session(redact_values=(access_token,), capture=False).get(
            f"{PULUMI_CLOUD_BASE_URL}/api/user", headers=_get_headers(access_token), timeout=10
        )
        return response.status_code == 200
    except Exception:
        return False


def _format_path(path: str, org: str, project: str | None = None, stack: str | None = None) -> str:
    return path.format(
        org=quote(org, safe=""),
        project=quote(project, safe="") if project is not None else "",
        stack=quote(stack, safe="") if stack is not None else "",
    )


def _iter_stack_pages(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    organization: str,
    start_token: str | None = None,
) -> Iterator[tuple[list[dict[str, Any]], str | None]]:
    """Page through GET /api/user/stacks for the organization, yielding (stacks, next_token) pairs.

    A nil continuationToken in the response signals the final page.
    """
    token = start_token
    for _ in range(MAX_PAGES):
        params: dict[str, Any] = {"organization": organization, "maxResults": PAGE_SIZE}
        if token:
            params["continuationToken"] = token
        data = _fetch(session, f"{PULUMI_CLOUD_BASE_URL}/api/user/stacks", headers, logger, params=params)
        stacks = data.get("stacks", [])
        token = data.get("continuationToken") or None
        yield stacks, token
        if not token:
            return
    logger.warning(f"Pulumi Cloud: stack listing hit the page cap ({MAX_PAGES}) for org={organization}")


def _get_stack_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    organization: str,
    resumable_source_manager: ResumableSourceManager[PulumiCloudResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_token = resume.next_token if resume else None

    for stacks, next_token in _iter_stack_pages(session, headers, logger, organization, start_token=start_token):
        if stacks:
            yield stacks
        # Save AFTER yielding (and only when more pages remain) so a crash re-yields the last page
        # rather than skipping it — merge dedupes on the primary key.
        if next_token:
            resumable_source_manager.save_state(PulumiCloudResumeConfig(next_token=next_token))


def _flatten_update(item: dict[str, Any], org: str, project: str, stack: str) -> dict[str, Any]:
    """Flatten an UpdateInfo item (nested `info` from the Pulumi CLI) into one flat row, injecting
    the stack coordinates the composite primary key needs."""
    row = dict(item)
    info = row.pop("info", None)
    if isinstance(info, dict):
        merged = dict(info)
        # The raw deployment state snapshot can be enormous and is not list-level data.
        merged.pop("deployment", None)
        merged.update(row)
        row = merged
    row["orgName"] = org
    row["projectName"] = project
    row["stackName"] = stack
    return row


def _get_single_stack_update_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    config: PulumiCloudEndpointConfig,
    org: str,
    project: str,
    stack: str,
    watermark: int | None,
) -> Iterator[list[dict[str, Any]]]:
    """Page through one stack's update history (newest-first), stopping early at the watermark.

    The endpoint has no server-side time filter, but its paginated format returns updates
    newest-first, so once any row on a page predates the watermark every later page is older and
    pagination can stop — an incremental sync only pays for the new pages.
    """
    url = f"{PULUMI_CLOUD_BASE_URL}{_format_path(config.path, org, project, stack)}"
    page = 1
    while page <= MAX_PAGES:
        # `output-type=service` selects the paginated response format ({updates, itemsPerPage, total});
        # unset returns a legacy unpaginated format.
        data = _fetch(
            session, url, headers, logger, params={"output-type": "service", "page": page, "pageSize": PAGE_SIZE}
        )
        updates = data.get("updates", [])
        if not updates:
            return

        rows = [_flatten_update(item, org, project, stack) for item in updates]

        if watermark is not None:
            kept = [row for row in rows if not isinstance(row.get("startTime"), int) or row["startTime"] >= watermark]
            if kept:
                yield kept
            start_times = [row["startTime"] for row in rows if isinstance(row.get("startTime"), int)]
            # Newest-first: if this page already reaches below the watermark, every later page is older.
            if start_times and min(start_times) < watermark:
                return
        else:
            yield rows

        if len(updates) < PAGE_SIZE:
            return
        page += 1
    logger.warning(f"Pulumi Cloud: stack_updates hit the page cap ({MAX_PAGES}) for {org}/{project}/{stack}")


def _get_stack_update_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    organization: str,
    resumable_source_manager: ResumableSourceManager[PulumiCloudResumeConfig],
    config: PulumiCloudEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    stacks = [stack for page, _ in _iter_stack_pages(session, headers, logger, organization) for stack in page]

    watermark: int | None = None
    if should_use_incremental_field:
        last_value = _as_unix_seconds(db_incremental_field_last_value)
        if last_value is not None:
            watermark = last_value - STACK_UPDATES_LOOKBACK_SECONDS

    # Resume by skipping only stacks already fully processed in an earlier attempt of this job.
    # Within a stack we always re-fetch from the first page; merge dedupes re-pulled rows.
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    completed_stack_keys = list(resume.completed_stack_keys) if resume is not None else []
    completed = set(completed_stack_keys)

    for stack_summary in stacks:
        org = stack_summary.get("orgName")
        project = stack_summary.get("projectName")
        stack = stack_summary.get("stackName")
        if not org or not project or not stack:
            continue
        stack_key = f"{org}/{project}/{stack}"
        if stack_key in completed:
            logger.debug(f"Pulumi Cloud: skipping already-processed stack={stack_key} for stack_updates fan-out")
            continue

        yield from _get_single_stack_update_rows(session, headers, logger, config, org, project, stack, watermark)

        # Mark this stack done so a crash resumes with the stacks still owed. Saved AFTER yielding
        # this stack's pages so a crash mid-stack re-processes it (merge dedupes) rather than skipping it.
        completed_stack_keys.append(stack_key)
        completed.add(stack_key)
        resumable_source_manager.save_state(PulumiCloudResumeConfig(completed_stack_keys=list(completed_stack_keys)))


def _get_deployment_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    organization: str,
    resumable_source_manager: ResumableSourceManager[PulumiCloudResumeConfig],
    config: PulumiCloudEndpointConfig,
) -> Iterator[list[dict[str, Any]]]:
    url = f"{PULUMI_CLOUD_BASE_URL}{_format_path(config.path, organization)}"

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.page if resume is not None and resume.page else 1

    while page <= MAX_PAGES:
        data = _fetch(session, url, headers, logger, params={"page": page, "pageSize": PAGE_SIZE})
        deployments = data.get("deployments", [])
        if not deployments:
            return
        yield deployments
        if len(deployments) < PAGE_SIZE:
            return
        page += 1
        resumable_source_manager.save_state(PulumiCloudResumeConfig(page=page))
    logger.warning(f"Pulumi Cloud: deployments hit the page cap ({MAX_PAGES}) for org={organization}")


def _get_audit_log_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    organization: str,
    resumable_source_manager: ResumableSourceManager[PulumiCloudResumeConfig],
    config: PulumiCloudEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    url = f"{PULUMI_CLOUD_BASE_URL}{_format_path(config.path, organization)}"

    base_params: dict[str, Any] = {}
    if should_use_incremental_field:
        last_value = _as_unix_seconds(db_incremental_field_last_value)
        if last_value is not None:
            # The v2 endpoint's startTime is a server-side lower bound on the query range.
            base_params["startTime"] = max(last_value - AUDIT_LOGS_LOOKBACK_SECONDS, 0)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    token = resume.next_token if resume else None

    for _ in range(MAX_PAGES):
        params = dict(base_params)
        if token:
            params["continuationToken"] = token
        data = _fetch(session, url, headers, logger, params=params)
        events = data.get("auditLogEvents", [])
        token = data.get("continuationToken") or None
        if events:
            yield events
            if token:
                resumable_source_manager.save_state(PulumiCloudResumeConfig(next_token=token))
        if not token:
            return
    logger.warning(f"Pulumi Cloud: audit_logs hit the page cap ({MAX_PAGES}) for org={organization}")


def _get_resource_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    organization: str,
    resumable_source_manager: ResumableSourceManager[PulumiCloudResumeConfig],
    config: PulumiCloudEndpointConfig,
) -> Iterator[list[dict[str, Any]]]:
    url = f"{PULUMI_CLOUD_BASE_URL}{_format_path(config.path, organization)}"

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor = resume.next_token if resume else None

    for _ in range(MAX_PAGES):
        params: dict[str, Any] = {"size": PAGE_SIZE}
        if cursor:
            params["cursor"] = cursor
        data = _fetch(session, url, headers, logger, params=params)
        resources = data.get("resources", [])
        if not resources:
            return
        yield resources
        # The response carries both a `next` link and an opaque `cursor`; an absent `next` link
        # signals the final page (the cursor may still be echoed back on it).
        pagination = data.get("pagination") or {}
        cursor = pagination.get("cursor") if pagination.get("next") else None
        if not cursor:
            return
        resumable_source_manager.save_state(PulumiCloudResumeConfig(next_token=cursor))
    logger.warning(f"Pulumi Cloud: resources hit the page cap ({MAX_PAGES}) for org={organization}")


def get_rows(
    access_token: str,
    organization: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PulumiCloudResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = PULUMI_CLOUD_ENDPOINTS[endpoint]
    headers = _get_headers(access_token)
    # One session reused across every page (and, for fan-out, every stack) so urllib3 keeps the
    # connection alive. Register the token for value-based redaction so it can't surface in logged
    # URLs, and disable sample capture: responses carry arbitrary infrastructure data (stack config,
    # environment variables, audit descriptions) that the name-based scrubber can't sanitise.
    session = make_tracked_session(redact_values=(access_token,), capture=False)

    if endpoint == "stacks":
        yield from _get_stack_rows(session, headers, logger, organization, resumable_source_manager)
    elif endpoint == "stack_updates":
        yield from _get_stack_update_rows(
            session,
            headers,
            logger,
            organization,
            resumable_source_manager,
            config,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )
    elif endpoint == "deployments":
        yield from _get_deployment_rows(session, headers, logger, organization, resumable_source_manager, config)
    elif endpoint == "audit_logs":
        yield from _get_audit_log_rows(
            session,
            headers,
            logger,
            organization,
            resumable_source_manager,
            config,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )
    elif endpoint == "resources":
        yield from _get_resource_rows(session, headers, logger, organization, resumable_source_manager, config)
    else:
        raise ValueError(f"Unknown Pulumi Cloud endpoint: {endpoint}")


def pulumi_cloud_source(
    access_token: str,
    organization: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PulumiCloudResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = PULUMI_CLOUD_ENDPOINTS[endpoint]

    # stack_updates and audit_logs arrive newest-first; stack_updates additionally fans out per
    # stack, so its watermark must persist only at successful job end (a partial run's max says
    # nothing about stacks it never reached). Deployments also list newest-first by default.
    descending_endpoints = {"stack_updates", "audit_logs", "deployments"}

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            access_token=access_token,
            organization=organization,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=config.primary_keys,
        sort_mode="desc" if endpoint in descending_endpoints else "asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
