import re
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import quote, urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.settings import (
    AZURE_DEVOPS_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

AZURE_DEVOPS_BASE_URL = "https://dev.azure.com"
API_VERSION = "7.1"
PAGE_SIZE = 200
REQUEST_TIMEOUT_SECONDS = 60
# Rate limiting is 200 TSTUs per identity per sliding 5-minute window; 429s
# carry Retry-After but exponential backoff is sufficient.
MAX_RETRY_ATTEMPTS = 5


class AzureDevOpsRetryableError(Exception):
    pass


class AzureDevOpsAuthError(Exception):
    pass


@dataclasses.dataclass
class AzureDevOpsResumeConfig:
    # Only the org-level work item revisions stream persists resume state —
    # its continuationToken is a purpose-built watermark. Project-fan-out
    # streams restart on retry (merge dedupes on primary keys).
    continuation_token: str


def _get_session(personal_access_token: str) -> requests.Session:
    session = make_tracked_session(redact_values=(personal_access_token,))
    # PATs go in the Basic-auth password with an empty username.
    session.auth = ("", personal_access_token)
    return session


def _validate_organization(organization: str) -> str:
    org = organization.strip().removeprefix("https://").removeprefix("http://")
    org = org.removeprefix("dev.azure.com/").split("/")[0]
    if not re.fullmatch(r"[a-zA-Z0-9._-]+", org):
        raise ValueError(f"Invalid Azure DevOps organization: {organization}")
    return org


def _format_datetime(value: Any) -> str:
    """Format an incremental cursor for Azure DevOps date-time filters (ISO 8601 UTC)."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%dT00:00:00Z")
    return str(value)


def _flatten_revision(item: dict[str, Any]) -> dict[str, Any]:
    # Revision payloads nest everything interesting under `fields`; copy the
    # watermark field to the top level so the pipeline can track it.
    changed = (item.get("fields") or {}).get("System.ChangedDate")
    if changed is not None:
        return {**item, "changed_date": changed}
    return item


def validate_credentials(organization: str, personal_access_token: str) -> bool:
    """Confirm the PAT and organization are valid with a cheap projects probe.

    Azure DevOps answers an invalid PAT with a 203 + HTML sign-in page rather
    than a 401, so only an exact 200 counts."""
    try:
        org = _validate_organization(organization)
        response = _get_session(personal_access_token).get(
            f"{AZURE_DEVOPS_BASE_URL}/{quote(org)}/_apis/projects?{urlencode({'$top': 1, 'api-version': API_VERSION})}",
            timeout=10,
        )
        return response.status_code == 200
    except Exception:
        return False


def get_rows(
    organization: str,
    personal_access_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AzureDevOpsResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = AZURE_DEVOPS_ENDPOINTS[endpoint]
    session = _get_session(personal_access_token)
    org = _validate_organization(organization)

    @retry(
        retry=retry_if_exception_type((AzureDevOpsRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=2, max=120),
        reraise=True,
    )
    def fetch(path: str, params: dict[str, Any]) -> requests.Response:
        url = f"{AZURE_DEVOPS_BASE_URL}/{quote(org)}{path}?{urlencode({**params, 'api-version': API_VERSION})}"
        response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise AzureDevOpsRetryableError(
                f"Azure DevOps API error (retryable): status={response.status_code}, url={url}"
            )

        # An invalid/expired PAT yields a 203 with an HTML sign-in page.
        if response.status_code == 203:
            raise AzureDevOpsAuthError(
                "Azure DevOps returned a sign-in page (203) — the personal access token is invalid or expired."
            )

        if not response.ok:
            logger.error(f"Azure DevOps API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return response

    incremental_value = (
        _format_datetime(db_incremental_field_last_value)
        if should_use_incremental_field and db_incremental_field_last_value is not None
        else None
    )

    def base_params() -> dict[str, Any]:
        params: dict[str, Any] = {}
        if config.incremental_param is not None and incremental_value is not None:
            params[config.incremental_param] = incremental_value
        return params

    def iterate_header_token(
        path: str, extra: dict[str, Any], use_base_params: bool = True
    ) -> Iterator[list[dict[str, Any]]]:
        token: Optional[str] = None
        while True:
            params = {**(base_params() if use_base_params else {}), **extra, "$top": PAGE_SIZE}
            if token:
                params["continuationToken"] = token
            response = fetch(path, params)
            items = response.json().get("value", []) or []
            if items:
                yield items
            token = response.headers.get("x-ms-continuationtoken")
            if not token or not items:
                return

    def iterate_skip(path: str, extra: dict[str, Any]) -> Iterator[list[dict[str, Any]]]:
        skip = 0
        while True:
            params = {**base_params(), **extra, "$top": PAGE_SIZE, "$skip": skip}
            response = fetch(path, params)
            items = response.json().get("value", []) or []
            if items:
                yield items
            if len(items) < PAGE_SIZE:
                return
            skip += PAGE_SIZE

    def project_names() -> list[str]:
        # Project enumeration is independent of the data endpoint being synced,
        # so it must not carry that endpoint's incremental filter.
        names: list[str] = []
        for page in iterate_header_token("/_apis/projects", {}, use_base_params=False):
            names.extend(item["name"] for item in page if item.get("name"))
        return names

    if endpoint == "projects":
        yield from iterate_header_token(config.path, {})
        return

    if endpoint == "repositories":
        for project in project_names():
            response = fetch(config.path.replace("{project}", quote(project)), {})
            items = response.json().get("value", []) or []
            if items:
                yield items
        return

    if endpoint == "builds":
        for project in project_names():
            # Ascending queue-time order keeps the incremental watermark monotonic.
            yield from iterate_header_token(
                config.path.replace("{project}", quote(project)), {"queryOrder": "queueTimeAscending"}
            )
        return

    if endpoint == "pull_requests":
        extra = {"searchCriteria.status": "all"}
        if incremental_value is not None:
            extra["searchCriteria.queryTimeRangeType"] = "created"
        for project in project_names():
            yield from iterate_skip(config.path.replace("{project}", quote(project)), extra)
        return

    # work_item_revisions: org-level reporting endpoint with a body
    # continuationToken that doubles as a resumable watermark.
    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    token = resume_config.continuation_token if resume_config is not None else None
    if token is not None:
        logger.debug(f"Azure DevOps: resuming {endpoint} from continuation token")

    while True:
        # A continuationToken fully encodes the stream position, so once we have
        # one (from a resumed run or the previous batch) it must be sent alone —
        # pairing it with startDateTime would reset the stream to the watermark.
        params = {"continuationToken": token} if token else base_params()
        body = fetch(config.path, params).json()
        items = [_flatten_revision(item) for item in (body.get("values", []) or [])]

        if items:
            yield items

        token = body.get("continuationToken")
        if body.get("isLastBatch", True) or not token:
            break

        # Save state AFTER yielding the batch so a crash re-yields it (merge
        # dedupes on primary keys) rather than skipping it.
        resumable_source_manager.save_state(AzureDevOpsResumeConfig(continuation_token=token))


def azure_devops_source(
    organization: str,
    personal_access_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AzureDevOpsResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = AZURE_DEVOPS_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            organization=organization,
            personal_access_token=personal_access_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode=config.sort_mode,
    )
