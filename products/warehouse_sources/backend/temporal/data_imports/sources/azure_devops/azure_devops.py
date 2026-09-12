import re
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import quote, urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.settings import (
    AZURE_DEVOPS_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import UNVERSIONED_API_VERSION
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

AZURE_DEVOPS_BASE_URL = "https://dev.azure.com"

# Source version labels. The legacy label predates versioning and keeps sending
# api-version 7.1 so existing syncs are unchanged; 7.2 is the current GA stable API.
AZURE_DEVOPS_VERSION_LEGACY = UNVERSIONED_API_VERSION
AZURE_DEVOPS_VERSION_7_2 = "7.2"

# Source label → `api-version` query param actually sent on the wire.
_WIRE_API_VERSION: dict[str, str] = {
    AZURE_DEVOPS_VERSION_LEGACY: "7.1",
    AZURE_DEVOPS_VERSION_7_2: "7.2",
}


def wire_api_version(api_version: str) -> str:
    try:
        return _WIRE_API_VERSION[api_version]
    except KeyError:
        raise ValueError(f"Unsupported Azure DevOps API version: {api_version}")


PAGE_SIZE = 200
REQUEST_TIMEOUT_SECONDS = 60
# Rate limiting is 200 TSTUs per identity per sliding 5-minute window; 429s
# carry Retry-After but exponential backoff is sufficient.
MAX_RETRY_ATTEMPTS = 5


class AzureDevOpsRetryableError(Exception):
    pass


class AzureDevOpsAuthError(Exception):
    pass


@dataclasses.dataclass(frozen=True)
class PullRequestRef:
    """One pull request located well enough to reach its child endpoints."""

    project: str
    repository_id: str
    pull_request_id: int


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


def _flatten_commit(item: dict[str, Any], project: str, repository: dict[str, Any]) -> dict[str, Any]:
    # The committer date is nested under `committer`; the pipeline needs it at the
    # row root to partition and to track the incremental watermark.
    return {
        **item,
        "project_name": project,
        "repository_id": repository.get("id"),
        "repository_name": repository.get("name"),
        "committer_date": (item.get("committer") or {}).get("date"),
    }


def _with_pull_request_ref(item: dict[str, Any], ref: PullRequestRef) -> dict[str, Any]:
    return {
        **item,
        "project_name": ref.project,
        "repository_id": ref.repository_id,
        "pull_request_id": ref.pull_request_id,
    }


def _flatten_thread_comments(thread: dict[str, Any], ref: PullRequestRef) -> list[dict[str, Any]]:
    return [
        {
            **comment,
            "project_name": ref.project,
            "repository_id": ref.repository_id,
            "pull_request_id": ref.pull_request_id,
            "thread_id": thread.get("id"),
        }
        for comment in (thread.get("comments") or [])
    ]


def _flatten_team(item: dict[str, Any], project: dict[str, Any]) -> dict[str, Any]:
    # This endpoint leaves WebApiTeam's optional project fields unset, so the
    # fan-out parent supplies them.
    return {**item, "project_id": project.get("id"), "project_name": project.get("name")}


def _flatten_team_member(item: dict[str, Any], project: dict[str, Any], team: dict[str, Any]) -> dict[str, Any]:
    return {
        **item,
        "project_id": project.get("id"),
        "team_id": team.get("id"),
        "team_name": team.get("name"),
        "identity_id": (item.get("identity") or {}).get("id"),
    }


# Actionable reasons returned by the create-time credential probe. The sync-time equivalents live in
# AzureDevOpsSource.get_non_retryable_errors, keyed on the raw HTTP error text raise_for_status emits.
_INVALID_ORGANIZATION_MESSAGE = "That doesn't look like a valid Azure DevOps organization name. Enter just the organization name, for example myorg."
_INVALID_PAT_MESSAGE = (
    "Azure DevOps authentication failed. Please check your personal access token (it may have expired)."
)
_FORBIDDEN_MESSAGE = (
    "Azure DevOps denied access. Please check that your personal access token has read scopes for this data."
)
_ORGANIZATION_NOT_FOUND_MESSAGE = "Azure DevOps organization not found. Please check the organization name."
_UNREACHABLE_MESSAGE = "Couldn't reach Azure DevOps to validate your credentials. Please try again in a few minutes."


def _unexpected_status_message(status_code: int) -> str:
    # Any status the probe doesn't map explicitly (a 429, a 5xx, an unexpected redirect) lands here.
    # Name the status and point at both inputs rather than asserting the credentials are invalid,
    # which misdirects the user when the real cause is throttling or an Azure-side error.
    return (
        f"Azure DevOps returned an unexpected response (HTTP {status_code}). "
        "Check your organization name and personal access token, then try again."
    )


def validate_credentials(organization: str, personal_access_token: str, api_version: str) -> tuple[bool, str | None]:
    """Confirm the PAT and organization are valid with a cheap projects probe, reporting an
    actionable reason on failure rather than collapsing every cause into one generic message.

    Azure DevOps answers an invalid PAT with a 203 + HTML sign-in page rather
    than a 401, so only an exact 200 counts."""
    try:
        org = _validate_organization(organization)
    except ValueError:
        return False, _INVALID_ORGANIZATION_MESSAGE

    try:
        wire_version = wire_api_version(api_version)
        response = _get_session(personal_access_token).get(
            f"{AZURE_DEVOPS_BASE_URL}/{quote(org)}/_apis/projects?{urlencode({'$top': 1, 'api-version': wire_version})}",
            timeout=10,
        )
    except Exception:
        return False, _UNREACHABLE_MESSAGE

    status_code = response.status_code
    if status_code == 200:
        return True, None
    # An invalid or expired PAT yields a 203 + HTML sign-in page rather than a 401.
    if status_code in (203, 401):
        return False, _INVALID_PAT_MESSAGE
    if status_code == 403:
        return False, _FORBIDDEN_MESSAGE
    if status_code == 404:
        return False, _ORGANIZATION_NOT_FOUND_MESSAGE
    return False, _unexpected_status_message(status_code)


def get_rows(
    organization: str,
    personal_access_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AzureDevOpsResumeConfig],
    api_version: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = AZURE_DEVOPS_ENDPOINTS[endpoint]
    session = _get_session(personal_access_token)
    org = _validate_organization(organization)
    wire_version = wire_api_version(api_version)

    @retry(
        retry=retry_if_exception_type((AzureDevOpsRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=2, max=120),
        reraise=True,
    )
    def fetch(path: str, params: dict[str, Any]) -> requests.Response:
        url = f"{AZURE_DEVOPS_BASE_URL}/{quote(org)}{path}?{urlencode({**params, 'api-version': wire_version})}"
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

    def iterate_skip(path: str, extra: dict[str, Any], use_base_params: bool = True) -> Iterator[list[dict[str, Any]]]:
        skip = 0
        while True:
            params = {**(base_params() if use_base_params else {}), **extra, "$top": PAGE_SIZE, "$skip": skip}
            response = fetch(path, params)
            items = response.json().get("value", []) or []
            if not items:
                return
            yield items
            # Advance by what the server returned rather than by $top: several
            # endpoints cap the page size below what we ask for, and treating a
            # short page as the last one would silently truncate the table.
            skip += len(items)

    def projects() -> list[dict[str, Any]]:
        # Project enumeration is independent of the data endpoint being synced,
        # so it must not carry that endpoint's incremental filter.
        items: list[dict[str, Any]] = []
        for page in iterate_header_token("/_apis/projects", {}, use_base_params=False):
            items.extend(page)
        return items

    def project_names() -> list[str]:
        return [item["name"] for item in projects() if item.get("name")]

    def repositories_for(project: str) -> list[dict[str, Any]]:
        path = AZURE_DEVOPS_ENDPOINTS["repositories"].path.replace("{project}", quote(project))
        return fetch(path, {}).json().get("value", []) or []

    def teams_for(project: dict[str, Any]) -> Iterator[list[dict[str, Any]]]:
        path = AZURE_DEVOPS_ENDPOINTS["teams"].path.replace("{project}", quote(str(project["id"])))
        yield from iterate_skip(path, {}, use_base_params=False)

    def pull_request_refs() -> Iterator[PullRequestRef]:
        pr_path = AZURE_DEVOPS_ENDPOINTS["pull_requests"].path
        for project in project_names():
            path = pr_path.replace("{project}", quote(project))
            for page in iterate_skip(path, {"searchCriteria.status": "all"}, use_base_params=False):
                for pull_request in page:
                    repository_id = (pull_request.get("repository") or {}).get("id")
                    pull_request_id = pull_request.get("pullRequestId")
                    if repository_id and pull_request_id is not None:
                        yield PullRequestRef(project, repository_id, pull_request_id)

    def pull_request_child_path(ref: PullRequestRef) -> str:
        return (
            config.path.replace("{project}", quote(ref.project))
            .replace("{repositoryId}", quote(str(ref.repository_id)))
            .replace("{pullRequestId}", quote(str(ref.pull_request_id)))
        )

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

    if endpoint == "commits":
        for project in project_names():
            for repository in repositories_for(project):
                if repository.get("isDisabled") or not repository.get("id"):
                    continue
                path = config.path.replace("{project}", quote(project)).replace(
                    "{repositoryId}", quote(str(repository["id"]))
                )
                # Oldest-first keeps each repository's pages aligned with the
                # fromDate filter; the stream is still declared `desc` because the
                # fan-out interleaves repositories.
                for page in iterate_skip(path, {"searchCriteria.showOldestCommitsFirst": "true"}):
                    yield [_flatten_commit(item, project, repository) for item in page]
        return

    if endpoint in ("pull_request_threads", "pull_request_thread_comments"):
        want_comments = endpoint == "pull_request_thread_comments"
        for ref in pull_request_refs():
            threads = fetch(pull_request_child_path(ref), {}).json().get("value", []) or []
            if want_comments:
                rows = [row for thread in threads for row in _flatten_thread_comments(thread, ref)]
            else:
                rows = [_with_pull_request_ref(thread, ref) for thread in threads]
            if rows:
                yield rows
        return

    if endpoint == "pull_request_reviewers":
        for ref in pull_request_refs():
            reviewers = fetch(pull_request_child_path(ref), {}).json().get("value", []) or []
            if reviewers:
                yield [_with_pull_request_ref(item, ref) for item in reviewers]
        return

    if endpoint == "teams":
        for project_row in projects():
            if not project_row.get("id"):
                continue
            for page in teams_for(project_row):
                yield [_flatten_team(item, project_row) for item in page]
        return

    if endpoint == "team_members":
        for project_row in projects():
            if not project_row.get("id"):
                continue
            for team_page in teams_for(project_row):
                for team in team_page:
                    if not team.get("id"):
                        continue
                    path = config.path.replace("{project}", quote(str(project_row["id"]))).replace(
                        "{teamId}", quote(str(team["id"]))
                    )
                    for page in iterate_skip(path, {}, use_base_params=False):
                        yield [_flatten_team_member(item, project_row, team) for item in page]
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
    api_version: str,
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
            api_version=api_version,
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
