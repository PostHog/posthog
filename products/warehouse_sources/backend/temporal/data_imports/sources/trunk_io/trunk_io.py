import dataclasses
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, Optional

from dateutil import parser as date_parser
from requests import Request, RequestException, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    APIKeyAuth,
    BearerTokenAuth,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    JSONResponseCursorPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.trunk_io.settings import (
    BASE_URL,
    MERGE_QUEUE_PAGE_SIZE,
    TEST_METRICS_PARAMS,
    V2_BASE_URL,
    V2_PAGE_SIZE,
)


@dataclasses.dataclass(frozen=True)
class TrunkIoResumeConfig:
    """Unified resume shape for every Trunk endpoint. Each `source_for_pipeline` call gets its
    own resumable-source-manager key (namespaced by job id), so only the fields relevant to the
    endpoint being synced are ever populated."""

    cursor: Optional[str] = None
    synced_through: Optional[str] = None


@dataclasses.dataclass
class TrunkRepo:
    host: str
    owner: str
    name: str

    def as_dict(self) -> dict[str, str]:
        return {"host": self.host, "owner": self.owner, "name": self.name}


class TrunkCursorPaginator(BasePaginator):
    """The Merge Queue endpoints take `cursor`/`take` as top-level POST body params and return
    `nextCursor`."""

    def __init__(self, take: int = MERGE_QUEUE_PAGE_SIZE, cursor: str = "") -> None:
        super().__init__()
        self.take = take
        self.cursor = cursor
        if cursor:
            self._has_next_page = True

    def init_request(self, request: Request) -> None:
        self._apply(request)

    def update_request(self, request: Request) -> None:
        self._apply(request)

    def _apply(self, request: Request) -> None:
        if request.json is None:
            request.json = {}
        request.json["take"] = self.take
        # `cursor` is typed as a uuid, so send it only once we have one, because an empty string
        # is not a valid "first page" value.
        if self.cursor:
            request.json["cursor"] = self.cursor
        else:
            request.json.pop("cursor", None)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            next_cursor = response.json().get("nextCursor") or ""
        except Exception:
            next_cursor = ""
        if next_cursor:
            self.cursor = next_cursor
            self._has_next_page = True
        else:
            self._has_next_page = False

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"cursor": self.cursor} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        cursor = state.get("cursor")
        if cursor:
            self.cursor = cursor
            self._has_next_page = True

    def __str__(self) -> str:
        return f"TrunkCursorPaginator(cursor={self.cursor!r})"


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


def _v2_client(api_token: str) -> RESTClient:
    # v2 takes the same token as an `Authorization: Bearer` organization API key. Redirects stay
    # off for the same reason as `_client`.
    return RESTClient(
        base_url=V2_BASE_URL,
        auth=BearerTokenAuth(token=api_token),
        allowed_hosts=[],
        allow_redirects=False,
        request_timeout=(10.0, 60.0),
    )


def _coerce_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    return date_parser.parse(str(value)).astimezone(UTC)


def _format_rfc3339(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def merge_queue_pull_requests(
    api_token: str,
    repo: TrunkRepo,
    target_branch: str,
    resumable_source_manager: ResumableSourceManager[TrunkIoResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> Iterator[list[dict[str, Any]]]:
    client = _client(api_token)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor = (resume.cursor if resume else None) or ""
    # Pin the stamp across a resume so the second half of an interrupted run doesn't claim
    # coverage the first half never had.
    synced_through = (resume.synced_through if resume else None) or _format_rfc3339(datetime.now(UTC))

    body: dict[str, Any] = {"repo": repo.as_dict(), "targetBranch": target_branch}
    if should_use_incremental_field and db_incremental_field_last_value:
        body["since"] = _format_rfc3339(_coerce_datetime(db_incremental_field_last_value))

    def checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state and state.get("cursor"):
            resumable_source_manager.save_state(
                TrunkIoResumeConfig(cursor=str(state["cursor"]), synced_through=synced_through)
            )

    for page in client.paginate(
        path="/listPullRequests",
        method="post",
        json=body,
        paginator=TrunkCursorPaginator(cursor=cursor),
        data_selector="pullRequests",
        resume_hook=checkpoint,
    ):
        if page:
            for row in page:
                row["synced_through"] = synced_through
            yield page

    resumable_source_manager.clear_state()


def _v2_list(
    api_token: str,
    path: str,
    resumable_source_manager: ResumableSourceManager[TrunkIoResumeConfig],
    params: Optional[dict[str, Any]] = None,
    synced_through: Optional[str] = None,
) -> Iterator[list[dict[str, Any]]]:
    client = _v2_client(api_token)
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    def checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state and state.get("cursor"):
            resumable_source_manager.save_state(
                TrunkIoResumeConfig(cursor=str(state["cursor"]), synced_through=synced_through)
            )

    for page in client.paginate(
        path=path,
        method="get",
        params={"limit": V2_PAGE_SIZE, **(params or {})},
        paginator=JSONResponseCursorPaginator(cursor_path="nextCursor", cursor_param="cursor"),
        data_selector="data",
        resume_hook=checkpoint,
        initial_paginator_state={"cursor": resume.cursor} if resume and resume.cursor else None,
    ):
        if page:
            if synced_through:
                for row in page:
                    row["synced_through"] = synced_through
            yield page

    resumable_source_manager.clear_state()


def list_test_collections(
    api_token: str,
    resumable_source_manager: ResumableSourceManager[TrunkIoResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    return _v2_list(api_token, "/v2/test-collections", resumable_source_manager)


def list_tests(
    api_token: str,
    resumable_source_manager: ResumableSourceManager[TrunkIoResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    # No `testCollectionId` filter, so this lists tests across every collection in the org.
    return _v2_list(api_token, "/v2/tests", resumable_source_manager)


def unhealthy_tests(
    api_token: str,
    resumable_source_manager: ResumableSourceManager[TrunkIoResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    return _v2_list(
        api_token,
        "/v2/tests",
        resumable_source_manager,
        params={"status": "flaky,broken", **TEST_METRICS_PARAMS},
    )


def quarantined_tests(
    api_token: str,
    resumable_source_manager: ResumableSourceManager[TrunkIoResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    return _v2_list(
        api_token,
        "/v2/tests",
        resumable_source_manager,
        params={"quarantineState": "quarantined", **TEST_METRICS_PARAMS},
    )


def failing_tests(
    api_token: str,
    resumable_source_manager: ResumableSourceManager[TrunkIoResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    synced_through = (resume.synced_through if resume else None) or _format_rfc3339(datetime.now(UTC))
    # A `lastFailureAt` sort drops tests with no failure in `period`, which is what makes this
    # the failing set rather than every test.
    return _v2_list(
        api_token,
        "/v2/tests",
        resumable_source_manager,
        params={"sort": "lastFailureAt", **TEST_METRICS_PARAMS},
        synced_through=synced_through,
    )


def validate_credentials(api_token: str) -> tuple[bool, str | None]:
    session = make_tracked_session(redact_values=(api_token,), allow_redirects=False)
    try:
        response = session.get(
            f"{V2_BASE_URL}/v2/tests",
            headers={"Authorization": f"Bearer {api_token}"},
            params={"limit": 1},
            timeout=15,
        )
    except RequestException as e:
        return False, f"Could not reach the Trunk.io API: {e}"

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Trunk.io authentication failed. Check your API token."
    return False, f"Trunk.io API returned HTTP {response.status_code}."
