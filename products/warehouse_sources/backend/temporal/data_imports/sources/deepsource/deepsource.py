import dataclasses
from collections.abc import Callable, Iterator
from typing import Any

import requests
from structlog.types import FilteringBoundLogger
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.deepsource.queries import (
    ANALYSIS_RUN_CHECKS_QUERY,
    CONNECTION_QUERIES,
    PER_REPOSITORY_QUERIES,
    REPOSITORIES_QUERY,
    REPOSITORY_NAMES_QUERY,
    ROOT_CONNECTION_QUERIES,
    VALIDATE_QUERY,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.deepsource.settings import (
    DEEPSOURCE_API_URL,
    DEEPSOURCE_CHECKS_PER_RUN_PAGE_SIZE,
    DEEPSOURCE_DEFAULT_PAGE_SIZE,
    DEEPSOURCE_ENDPOINTS,
    DEEPSOURCE_MAX_PAGES_PER_CONNECTION,
    DEEPSOURCE_REPOSITORY_LIST_PAGE_SIZE,
)

DEEPSOURCE_MAX_RETRY_ATTEMPTS = 8
# DeepSource rate-limits at 5,000 requests/hour and answers overages with HTTP 429. Cap a
# misbehaving Retry-After so one header can't pin the activity open indefinitely; genuine
# hour-long exhaustion falls through to Temporal rescheduling the activity, which resumes
# from the saved cursor.
DEEPSOURCE_MAX_RETRY_AFTER_SECONDS = 300
_DEEPSOURCE_FALLBACK_WAIT = wait_exponential_jitter(initial=1, max=60)


class DeepsourceRetryableError(Exception):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


def _parse_retry_after(response: requests.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        return None
    return max(0.0, seconds)


def _wait_strategy(retry_state: RetryCallState) -> float:
    """Honor a 429's Retry-After when present, else fall back to jittered exponential backoff."""
    exc = retry_state.outcome.exception() if retry_state.outcome is not None else None
    if isinstance(exc, DeepsourceRetryableError) and exc.retry_after is not None:
        return min(exc.retry_after, DEEPSOURCE_MAX_RETRY_AFTER_SECONDS)
    return _DEEPSOURCE_FALLBACK_WAIT(retry_state)


@dataclasses.dataclass
class DeepsourceResumeConfig:
    # Repositories whose fan-out walk finished in this job; skipped on resume.
    completed_repositories: list[str] = dataclasses.field(default_factory=list)
    # Repository currently being walked, resumed at `cursor`.
    current_repository: str | None = None
    # Relay endCursor of the next page to fetch (the account repositories connection for
    # the `repositories` endpoint, the per-repository connection for fan-out endpoints).
    cursor: str | None = None


def _make_session(api_token: str) -> requests.Session:
    return make_tracked_session(
        headers={
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        }
    )


@retry(
    retry=retry_if_exception_type(DeepsourceRetryableError),
    stop=stop_after_attempt(DEEPSOURCE_MAX_RETRY_ATTEMPTS),
    wait=_wait_strategy,
    reraise=True,
)
def _execute(
    session: requests.Session,
    query: str,
    variables: dict[str, Any],
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    try:
        response = session.post(DEEPSOURCE_API_URL, json={"query": query, "variables": variables}, timeout=60)
    except (requests.ConnectionError, requests.Timeout) as e:
        # The tracked session's urllib3 retry only covers idempotent methods, so these POSTs
        # get no transport-level retry; fold transient network failures into the backoff here.
        raise DeepsourceRetryableError(f"DeepSource: transient network error - {e}")

    if response.status_code >= 500:
        raise DeepsourceRetryableError(f"DeepSource: server error {response.status_code}")

    if response.status_code == 429:
        raise DeepsourceRetryableError("DeepSource: rate limited (429)", retry_after=_parse_retry_after(response))

    if response.status_code in (401, 403):
        # Auth failures return a plain JSON body ({"message": "Authentication required"}),
        # not a GraphQL payload. Raise with the stable status text so
        # get_non_retryable_errors can match it and stop the sync.
        detail = ""
        try:
            body = response.json()
            if isinstance(body, dict) and body.get("message"):
                detail = f" (DeepSource API: {body['message']})"
        except Exception:
            pass
        raise Exception(f"{response.status_code} Client Error: {response.reason} for url: {DEEPSOURCE_API_URL}{detail}")

    try:
        payload = response.json()
    except Exception as e:
        if not response.ok:
            raise Exception(
                f"{response.status_code} Client Error: {response.reason} for url: {DEEPSOURCE_API_URL}"
            ) from e
        # A 2xx whose body won't parse is almost always a truncated transfer, not a stable
        # response. Retry it; don't echo response.text — a partial body carries data.
        raise DeepsourceRetryableError(f"DeepSource: incomplete JSON response ({e})") from e

    if "errors" in payload:
        error_messages = [e.get("message", "") for e in payload["errors"] if isinstance(e, dict)]
        joined = "; ".join(error_messages)
        raise Exception(f"DeepSource GraphQL error: {joined}")

    if not response.ok:
        raise Exception(f"{response.status_code} Client Error: {response.reason} for url: {DEEPSOURCE_API_URL}")

    if "data" not in payload:
        raise Exception(f"Unexpected DeepSource response format. Keys: {list(payload.keys())}")

    return payload


def _iter_connection(
    session: requests.Session,
    query: str,
    variables: dict[str, Any],
    parent_field: str | None,
    connection_field: str,
    logger: FilteringBoundLogger,
    start_cursor: str | None = None,
    missing_parent_error: str | None = None,
) -> Iterator[tuple[dict[str, Any], list[dict[str, Any]], str | None, bool]]:
    """Walk one Relay connection, yielding (parent_object, nodes, end_cursor, has_next_page) pages.

    ``parent_field`` is None for a connection that sits directly on the root query.

    When the parent object resolves to null: raise ``missing_parent_error`` if set (a missing
    account is fatal), otherwise stop silently (a repository deleted mid-sync is a benign skip).
    """
    cursor = start_cursor
    page_count = 0
    while True:
        payload = _execute(session, query, {**variables, "cursor": cursor}, logger)
        parent = payload["data"] if parent_field is None else payload["data"].get(parent_field)
        if parent is None:
            if missing_parent_error:
                raise Exception(missing_parent_error)
            logger.warning(f"DeepSource: {parent_field} not found, skipping", variables=variables)
            return

        connection = parent.get(connection_field) or {}
        nodes = [edge["node"] for edge in connection.get("edges") or [] if edge and edge.get("node")]
        page_info = connection.get("pageInfo") or {}
        has_next_page = bool(page_info.get("hasNextPage"))
        end_cursor = page_info.get("endCursor")

        if has_next_page and not end_cursor:
            # hasNextPage=True with a null endCursor would loop on the same page forever;
            # fail loudly instead of silently returning partial results.
            raise Exception(f"DeepSource: hasNextPage=True but endCursor is empty for {connection_field}")

        if has_next_page and end_cursor == cursor:
            # An endCursor that doesn't advance re-fetches this page, duplicating its rows
            # until the page cap truncates the rest.
            raise Exception(f"DeepSource: endCursor did not advance past '{cursor}' for {connection_field}")

        yield parent, nodes, end_cursor, has_next_page

        if not has_next_page:
            return

        page_count += 1
        if page_count >= DEEPSOURCE_MAX_PAGES_PER_CONNECTION:
            logger.warning(
                "DeepSource: per-connection page cap reached; remaining pages skipped",
                connection_field=connection_field,
                max_pages=DEEPSOURCE_MAX_PAGES_PER_CONNECTION,
                variables=variables,
            )
            return

        cursor = end_cursor


def _account_variables(account_login: str, vcs_provider: str) -> dict[str, Any]:
    return {"login": account_login, "vcsProvider": vcs_provider}


def _repositories_rows(
    session: requests.Session,
    account_login: str,
    vcs_provider: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DeepsourceResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_cursor = resume.cursor if resume else None
    if start_cursor:
        logger.debug("DeepSource: resuming repositories from saved cursor")

    variables = {**_account_variables(account_login, vcs_provider), "pageSize": DEEPSOURCE_DEFAULT_PAGE_SIZE}
    for _parent, nodes, end_cursor, has_next_page in _iter_connection(
        session,
        REPOSITORIES_QUERY,
        variables,
        "account",
        "repositories",
        logger,
        start_cursor=start_cursor,
        missing_parent_error=_account_not_found_error(account_login, vcs_provider),
    ):
        if nodes:
            yield nodes
        # Checkpoint points at the next page; on resume the walk continues from there.
        if has_next_page:
            resumable_source_manager.save_state(DeepsourceResumeConfig(cursor=end_cursor))


def _account_not_found_error(account_login: str, vcs_provider: str) -> str:
    return (
        f"DeepSource account not found: '{account_login}' ({vcs_provider}). "
        "Check the account login and VCS provider, and that your token has access to it."
    )


def _list_activated_repository_names(
    session: requests.Session,
    account_login: str,
    vcs_provider: str,
    logger: FilteringBoundLogger,
) -> list[str]:
    """Enumerate activated repositories to drive fan-out. Repositories that aren't activated
    on DeepSource have no analysis data, so querying them would only burn rate limit."""
    names: list[str] = []
    total = 0
    variables = {**_account_variables(account_login, vcs_provider), "pageSize": DEEPSOURCE_REPOSITORY_LIST_PAGE_SIZE}
    for _parent, nodes, _end_cursor, _has_next_page in _iter_connection(
        session,
        REPOSITORY_NAMES_QUERY,
        variables,
        "account",
        "repositories",
        logger,
        missing_parent_error=_account_not_found_error(account_login, vcs_provider),
    ):
        total += len(nodes)
        names.extend(node["name"] for node in nodes if node.get("isActivated"))

    logger.debug(f"DeepSource: fanning out over {len(names)} activated repositories (of {total} total)")
    return names


def _with_repository_context(node: dict[str, Any], repository: dict[str, Any]) -> dict[str, Any]:
    return {**node, "repositoryId": repository.get("id"), "repositoryName": repository.get("name")}


# Turns one node of a repository connection into the rows it contributes to the table.
# Most endpoints are one row per node; `checks` expands each analysis run into its checks.
FanOutRowBuilder = Callable[
    [requests.Session, FilteringBoundLogger, dict[str, Any], dict[str, Any]], list[dict[str, Any]]
]


def _repository_node_rows(
    _session: requests.Session,
    _logger: FilteringBoundLogger,
    node: dict[str, Any],
    repository: dict[str, Any],
) -> list[dict[str, Any]]:
    return [_with_repository_context(node, repository)]


def _check_rows(
    session: requests.Session,
    logger: FilteringBoundLogger,
    analysis_run: dict[str, Any],
    repository: dict[str, Any],
) -> list[dict[str, Any]]:
    """One row per analyzer check of an analysis run, from the checks nested in the run walk."""
    context = {
        "analysisRunId": analysis_run.get("id"),
        "analysisRunUid": analysis_run.get("runUid"),
        "commitOid": analysis_run.get("commitOid"),
        "branchName": analysis_run.get("branchName"),
        "repositoryId": repository.get("id"),
        "repositoryName": repository.get("name"),
    }
    connection = analysis_run.get("checks") or {}
    rows = [{**edge["node"], **context} for edge in connection.get("edges") or [] if edge and edge.get("node")]

    page_info = connection.get("pageInfo") or {}
    if not page_info.get("hasNextPage"):
        return rows

    end_cursor = page_info.get("endCursor")
    if not end_cursor:
        raise Exception("DeepSource: hasNextPage=True but endCursor is empty for checks")

    for _parent, nodes, _end_cursor, _has_next_page in _iter_connection(
        session,
        ANALYSIS_RUN_CHECKS_QUERY,
        {"id": analysis_run["id"], "checkPageSize": DEEPSOURCE_CHECKS_PER_RUN_PAGE_SIZE},
        "node",
        "checks",
        logger,
        start_cursor=end_cursor,
        # The run was in the page we just read, so a null node here means its remaining
        # checks are unreachable. Skipping would checkpoint a half-synced run as complete.
        missing_parent_error=f"DeepSource: analysis run {analysis_run['id']} disappeared while paginating its checks",
    ):
        rows.extend({**node, **context} for node in nodes)
    return rows


_FAN_OUT_ROW_BUILDERS: dict[str, FanOutRowBuilder] = {
    "checks": _check_rows,
}


def _metric_rows(repository: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten repository.metrics into one row per metric item (metric x language key)."""
    rows: list[dict[str, Any]] = []
    for metric in repository.get("metrics") or []:
        for item in metric.get("items") or []:
            rows.append(
                {
                    "id": item.get("id"),
                    "key": item.get("key"),
                    "threshold": item.get("threshold"),
                    "latestValue": item.get("latestValue"),
                    "latestValueDisplay": item.get("latestValueDisplay"),
                    "thresholdStatus": item.get("thresholdStatus"),
                    "metricShortcode": metric.get("shortcode"),
                    "metricName": metric.get("name"),
                    "metricDescription": metric.get("description"),
                    "metricUnit": metric.get("unit"),
                    "positiveDirection": metric.get("positiveDirection"),
                    "isReported": metric.get("isReported"),
                    "isThresholdEnforced": metric.get("isThresholdEnforced"),
                    "repositoryId": repository.get("id"),
                    "repositoryName": repository.get("name"),
                }
            )
    return rows


def _report_rows(repository: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten the repository.reports namespace into one row per report key."""
    rows: list[dict[str, Any]] = []
    for report in (repository.get("reports") or {}).values():
        if not isinstance(report, dict):
            continue
        rows.append(
            {
                "key": report.get("key"),
                "title": report.get("title"),
                "currentValue": report.get("currentValue"),
                # Only the security reports expose a status; the trend reports carry null.
                "status": report.get("status"),
                "repositoryId": repository.get("id"),
                "repositoryName": repository.get("name"),
            }
        )
    return rows


_PER_REPOSITORY_ROW_BUILDERS = {
    "metrics": _metric_rows,
    "reports": _report_rows,
}


def _fan_out_connection_rows(
    session: requests.Session,
    account_login: str,
    vcs_provider: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DeepsourceResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Paginated per-repository fan-out (analysis runs, pull requests, issues, occurrences)."""
    query = CONNECTION_QUERIES[endpoint]
    endpoint_config = DEEPSOURCE_ENDPOINTS[endpoint]
    connection_field = endpoint_config.connection_field
    assert connection_field is not None
    build_rows = _FAN_OUT_ROW_BUILDERS.get(endpoint, _repository_node_rows)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    completed = set(resume.completed_repositories) if resume else set()
    if resume:
        logger.debug(
            f"DeepSource: resuming {endpoint} fan-out, {len(completed)} repositories already completed",
        )

    for repository_name in _list_activated_repository_names(session, account_login, vcs_provider, logger):
        if repository_name in completed:
            continue

        # Community reports note DeepSource cursors can expire; if a stale resume cursor is
        # rejected the sync fails and Temporal retries — the Redis state expires within 24h,
        # bounding the worst case. Kept simple on purpose until observed in practice.
        start_cursor = resume.cursor if resume and resume.current_repository == repository_name else None
        variables = {
            **_account_variables(account_login, vcs_provider),
            "name": repository_name,
            "pageSize": DEEPSOURCE_DEFAULT_PAGE_SIZE,
            **endpoint_config.extra_variables,
        }
        for parent, nodes, end_cursor, has_next_page in _iter_connection(
            session,
            query,
            variables,
            "repository",
            connection_field,
            logger,
            start_cursor=start_cursor,
        ):
            rows = [row for node in nodes for row in build_rows(session, logger, node, parent)]
            if rows:
                yield rows
            if has_next_page:
                resumable_source_manager.save_state(
                    DeepsourceResumeConfig(
                        completed_repositories=sorted(completed),
                        current_repository=repository_name,
                        cursor=end_cursor,
                    )
                )

        completed.add(repository_name)
        resumable_source_manager.save_state(DeepsourceResumeConfig(completed_repositories=sorted(completed)))


def _root_connection_rows(
    session: requests.Session,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DeepsourceResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Walk a Relay connection on the root query — no account or repository to fan out over."""
    connection_field = DEEPSOURCE_ENDPOINTS[endpoint].root_connection_field
    assert connection_field is not None

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_cursor = resume.cursor if resume else None

    for _parent, nodes, end_cursor, has_next_page in _iter_connection(
        session,
        ROOT_CONNECTION_QUERIES[endpoint],
        {"pageSize": DEEPSOURCE_DEFAULT_PAGE_SIZE},
        None,
        connection_field,
        logger,
        start_cursor=start_cursor,
    ):
        if nodes:
            yield nodes
        if has_next_page:
            resumable_source_manager.save_state(DeepsourceResumeConfig(cursor=end_cursor))


def _per_repository_object_rows(
    session: requests.Session,
    account_login: str,
    vcs_provider: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DeepsourceResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Non-paginated per-repository fan-out (metrics, reports): one query per repository."""
    query = PER_REPOSITORY_QUERIES[endpoint]
    build_rows = _PER_REPOSITORY_ROW_BUILDERS[endpoint]

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    completed = set(resume.completed_repositories) if resume else set()

    for repository_name in _list_activated_repository_names(session, account_login, vcs_provider, logger):
        if repository_name in completed:
            continue

        variables = {**_account_variables(account_login, vcs_provider), "name": repository_name}
        payload = _execute(session, query, variables, logger)
        repository = payload["data"].get("repository")
        if repository is None:
            logger.warning("DeepSource: repository not found, skipping", repository=repository_name)
        else:
            rows = build_rows(repository)
            if rows:
                yield rows

        completed.add(repository_name)
        resumable_source_manager.save_state(DeepsourceResumeConfig(completed_repositories=sorted(completed)))


def deepsource_source(
    api_token: str,
    account_login: str,
    vcs_provider: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DeepsourceResumeConfig],
) -> SourceResponse:
    endpoint_config = DEEPSOURCE_ENDPOINTS.get(endpoint)
    if not endpoint_config:
        raise ValueError(f"Unknown DeepSource endpoint: {endpoint}")

    def get_rows() -> Iterator[list[dict[str, Any]]]:
        session = _make_session(api_token)
        try:
            if endpoint == "repositories":
                yield from _repositories_rows(session, account_login, vcs_provider, logger, resumable_source_manager)
            elif endpoint_config.root_connection_field:
                yield from _root_connection_rows(session, endpoint, logger, resumable_source_manager)
            elif endpoint_config.per_repository_object:
                yield from _per_repository_object_rows(
                    session, account_login, vcs_provider, endpoint, logger, resumable_source_manager
                )
            else:
                yield from _fan_out_connection_rows(
                    session, account_login, vcs_provider, endpoint, logger, resumable_source_manager
                )
        finally:
            session.close()

    return SourceResponse(
        items=get_rows,
        primary_keys=endpoint_config.primary_keys,
        name=endpoint,
        partition_count=1 if endpoint_config.partition_mode else None,
        partition_size=1 if endpoint_config.partition_mode else None,
        partition_mode=endpoint_config.partition_mode,
        partition_format=endpoint_config.partition_format,
        partition_keys=endpoint_config.partition_keys,
    )


def validate_credentials(api_token: str, account_login: str, vcs_provider: str) -> tuple[bool, str | None]:
    session = _make_session(api_token)
    try:
        response = session.post(
            DEEPSOURCE_API_URL,
            json={"query": VALIDATE_QUERY, "variables": _account_variables(account_login, vcs_provider)},
            timeout=10,
        )

        if response.status_code in (401, 403):
            return False, "Invalid DeepSource personal access token"

        response.raise_for_status()
        payload = response.json()
        data = payload.get("data") or {}

        # The token can be genuine while the configured account is wrong or inaccessible —
        # DeepSource resolves `account` to null (with or without a GraphQL error) in that case.
        if data.get("viewer") and data.get("account"):
            return True, None
        if data.get("viewer"):
            return False, _account_not_found_error(account_login, vcs_provider)
        if "errors" in payload:
            error_messages = [e.get("message", "") for e in payload["errors"] if isinstance(e, dict)]
            return False, f"DeepSource API error: {'; '.join(error_messages)}"
        return False, "Could not verify DeepSource credentials"
    except Exception as e:
        return False, str(e)
    finally:
        session.close()
