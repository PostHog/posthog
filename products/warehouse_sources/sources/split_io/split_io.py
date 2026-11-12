from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urlsplit, urlunsplit

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry_if_exception_type, stop_after_attempt

from products.warehouse_sources.sources.sdk import (
    ResumableSourceManager,
    SourceResponse,
    frozen,
    make_tracked_session,
    retry_with_deadline,
)
from products.warehouse_sources.sources.split_io.settings import (
    SPLIT_IO_ENDPOINTS,
    SplitIoEndpointConfig,
    SplitIoParentLevel,
)

API_HOST = "https://api.split.io"
BASE_URL = f"{API_HOST}/internal/api/v2"

# Offset-paginated list endpoints document a max `limit` of 200 but some resources cap lower;
# 50 is accepted across the board, and the offset advances by the actual row count so a lower
# server-side clamp only costs extra requests, never skipped rows.
PAGE_SIZE = 50
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRY_ATTEMPTS = 5
MAX_RETRY_WAIT_SECONDS = 60


class SplitIoRetryableError(Exception):
    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


@frozen
class SplitIoResumeConfig:
    # Full URL of the next page to fetch ("" once a resource is exhausted).
    next_url: str = ""
    # For fan-out endpoints, the workspace currently being paginated ("" for top-level
    # endpoints or before the first workspace starts).
    workspace_id: str = ""
    # For endpoints with parent levels inside a workspace, the parent being paginated: its
    # path values joined with "/", outermost first.
    parent_key: str = ""


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _base_url(config: SplitIoEndpointConfig) -> str:
    return f"{API_HOST}/internal/api/{config.api_version}"


def _initial_url(config: SplitIoEndpointConfig, workspace_id: str = "", path_vars: dict[str, str] | None = None) -> str:
    quoted_vars = {key: quote(value, safe="") for key, value in (path_vars or {}).items()}
    path = config.path.format(workspace_id=workspace_id, **quoted_vars)
    params: dict[str, Any] = dict(config.extra_params)
    if config.workspace_query_param and workspace_id:
        params[config.workspace_query_param] = workspace_id
    if config.pagination != "none":
        params[config.limit_param] = PAGE_SIZE
    query = urlencode(params)
    base = _base_url(config)
    return f"{base}{path}?{query}" if query else f"{base}{path}"


def _replace_query_param(url: str, key: str, value: str) -> str:
    scheme, netloc, path, query, fragment = urlsplit(url)
    params = {k: v[-1] for k, v in parse_qs(query).items()}
    params[key] = value
    return urlunsplit((scheme, netloc, path, urlencode(params), fragment))


def _query_param(url: str, key: str) -> str | None:
    values = parse_qs(urlsplit(url).query).get(key)
    return values[-1] if values else None


def _extract_items(payload: Any, data_key: str | None) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        raise SplitIoRetryableError(f"Split returned an unexpected payload type: {type(payload).__name__}")
    # Fall back to the other documented envelope key — the Admin API wraps rows in either
    # `objects` (offset endpoints) or `data` (marker endpoints), and per-endpoint docs drift.
    for key in filter(None, (data_key, "objects", "data")):
        items = payload.get(key)
        if isinstance(items, list):
            return items
    return []


def _next_url(config: SplitIoEndpointConfig, url: str, payload: Any, items: list[dict[str, Any]]) -> str | None:
    if config.pagination == "none" or not isinstance(payload, dict) or not items:
        return None

    if config.pagination == "marker":
        next_marker = payload.get("nextMarker")
        if not next_marker or not isinstance(next_marker, str):
            return None
        # A marker equal to the one we just requested means the server ignored the param;
        # stop rather than loop on the same page forever.
        if next_marker == _query_param(url, config.after_param):
            return None
        return _replace_query_param(url, config.after_param, next_marker)

    # Offset pagination: advance by the number of rows actually returned (robust to the server
    # clamping `limit`), terminating on `totalCount` when present.
    offset = int(_query_param(url, "offset") or 0)
    next_offset = offset + len(items)
    total_count = payload.get("totalCount")
    if isinstance(total_count, int) and next_offset >= total_count:
        return None
    if total_count is None and len(items) < int(_query_param(url, config.limit_param) or PAGE_SIZE):
        return None
    return _replace_query_param(url, "offset", str(next_offset))


def _wait_strategy(retry_state: Any) -> float:
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, SplitIoRetryableError) and exc.retry_after is not None:
        return min(exc.retry_after, MAX_RETRY_WAIT_SECONDS)
    return min(2.0**retry_state.attempt_number, MAX_RETRY_WAIT_SECONDS)


@retry_with_deadline(
    retry=retry_if_exception_type((SplitIoRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
    wait=_wait_strategy,
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, logger: FilteringBoundLogger) -> Any:
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429:
        retry_after_header = response.headers.get("Retry-After")
        try:
            retry_after = float(retry_after_header) if retry_after_header else None
        except ValueError:
            # A non-numeric value (e.g. an HTTP-date) falls back to exponential backoff.
            retry_after = None
        logger.warning(f"Split rate limited (429), retrying. retry_after={retry_after_header}, url={url}")
        raise SplitIoRetryableError(f"Split rate limited: url={url}", retry_after=retry_after)

    if response.status_code >= 500:
        raise SplitIoRetryableError(f"Split server error: status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Split API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def validate_credentials(api_key: str, endpoint: str | None = None) -> int | None:
    """Probe an endpoint and return the HTTP status code (or None on transport failure).

    Fan-out endpoints can't be probed without a workspace id, so they (and the default
    source-create probe) check /workspaces — their prerequisite. Top-level endpoints probe
    their own path.
    """
    config = SPLIT_IO_ENDPOINTS.get(endpoint) if endpoint else None
    if config is None or config.requires_workspace:
        url = f"{BASE_URL}/workspaces?{urlencode({'limit': 1})}"
    else:
        params: dict[str, Any] = dict(config.extra_params)
        params["limit"] = 1
        url = f"{_base_url(config)}{config.path}?{urlencode(params)}"

    try:
        session = make_tracked_session(headers=_get_headers(api_key), redact_values=(api_key,))
        response = session.get(url, timeout=10)
        return response.status_code
    except Exception:
        return None


def _fetch_workspace_ids(session: requests.Session, logger: FilteringBoundLogger) -> list[str]:
    ids: list[str] = []
    url: str | None = _initial_url(SPLIT_IO_ENDPOINTS["workspaces"])
    while url:
        payload = _fetch_page(session, url, logger)
        items = _extract_items(payload, "objects")
        # `id` is the identifier every fan-out URL is built from; fail fast rather than
        # silently dropping a workspace (and all its flags/segments/environments) if absent.
        for item in items:
            ids.append(item["id"])
        url = _next_url(SPLIT_IO_ENDPOINTS["workspaces"], url, payload, items)
    return ids


def _paginate_resource(
    session: requests.Session,
    config: SplitIoEndpointConfig,
    start_url: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SplitIoResumeConfig],
    workspace_id: str,
    parent_columns: dict[str, str] | None = None,
    parent_key: str = "",
) -> Iterator[list[dict[str, Any]]]:
    url: str | None = start_url
    previous_fingerprint: tuple[int, str] | None = None
    while url:
        payload = _fetch_page(session, url, logger)
        items = _extract_items(payload, config.data_key)

        # If the server ignores our pagination params and keeps returning the same page,
        # stop rather than yield duplicates forever (fingerprint taken before mutation).
        fingerprint = (len(items), str(items[0])) if items else None
        if fingerprint is not None and fingerprint == previous_fingerprint:
            logger.warning(f"Split: identical page returned twice, stopping pagination. endpoint={config.name}")
            break
        previous_fingerprint = fingerprint

        if workspace_id:
            for item in items:
                item["_workspace_id"] = workspace_id
                if parent_columns:
                    item.update(parent_columns)

        next_url = _next_url(config, url, payload, items)
        resumable_source_manager.save_state(
            SplitIoResumeConfig(next_url=next_url or "", workspace_id=workspace_id, parent_key=parent_key)
        )
        if items:
            yield items
        else:
            resumable_source_manager.safe_point()
        url = next_url


def _list_parent_path_vars(
    session: requests.Session,
    levels: tuple[SplitIoParentLevel, ...],
    workspace_id: str,
    path_vars: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SplitIoResumeConfig],
) -> list[dict[str, str]]:
    if not levels:
        return [path_vars]
    level, rest = levels[0], levels[1:]
    result: list[dict[str, str]] = []
    url: str | None = _initial_url(level.config, workspace_id, path_vars)
    while url:
        payload = _fetch_page(session, url, logger)
        # Listing parents yields no rows; every row the staged cursor covers is already yielded.
        resumable_source_manager.safe_point()
        items = _extract_items(payload, level.config.data_key)
        for item in items:
            child_vars = {**path_vars, level.path_var: str(item[level.id_field])}
            result.extend(
                _list_parent_path_vars(session, rest, workspace_id, child_vars, logger, resumable_source_manager)
            )
        url = _next_url(level.config, url, payload, items)
    return result


def _get_nested_rows(
    session: requests.Session,
    config: SplitIoEndpointConfig,
    workspace_id: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SplitIoResumeConfig],
    resume: SplitIoResumeConfig | None,
) -> Iterator[list[dict[str, Any]]]:
    parents = _list_parent_path_vars(session, config.parents, workspace_id, {}, logger, resumable_source_manager)
    parent_keys = ["/".join(path_vars.values()) for path_vars in parents]

    start_idx = 0
    resume_url = ""
    if resume is not None and resume.parent_key in parent_keys:
        idx = parent_keys.index(resume.parent_key)
        # An empty next_url marks the saved parent as finished.
        start_idx = idx if resume.next_url else idx + 1
        resume_url = resume.next_url

    for i in range(start_idx, len(parents)):
        path_vars = parents[i]
        start_url = resume_url if i == start_idx and resume_url else _initial_url(config, workspace_id, path_vars)
        parent_columns = {level.column: path_vars[level.path_var] for level in config.parents}
        yield from _paginate_resource(
            session,
            config,
            start_url,
            logger,
            resumable_source_manager,
            workspace_id,
            parent_columns=parent_columns,
            parent_key=parent_keys[i],
        )


def _get_fanout_rows(
    session: requests.Session,
    config: SplitIoEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SplitIoResumeConfig],
    resume: SplitIoResumeConfig | None,
) -> Iterator[list[dict[str, Any]]]:
    workspace_ids = _fetch_workspace_ids(session, logger)
    if not workspace_ids:
        logger.warning(f"Split: no workspaces found, nothing to sync for endpoint={config.name}")
        return

    start_idx = 0
    resume_url: str | None = None
    if resume is not None and resume.workspace_id and resume.workspace_id in workspace_ids:
        idx = workspace_ids.index(resume.workspace_id)
        if config.parents:
            # The saved parent, not the workspace, is what finished; the nested walk works out
            # where to continue inside the workspace.
            start_idx = idx
        elif resume.next_url:
            # Mid-workspace: pick up at the saved page within that workspace.
            start_idx = idx
            resume_url = resume.next_url
        else:
            # The saved workspace finished (empty next_url marker); start at the next one.
            start_idx = idx + 1

    for i in range(start_idx, len(workspace_ids)):
        workspace_id = workspace_ids[i]
        if config.parents:
            workspace_resume = resume if resume is not None and resume.workspace_id == workspace_id else None
            yield from _get_nested_rows(
                session, config, workspace_id, logger, resumable_source_manager, workspace_resume
            )
            continue
        if i == start_idx and resume_url:
            start_url = resume_url
        else:
            start_url = _initial_url(config, workspace_id)
        yield from _paginate_resource(session, config, start_url, logger, resumable_source_manager, workspace_id)


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SplitIoResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = SPLIT_IO_ENDPOINTS[endpoint]
    session = make_tracked_session(headers=_get_headers(api_key), redact_values=(api_key,))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if config.requires_workspace:
        yield from _get_fanout_rows(session, config, logger, resumable_source_manager, resume)
        return

    if resume is not None and resume.next_url:
        logger.debug(f"Split: resuming endpoint={endpoint} from url={resume.next_url}")
        start_url = resume.next_url
    else:
        start_url = _initial_url(config)

    yield from _paginate_resource(session, config, start_url, logger, resumable_source_manager, workspace_id="")


def split_io_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SplitIoResumeConfig],
) -> SourceResponse:
    config = SPLIT_IO_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        # Split timestamps are epoch-millisecond integers and the datetime partitioner
        # expects epoch-seconds, so partitioning is intentionally left off to avoid
        # mis-bucketing rows far into the future.
        partition_mode=None,
        partition_keys=None,
    )
