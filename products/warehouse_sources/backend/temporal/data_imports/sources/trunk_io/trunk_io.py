import dataclasses
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

from dateutil import parser as date_parser
from requests import Request, RequestException, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.trunk_io.settings import (
    BASE_URL,
    FAILING_TESTS_DEFAULT_LOOKBACK_DAYS,
    FAILING_TESTS_WINDOW_DAYS,
    PAGE_SIZE,
    UNHEALTHY_STATUSES,
)


@dataclasses.dataclass
class TrunkIoResumeConfig:
    """Unified resume shape for every Trunk endpoint. Each `source_for_pipeline` call gets its
    own resumable-source-manager key (namespaced by job id), so only the fields relevant to the
    endpoint being synced are ever populated."""

    page_token: str = ""
    status: Optional[str] = None
    window_start: Optional[str] = None


@dataclasses.dataclass
class TrunkRepo:
    host: str
    owner: str
    name: str

    def as_dict(self) -> dict[str, str]:
        return {"host": self.host, "owner": self.owner, "name": self.name}


class TrunkPageQueryPaginator(BasePaginator):
    """Trunk paginates via a nested `page_query: {page_size, page_token}` object in the POST
    body rather than a top-level query/json param, so the shared param-injection paginators
    (`JSONResponseCursorPaginator` et al.) don't apply directly."""

    def __init__(self, page_size: int = PAGE_SIZE, page_token: str = "") -> None:
        super().__init__()
        self.page_size = page_size
        self.page_token = page_token
        if page_token:
            self._has_next_page = True

    def init_request(self, request: Request) -> None:
        self._apply(request)

    def update_request(self, request: Request) -> None:
        self._apply(request)

    def _apply(self, request: Request) -> None:
        if request.json is None:
            request.json = {}
        request.json["page_query"] = {"page_size": self.page_size, "page_token": self.page_token}

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            page = response.json().get("page") or {}
        except Exception:
            page = {}
        next_token = page.get("next_page_token") or ""
        if next_token:
            self.page_token = next_token
            self._has_next_page = True
        else:
            self._has_next_page = False

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"page_token": self.page_token} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        token = state.get("page_token")
        if token:
            self.page_token = token
            self._has_next_page = True

    def __str__(self) -> str:
        return f"TrunkPageQueryPaginator(page_token={self.page_token!r})"


def _client(api_token: str) -> RESTClient:
    # Pin to the API origin and never follow redirects: the token rides a nonstandard
    # `x-api-token` header that `requests` won't strip on an off-origin redirect, so a 30x
    # from the API host would otherwise replay the credential to the redirect target.
    return RESTClient(
        base_url=BASE_URL,
        auth=APIKeyAuth(api_key=api_token, name="x-api-token", location="header"),
        allowed_hosts=[],
        allow_redirects=False,
    )


def _coerce_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    return date_parser.parse(str(value)).astimezone(UTC)


def _format_rfc3339(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def unhealthy_tests(
    api_token: str,
    repo: TrunkRepo,
    org_url_slug: str,
    resumable_source_manager: ResumableSourceManager[TrunkIoResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    client = _client(api_token)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_index = 0
    seed_token = ""
    if resume and resume.status in UNHEALTHY_STATUSES:
        start_index = UNHEALTHY_STATUSES.index(resume.status)
        seed_token = resume.page_token or ""

    for index, status in enumerate(UNHEALTHY_STATUSES[start_index:], start=start_index):
        page_token = seed_token if index == start_index else ""
        paginator = TrunkPageQueryPaginator(page_token=page_token)
        body = {"repo": repo.as_dict(), "org_url_slug": org_url_slug, "status": status}

        def checkpoint(state: Optional[dict[str, Any]], _status: str = status) -> None:
            # `RESTClient.paginate` deep-copies the paginator it's given, so this hook (fed the
            # deep-copied paginator's own resume state) is the only reliable way to observe
            # pagination progress — reading back the outer `paginator` variable would see a
            # stale, never-mutated copy.
            if state and state.get("page_token"):
                resumable_source_manager.save_state(
                    TrunkIoResumeConfig(status=_status, page_token=str(state["page_token"]))
                )

        for page in client.paginate(
            path="/flaky-tests/list-unhealthy-tests",
            method="post",
            json=body,
            paginator=paginator,
            data_selector="tests",
            resume_hook=checkpoint,
        ):
            if page:
                yield page

    resumable_source_manager.clear_state()


def quarantined_tests(
    api_token: str,
    repo: TrunkRepo,
    org_url_slug: str,
    resumable_source_manager: ResumableSourceManager[TrunkIoResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    client = _client(api_token)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page_token = resume.page_token if resume else ""
    paginator = TrunkPageQueryPaginator(page_token=page_token)
    body = {"repo": repo.as_dict(), "org_url_slug": org_url_slug}

    def checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state and state.get("page_token"):
            resumable_source_manager.save_state(TrunkIoResumeConfig(page_token=str(state["page_token"])))

    for page in client.paginate(
        path="/flaky-tests/list-quarantined-tests",
        method="post",
        json=body,
        paginator=paginator,
        data_selector="quarantined_tests",
        resume_hook=checkpoint,
    ):
        if page:
            yield page

    resumable_source_manager.clear_state()


def failing_tests(
    api_token: str,
    repo: TrunkRepo,
    org_url_slug: str,
    resumable_source_manager: ResumableSourceManager[TrunkIoResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> Iterator[list[dict[str, Any]]]:
    client = _client(api_token)
    now = datetime.now(UTC)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume and resume.window_start:
        window_start = _coerce_datetime(resume.window_start)
        page_token = resume.page_token or ""
    else:
        if should_use_incremental_field and db_incremental_field_last_value:
            window_start = _coerce_datetime(db_incremental_field_last_value)
        else:
            window_start = now - timedelta(days=FAILING_TESTS_DEFAULT_LOOKBACK_DAYS)
        page_token = ""

    while window_start < now:
        window_end = min(window_start + timedelta(days=FAILING_TESTS_WINDOW_DAYS), now)
        synced_through = _format_rfc3339(window_end)
        paginator = TrunkPageQueryPaginator(page_token=page_token)
        body = {
            "repo": repo.as_dict(),
            "org_url_slug": org_url_slug,
            "start_time": _format_rfc3339(window_start),
            "end_time": synced_through,
        }

        def checkpoint(state: Optional[dict[str, Any]], _window_start: datetime = window_start) -> None:
            if state and state.get("page_token"):
                resumable_source_manager.save_state(
                    TrunkIoResumeConfig(window_start=_window_start.isoformat(), page_token=str(state["page_token"]))
                )

        for page in client.paginate(
            path="/flaky-tests/list-failing-tests",
            method="post",
            json=body,
            paginator=paginator,
            data_selector="tests",
            resume_hook=checkpoint,
        ):
            if page:
                # Stamp the window boundary onto each row: there is no per-row "modified since"
                # field, so this is what lets the pipeline's incremental watermark advance.
                for row in page:
                    row["synced_through"] = synced_through
                yield page

        window_start = window_end
        page_token = ""
        resumable_source_manager.save_state(TrunkIoResumeConfig(window_start=window_start.isoformat(), page_token=""))

    resumable_source_manager.clear_state()


def validate_credentials(api_token: str, org_url_slug: str, repo: TrunkRepo) -> tuple[bool, str | None]:
    session = make_tracked_session(redact_values=(api_token,), allow_redirects=False)
    try:
        response = session.post(
            f"{BASE_URL}/flaky-tests/list-quarantined-tests",
            headers={"x-api-token": api_token},
            json={
                "repo": repo.as_dict(),
                "org_url_slug": org_url_slug,
                "page_query": {"page_size": 1, "page_token": ""},
            },
            timeout=15,
        )
    except RequestException as e:
        return False, f"Could not reach the Trunk.io API: {e}"

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return (
            False,
            "Trunk.io authentication failed. Check your API token, organization slug, and repository details.",
        )
    return False, f"Trunk.io API returned HTTP {response.status_code}."
