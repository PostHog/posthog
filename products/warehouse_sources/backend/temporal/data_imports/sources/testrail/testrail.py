import re
import dataclasses
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.testrail.settings import (
    PAGE_SIZE,
    TESTRAIL_ENDPOINTS,
)

REQUEST_TIMEOUT_SECONDS = 60
# Cheap probe confirming the credentials are genuine and the instance's API toggle is enabled.
DEFAULT_PROBE_METHOD = "get_projects"

# A single DNS label: letters, digits, hyphens. Rejects anything that could retarget the host
# (slashes, `@`, dots) so the stored API key is only ever sent to `<subdomain>.testrail.io`.
_SUBDOMAIN_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


class TestrailRetryableError(Exception):
    pass


@dataclasses.dataclass
class TestrailResumeConfig:
    # Position of the NEXT page to fetch within the deterministic parent walk. `parent_path`
    # identifies the fan-out parent: [] for instance-level endpoints, [project_id],
    # [project_id, suite_id] or [run_id] for scoped ones. `phase` separates the two passes of
    # the `runs` endpoint (0 = standalone runs via get_runs, 1 = plan-entry runs via
    # get_plans/get_plan). Parents are walked in ascending id order, so a resume skips every
    # position before the saved one; merge on `id` dedupes any boundary page re-fetched.
    parent_path: list[int] = dataclasses.field(default_factory=list)
    phase: int = 0
    offset: int = 0


class _ResumeCursor:
    """Maps a saved crash position onto the deterministic parent walk.

    Positions are ``(parent_path, phase)`` tuples visited in strictly ascending order, so a
    parent that compares below the saved position was fully synced before the crash and is
    skipped; the saved parent itself restarts at the saved offset; everything after syncs
    from offset 0.
    """

    def __init__(self, resume: TestrailResumeConfig | None) -> None:
        self._position = (tuple(resume.parent_path), resume.phase) if resume is not None else None
        self._offset = resume.offset if resume is not None else 0

    def start_offset(self, parent_path: tuple[int, ...], phase: int = 0) -> int | None:
        """Offset to start this parent at, or ``None`` to skip it entirely."""
        if self._position is None:
            return 0
        current = (parent_path, phase)
        if current < self._position:
            return None
        if current == self._position:
            return self._offset
        return 0


def normalize_subdomain(subdomain: str) -> str:
    """Reduce user input to a bare, validated TestRail Cloud subdomain label.

    Accepts either the full host (``yourcompany.testrail.io``) or the bare subdomain
    (``yourcompany``). Raises ``ValueError`` on anything that isn't a single DNS label so the
    API key can never be retargeted away from ``<subdomain>.testrail.io``.
    """
    cleaned = subdomain.strip().removeprefix("https://").removeprefix("http://")
    cleaned = cleaned.strip("/")
    cleaned = cleaned.removesuffix(".testrail.io").removesuffix(".testrail.com")
    if not _SUBDOMAIN_RE.match(cleaned):
        raise ValueError(
            f"Invalid TestRail address: {subdomain!r}. Enter just your subdomain, e.g. 'yourcompany' "
            "for yourcompany.testrail.io."
        )
    return cleaned


def _base_url(subdomain: str) -> str:
    return f"https://{normalize_subdomain(subdomain)}.testrail.io/index.php?"


def _build_url(
    base_url: str, method: str, path_id: Optional[int] = None, params: Optional[dict[str, Any]] = None
) -> str:
    # TestRail's router keeps the whole API path inside the query string
    # (index.php?/api/v2/get_cases/1&suite_id=2&limit=250), so extra params are appended
    # with `&`, never a second `?`.
    url = f"{base_url}/api/v2/{method}"
    if path_id is not None:
        url = f"{url}/{path_id}"
    if params:
        url = f"{url}&{urlencode(params)}"
    return url


def _make_session(username: str, api_key: str) -> requests.Session:
    session = make_tracked_session(
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        redact_values=(api_key,),
    )
    # TestRail auth is HTTP Basic with the account email plus an API key (or password).
    session.auth = (username, api_key)
    return session


def _to_epoch(value: Any) -> int:
    """Coerce an incremental cursor into the UNIX timestamp TestRail's `*_after` filters expect."""
    if isinstance(value, bool):
        raise ValueError(f"Cannot use {value!r} as a TestRail timestamp cursor")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return int(aware.timestamp())
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp())
    return int(str(value))


@retry(
    retry=retry_if_exception_type((TestrailRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=2, max=60),
    reraise=True,
)
def _fetch(session: requests.Session, url: str, logger: FilteringBoundLogger) -> Any:
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

    # TestRail Cloud rate-limits (~180-300 req/min depending on plan) and answers 429 with a
    # Retry-After; exponential backoff with jitter stays under the window. Transient 5xx retry too.
    if response.status_code == 429 or response.status_code >= 500:
        raise TestrailRetryableError(f"TestRail API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"TestRail API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _extract_items(data: Any, response_key: str) -> tuple[list[dict[str, Any]], bool]:
    """Normalise both TestRail response shapes into ``(items, has_more)``.

    Bulk endpoints (6.7+) wrap records in {"offset", "limit", "size", "_links", "<key>": [...]};
    dictionary endpoints (suites, statuses, ...) return a plain JSON array. `has_more` comes
    exclusively from `_links.next` — a full page is never treated as "more" on its own, so an
    endpoint that ignores limit/offset can't loop forever.
    """
    if isinstance(data, list):
        return data, False
    if isinstance(data, dict) and isinstance(data.get(response_key), list):
        links = data.get("_links")
        has_more = isinstance(links, dict) and bool(links.get("next"))
        return data[response_key], has_more
    raise TestrailRetryableError(f"TestRail returned an unexpected payload shape: {type(data).__name__}")


def _fetch_list(
    session: requests.Session,
    base_url: str,
    method: str,
    path_id: Optional[int],
    params: dict[str, Any],
    response_key: str,
    logger: FilteringBoundLogger,
) -> list[dict[str, Any]]:
    data = _fetch(session, _build_url(base_url, method, path_id, params), logger)
    items, _ = _extract_items(data, response_key)
    return items


def _paginate(
    session: requests.Session,
    base_url: str,
    method: str,
    path_id: Optional[int],
    extra_params: dict[str, Any],
    response_key: str,
    logger: FilteringBoundLogger,
    start_offset: int = 0,
    save_state: Optional[Callable[[int], None]] = None,
) -> Iterator[list[dict[str, Any]]]:
    """Walk one parent's limit/offset pages, yielding each page's records.

    ``save_state`` (when set) is called with the NEXT page's offset after the consumer has
    fully processed the yielded page — save AFTER yielding, so a crash re-fetches the last
    page and merge dedupes it on the primary key rather than skipping it.
    """
    offset = start_offset
    while True:
        params: dict[str, Any] = {**extra_params, "limit": PAGE_SIZE, "offset": offset}
        data = _fetch(session, _build_url(base_url, method, path_id, params), logger)
        items, has_more = _extract_items(data, response_key)
        if items:
            yield items
            if save_state is not None:
                save_state(offset + PAGE_SIZE)
        if not has_more:
            break
        offset += PAGE_SIZE


def _make_checkpoint(
    resumable_source_manager: ResumableSourceManager[TestrailResumeConfig],
    parent_path: tuple[int, ...],
    phase: int = 0,
) -> Callable[[int], None]:
    def save(next_offset: int) -> None:
        resumable_source_manager.save_state(
            TestrailResumeConfig(parent_path=list(parent_path), phase=phase, offset=next_offset)
        )

    return save


def _list_project_ids(session: requests.Session, base_url: str, logger: FilteringBoundLogger) -> list[int]:
    project_ids: list[int] = []
    for page in _paginate(session, base_url, "get_projects", None, {}, "projects", logger):
        project_ids.extend(project["id"] for project in page)
    return sorted(project_ids)


def _list_suite_units(
    session: requests.Session, base_url: str, project_ids: list[int], logger: FilteringBoundLogger
) -> list[tuple[int, int]]:
    """Every (project_id, suite_id) pair, ascending. get_suites also returns the default suite
    of single-suite-mode projects, so the same walk covers every suite mode."""
    units: list[tuple[int, int]] = []
    for project_id in project_ids:
        suites = _fetch_list(session, base_url, "get_suites", project_id, {}, "suites", logger)
        units.extend((project_id, suite["id"]) for suite in suites)
    return sorted(units)


def _plan_entry_runs(
    session: requests.Session, base_url: str, plan_id: int, logger: FilteringBoundLogger
) -> list[dict[str, Any]]:
    """Runs embedded in a plan's entries (same record shape as get_runs rows, with plan_id set).
    get_plans omits `entries`, so each plan needs one get_plan detail request."""
    plan = _fetch(session, _build_url(base_url, "get_plan", plan_id), logger)
    if not isinstance(plan, dict):
        raise TestrailRetryableError(f"TestRail returned an unexpected get_plan payload: {type(plan).__name__}")
    runs: list[dict[str, Any]] = []
    for entry in plan.get("entries") or []:
        runs.extend(entry.get("runs") or [])
    return runs


def _list_run_ids(
    session: requests.Session, base_url: str, project_ids: list[int], logger: FilteringBoundLogger
) -> list[int]:
    """Every run id, ascending: standalone runs (get_runs excludes runs inside plans) plus
    plan-entry runs, so tests/results cover plan-driven QA workflows too."""
    run_ids: set[int] = set()
    for project_id in project_ids:
        for page in _paginate(session, base_url, "get_runs", project_id, {}, "runs", logger):
            run_ids.update(run["id"] for run in page)
        for page in _paginate(session, base_url, "get_plans", project_id, {}, "plans", logger):
            for plan in page:
                run_ids.update(run["id"] for run in _plan_entry_runs(session, base_url, plan["id"], logger))
    logger.debug(f"TestRail: enumerated {len(run_ids)} runs across {len(project_ids)} projects")
    return sorted(run_ids)


def _users_rows(
    session: requests.Session, base_url: str, logger: FilteringBoundLogger
) -> Iterator[list[dict[str, Any]]]:
    """Instance-wide get_users needs an administrator account; everyone else must pass a
    project id. Try the admin listing first (it also includes users with only global access),
    then fall back to per-project listing with client-side dedupe. The walk is one cheap
    request per project, so it restarts from scratch instead of checkpointing — a resumed
    seen-set would otherwise re-emit duplicate rows into a full-refresh table.
    """
    try:
        users = _fetch_list(session, base_url, "get_users", None, {}, "users", logger)
        if users:
            yield users
        return
    except requests.HTTPError as e:
        if e.response is None or e.response.status_code != 403:
            raise
        logger.debug("TestRail: instance-wide get_users forbidden, falling back to per-project listing")

    seen: set[Any] = set()
    for project_id in _list_project_ids(session, base_url, logger):
        users = _fetch_list(session, base_url, "get_users", project_id, {}, "users", logger)
        # Direct access on the user's id (its primary key): a user without one is a broken
        # response that should fail loudly, not get silently deduplicated against None.
        fresh = [user for user in users if user["id"] not in seen]
        seen.update(user["id"] for user in fresh)
        if fresh:
            yield fresh


def _runs_rows(
    session: requests.Session,
    base_url: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[TestrailResumeConfig],
    cursor: _ResumeCursor,
    cutoff: int | None,
) -> Iterator[list[dict[str, Any]]]:
    """The runs table combines, per project, standalone runs (phase 0: get_runs, which
    excludes runs inside plans) and plan-entry runs (phase 1: get_plans -> get_plan ->
    entries[].runs[]). On incremental syncs created_after bounds get_runs directly and bounds
    plan-entry runs via their PLAN's creation time — runs added later to a pre-watermark plan
    only appear on a full refresh (documented in the source docs).
    """
    extra_params: dict[str, Any] = {"created_after": cutoff} if cutoff is not None else {}
    project_ids = _list_project_ids(session, base_url, logger)

    for project_id in project_ids:
        offset = cursor.start_offset((project_id,), phase=0)
        if offset is not None:
            yield from _paginate(
                session,
                base_url,
                "get_runs",
                project_id,
                extra_params,
                "runs",
                logger,
                start_offset=offset,
                save_state=_make_checkpoint(resumable_source_manager, (project_id,), phase=0),
            )

        offset = cursor.start_offset((project_id,), phase=1)
        if offset is None:
            continue
        for plan_page in _paginate(
            session,
            base_url,
            "get_plans",
            project_id,
            extra_params,
            "plans",
            logger,
            start_offset=offset,
            save_state=_make_checkpoint(resumable_source_manager, (project_id,), phase=1),
        ):
            runs: list[dict[str, Any]] = []
            for plan in plan_page:
                runs.extend(_plan_entry_runs(session, base_url, plan["id"], logger))
            if runs:
                yield runs


def get_rows(
    subdomain: str,
    username: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[TestrailResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = TESTRAIL_ENDPOINTS[endpoint]
    base_url = _base_url(subdomain)
    session = _make_session(username, api_key)

    cutoff: int | None = None
    if config.incremental_param is not None and should_use_incremental_field and db_incremental_field_last_value:
        cutoff = _to_epoch(db_incremental_field_last_value)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor = _ResumeCursor(resume)
    if resume is not None:
        logger.debug(
            f"TestRail: resuming {endpoint} from parent={resume.parent_path} phase={resume.phase} "
            f"offset={resume.offset}"
        )

    if endpoint == "runs":
        yield from _runs_rows(session, base_url, logger, resumable_source_manager, cursor, cutoff)
        return

    if endpoint == "users":
        yield from _users_rows(session, base_url, logger)
        return

    extra_params: dict[str, Any] = {}
    if cutoff is not None and config.incremental_param is not None:
        extra_params[config.incremental_param] = cutoff

    if config.scope == "instance":
        if not config.paginated:
            items = _fetch_list(session, base_url, config.method, None, {}, config.response_key, logger)
            if items:
                yield items
            return
        offset = cursor.start_offset(())
        if offset is None:
            return
        yield from _paginate(
            session,
            base_url,
            config.method,
            None,
            extra_params,
            config.response_key,
            logger,
            start_offset=offset,
            save_state=_make_checkpoint(resumable_source_manager, ()),
        )
        return

    project_ids = _list_project_ids(session, base_url, logger)

    if config.scope == "project":
        if not config.paginated:
            # One cheap request per project (e.g. suites) — no checkpointing needed.
            for project_id in project_ids:
                items = _fetch_list(session, base_url, config.method, project_id, {}, config.response_key, logger)
                if items:
                    yield items
            return
        for project_id in project_ids:
            offset = cursor.start_offset((project_id,))
            if offset is None:
                continue
            yield from _paginate(
                session,
                base_url,
                config.method,
                project_id,
                extra_params,
                config.response_key,
                logger,
                start_offset=offset,
                save_state=_make_checkpoint(resumable_source_manager, (project_id,)),
            )
        return

    if config.scope == "suite":
        for project_id, suite_id in _list_suite_units(session, base_url, project_ids, logger):
            offset = cursor.start_offset((project_id, suite_id))
            if offset is None:
                continue
            yield from _paginate(
                session,
                base_url,
                config.method,
                project_id,
                {**extra_params, "suite_id": suite_id},
                config.response_key,
                logger,
                start_offset=offset,
                save_state=_make_checkpoint(resumable_source_manager, (project_id, suite_id)),
            )
        return

    # scope == "run": tests and results fan out over every run (standalone + plan-entry).
    for run_id in _list_run_ids(session, base_url, project_ids, logger):
        offset = cursor.start_offset((run_id,))
        if offset is None:
            continue
        yield from _paginate(
            session,
            base_url,
            config.method,
            run_id,
            extra_params,
            config.response_key,
            logger,
            start_offset=offset,
            save_state=_make_checkpoint(resumable_source_manager, (run_id,)),
        )


def testrail_source(
    subdomain: str,
    username: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[TestrailResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = TESTRAIL_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            subdomain=subdomain,
            username=username,
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        # Fan-out across projects/suites/runs means rows never arrive globally time-ordered, so
        # incremental endpoints declare "desc": the watermark commits only once the whole sync
        # completes instead of checkpointing after every batch.
        sort_mode="desc" if config.incremental_param is not None else "asc",
    )


def _error_message(response: requests.Response) -> Optional[str]:
    # TestRail error bodies are {"error": "..."} with a user-actionable message (bad credentials
    # vs the API toggle being disabled), so surface it verbatim when present.
    try:
        body = response.json()
    except Exception:
        return None
    if isinstance(body, dict) and isinstance(body.get("error"), str):
        return body["error"]
    return None


def check_access(subdomain: str, username: str, api_key: str) -> tuple[int, Optional[str]]:
    """Probe get_projects to validate the credentials and the instance's API toggle.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth or API-disabled
    failure (message carries TestRail's own explanation when available), ``0`` for a
    connection problem, other HTTP status otherwise. Raises ``ValueError`` on a malformed
    subdomain so the caller can surface a precise message.
    """
    session = _make_session(username, api_key)
    url = _build_url(_base_url(subdomain), DEFAULT_PROBE_METHOD, None, {"limit": 1})
    try:
        response = session.get(url, timeout=15)
    except Exception as e:
        return 0, f"Could not connect to TestRail: {e}"

    if response.status_code in (401, 403):
        return response.status_code, _error_message(response)

    if not response.ok:
        return response.status_code, f"TestRail returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(subdomain: str, username: str, api_key: str) -> tuple[bool, str | None]:
    try:
        status, message = check_access(subdomain, username, api_key)
    except ValueError as e:
        return False, str(e)

    if status == 200:
        return True, None
    if status == 401:
        return False, message or "Invalid TestRail email or API key"
    if status == 403:
        return False, (
            message
            or "TestRail rejected the request. Check that the API is enabled under "
            "Administration > Site Settings > API."
        )
    return False, message or "Could not validate TestRail credentials"
