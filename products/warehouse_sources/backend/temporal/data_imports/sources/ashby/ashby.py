import dataclasses
from collections.abc import Callable, Iterator
from typing import Any, Optional

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.ashby.settings import (
    ASHBY_ENDPOINTS,
    PAGE_SIZE,
    AshbyEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

ASHBY_BASE_URL = "https://api.ashbyhq.com"
# Cheap endpoint to confirm a key is genuine when no specific schema is being validated.
DEFAULT_PROBE_PATH = "department.list"

AUTH_ERROR_HINT = "Ashby API authentication or permission error"


class AshbyAPIError(Exception):
    pass


@dataclasses.dataclass
class AshbyResumeConfig:
    cursor: Optional[str] = None
    """Next page cursor for a directly listed endpoint."""
    parent_cursor: Optional[str] = None
    """Fan-out: the cursor that fetched the parent page being walked."""
    parent_index: int = 0
    """Fan-out: how many parents in that page are already finished."""
    child_cursor: Optional[str] = None
    """Fan-out: next page cursor for the parent currently in progress."""


def _headers() -> dict[str, str]:
    return {"Content-Type": "application/json", "Accept": "application/json"}


def _classify_failure_message(errors: list[Any]) -> tuple[bool, str]:
    """Return ``(is_auth_related, joined_message)`` for an ``success: false`` payload.

    Ashby reports many failures as HTTP 200 with ``success: false`` and an ``errors`` array,
    so we sniff the messages to decide whether it's an unrecoverable auth/permission problem.
    """
    message = "; ".join(str(e) for e in errors) or "unknown error"
    lowered = message.lower()
    is_auth = any(
        hint in lowered
        for hint in ("unauthorized", "not authorized", "invalid api key", "permission", "forbidden", "authentication")
    )
    return is_auth, message


def _errors_from_payload(data: dict[str, Any]) -> list[Any]:
    errors = data.get("errors")
    if errors:
        return errors if isinstance(errors, list) else [errors]
    if data.get("error"):
        return [data["error"]]
    return []


class AshbyCursorPaginator(JSONResponseCursorPaginator):
    """Cursor-in-JSON-body pagination plus Ashby's HTTP-200 error envelope.

    Ashby reports many failures as HTTP 200 with ``success: false`` and an ``errors``
    array — raise on those (auth-ish messages carry ``AUTH_ERROR_HINT`` so the job-level
    classifier treats them as non-retryable). Termination honors ``moreDataAvailable``,
    which can be false even when a ``nextCursor`` is present.
    """

    def __init__(self, path: str) -> None:
        super().__init__(cursor_path="nextCursor", cursor_param="cursor", param_location="json")
        self._path = path

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        payload = response.json()
        if not payload.get("success", False):
            is_auth, message = _classify_failure_message(_errors_from_payload(payload))
            if is_auth:
                raise AshbyAPIError(f"{AUTH_ERROR_HINT} for path {self._path}: {message}")
            raise AshbyAPIError(f"Ashby API error for path {self._path}: {message}")

        super().update_state(response, data)
        if not payload.get("moreDataAvailable", False):
            self._has_next_page = False


def _rest_config(api_key: str, name: str, path: str, body: dict[str, Any]) -> RESTAPIConfig:
    return {
        "client": {
            "base_url": ASHBY_BASE_URL,
            "headers": _headers(),
            # Ashby uses HTTP Basic auth: API key as username, empty password.
            "auth": {"type": "http_basic", "username": api_key, "password": ""},
            "paginator": AshbyCursorPaginator(path),
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": name,
                "endpoint": {
                    "path": path,
                    "method": "post",
                    "json": body,
                    "data_selector": "results",
                },
            }
        ],
    }


def _iter_pages(
    api_key: str,
    name: str,
    path: str,
    body: dict[str, Any],
    team_id: int,
    job_id: str,
    *,
    start_cursor: Optional[str] = None,
    on_next_cursor: Optional[Callable[[Optional[str]], None]] = None,
) -> Iterator[tuple[list[dict[str, Any]], Optional[str]]]:
    """Yield each page of an Ashby list method with the cursor that fetched it.

    ``on_next_cursor`` receives the cursor for the page after the one just yielded, or ``None``
    once the listing is exhausted.
    """
    next_cursor: dict[str, Optional[str]] = {"value": None}

    def remember(state: Optional[dict[str, Any]]) -> None:
        next_cursor["value"] = str(state["cursor"]) if state and state.get("cursor") else None
        if on_next_cursor is not None:
            on_next_cursor(next_cursor["value"])

    resource = rest_api_resource(
        _rest_config(api_key, name, path, body),
        team_id,
        job_id,
        None,  # every Ashby endpoint is full refresh
        resume_hook=remember,
        initial_paginator_state={"cursor": start_cursor} if start_cursor else None,
    )

    cursor = start_cursor
    for index, page in enumerate(resource):
        if index:
            # ``remember`` for the previous page runs as the resource advances above, so by now
            # it holds the cursor that fetched the page we are about to yield.
            cursor = next_cursor["value"]
        yield page, cursor


def _listed_pages(
    api_key: str,
    config: AshbyEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[AshbyResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    def save_checkpoint(cursor: Optional[str]) -> None:
        # Persist only when a next page remains; the checkpoint fires AFTER a page is yielded so a
        # crash re-fetches from the next page (already-yielded pages are persisted); merge/replace
        # dedupes on the primary key.
        if cursor:
            resumable_source_manager.save_state(AshbyResumeConfig(cursor=cursor))

    body: dict[str, Any] = {} if config.page_size is None else {"limit": config.page_size}
    for page, _ in _iter_pages(
        api_key,
        config.name,
        config.path,
        body,
        team_id,
        job_id,
        start_cursor=resume.cursor if resume else None,
        on_next_cursor=save_checkpoint,
    ):
        yield [row for item in page for row in (item.get(config.nested_field) or [])] if config.nested_field else page


def _fanned_out_pages(
    api_key: str,
    config: AshbyEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[AshbyResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    fanout = config.fanout
    assert fanout is not None

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    child_cursor = resume.child_cursor if resume else None
    skip = resume.parent_index if resume else 0

    for parent_page, parent_cursor in _iter_pages(
        api_key,
        fanout.parent_path,
        fanout.parent_path,
        {"limit": PAGE_SIZE},
        team_id,
        job_id,
        start_cursor=resume.parent_cursor if resume else None,
    ):
        for index, parent in enumerate(parent_page):
            if index < skip:
                continue

            parent_id = parent["id"]
            body: dict[str, Any] = {fanout.resolve_param: parent_id}
            if config.page_size is not None:
                body["limit"] = config.page_size

            def save_child_checkpoint(
                cursor: Optional[str], page: Optional[str] = parent_cursor, at: int = index
            ) -> None:
                if cursor:
                    resumable_source_manager.save_state(
                        AshbyResumeConfig(parent_cursor=page, parent_index=at, child_cursor=cursor)
                    )

            for child_page, _ in _iter_pages(
                api_key,
                config.name,
                config.path,
                body,
                team_id,
                job_id,
                start_cursor=child_cursor,
                on_next_cursor=save_child_checkpoint,
            ):
                if fanout.parent_id_field:
                    for row in child_page:
                        row.setdefault(fanout.parent_id_field, parent_id)
                yield child_page

            child_cursor = None
            resumable_source_manager.save_state(AshbyResumeConfig(parent_cursor=parent_cursor, parent_index=index + 1))

        skip = 0


def ashby_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[AshbyResumeConfig],
) -> SourceResponse:
    config = ASHBY_ENDPOINTS[endpoint]
    pages = _fanned_out_pages if config.fanout else _listed_pages

    return SourceResponse(
        name=endpoint,
        items=lambda: pages(api_key, config, team_id, job_id, resumable_source_manager),
        primary_keys=config.primary_key,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def check_access(api_key: str, path: str) -> tuple[int, Optional[str]]:
    """Probe a single endpoint to validate credentials.

    Ashby's RPC endpoints are POST-only and report many failures as HTTP 200 with
    ``success: false``, so the generic GET-based ``validate_via_probe`` can't express this
    check. Returns a normalized ``(status, message)`` where status mimics HTTP semantics:
      200 = reachable, 401 = bad key, 403 = valid key without scope, other = unexpected.
    """
    session = make_tracked_session(redact_values=(api_key,))
    try:
        response = session.post(
            f"{ASHBY_BASE_URL}/{path}", json={"limit": 1}, auth=(api_key, ""), headers=_headers(), timeout=15
        )
    except Exception as e:
        return 0, f"Could not connect to Ashby: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"Ashby returned HTTP {response.status_code}"

    try:
        data = response.json()
    except ValueError:
        # A 200 that isn't JSON (e.g. a proxy/maintenance HTML page) is not a valid Ashby
        # response — fail validation rather than reporting the credentials as good.
        return 0, "Ashby returned a non-JSON response"

    if data.get("success", False):
        return 200, None

    is_auth, message = _classify_failure_message(_errors_from_payload(data))
    if is_auth:
        # Can't distinguish bad-key from missing-scope purely from the message; treat as 403
        # (valid key, insufficient scope) so source-create accepts keys scoped to a subset of
        # endpoints. A genuinely invalid key surfaces as HTTP 401 above.
        return 403, message
    return 400, message
