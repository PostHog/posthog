import dataclasses
from typing import Any, Optional

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import AuthConfigBase
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.resend.settings import (
    RESEND_ENDPOINTS,
    ResendEndpointConfig,
)

RESEND_BASE_URL = "https://api.resend.com"
_EMAILS_DEFAULT_PAGE_SIZE = 100


@dataclasses.dataclass
class ResendResumeConfig:
    # Cursor for the /emails endpoint (Resend's `after` parameter).
    next_cursor: Optional[str] = None
    # Pre-framework fan-out bookmark. Kept (with a default) so previously saved state still parses;
    # no longer written — fan-out resume now lives in fanout_state.
    last_completed_parent_id: Optional[str] = None
    # Framework fan-out resume state for the contacts (per-audience) endpoint:
    # {"completed": [child_path, ...], "current": child_path | None, "child_state": {...} | None}.
    fanout_state: Optional[dict] = None


class ResendEmailsPaginator(BasePaginator):
    """Keyset pagination for /emails: Resend pages with `limit` + `after`, where `after` is the id
    of the last row on the previous page and `has_more` in the body signals whether more remain."""

    def __init__(self) -> None:
        super().__init__()
        self._cursor: Optional[str] = None

    def init_request(self, request: Request) -> None:
        # Honour a seeded resume cursor on the first request.
        if self._cursor is not None:
            if request.params is None:
                request.params = {}
            request.params["after"] = self._cursor

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        has_more = bool(response.json().get("has_more"))
        rows = data or []

        if not rows:
            if has_more:
                # has_more=True with an empty page would silently skip remaining rows; surface it
                # instead of producing a data gap.
                raise ValueError(f"Resend API returned an empty page but has_more=True for {response.url}")
            self._has_next_page = False
            return

        if has_more:
            # Advance the cursor from the last row's id (Resend keyset pagination on id). Direct
            # access so a missing id surfaces as a hard error rather than silently terminating.
            self._cursor = rows[-1]["id"]
            self._has_next_page = True
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        if self._cursor is not None:
            if request.params is None:
                request.params = {}
            request.params["after"] = self._cursor

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"next_cursor": self._cursor} if self._has_next_page and self._cursor is not None else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        cursor = state.get("next_cursor")
        if cursor is not None:
            self._cursor = str(cursor)
            self._has_next_page = True


def _client_config(auth: AuthConfigBase) -> ClientConfig:
    # Framework auth object (not a hand-built header) so the credential is redacted from logged
    # URLs/headers. Both auth methods pass a bearer here: a static API key, or the Resend OAuth
    # access token wrapped in an auth that re-mints it through the integration row (see oauth.py).
    return {
        "base_url": RESEND_BASE_URL,
        "headers": {"Accept": "application/json"},
        "auth": auth,
    }


def _simple_resource(
    config: ResendEndpointConfig,
    auth: AuthConfigBase,
    team_id: int,
    job_id: str,
    manager: ResumableSourceManager[ResendResumeConfig],
) -> Resource:
    """A single top-level list endpoint: flat (one page) or cursor-paginated (/emails)."""
    is_emails = config.name == "emails"

    params: dict[str, Any] = {}
    paginator: BasePaginator
    if is_emails:
        params["limit"] = config.page_size or _EMAILS_DEFAULT_PAGE_SIZE
        paginator = ResendEmailsPaginator()
    else:
        paginator = SinglePagePaginator()

    endpoint: Endpoint = {
        "path": config.path,
        "params": params,
        "paginator": paginator,
        # A missing `data` key yields a zero-row page (the API returns {"data": [...]}); tolerant,
        # matching the previous implementation's `data.get("data") or []`.
        "data_selector": "data",
    }

    rest_config: RESTAPIConfig = {
        "client": _client_config(auth),
        "resources": [{"name": config.name, "endpoint": endpoint}],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if is_emails and manager.can_resume():
        resume = manager.load_state()
        if resume is not None and resume.next_cursor is not None:
            initial_paginator_state = {"next_cursor": resume.next_cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; saved AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes) rather than skipping it.
        if state and state.get("next_cursor"):
            manager.save_state(ResendResumeConfig(next_cursor=str(state["next_cursor"])))

    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def _inject_audience_id(row: dict[str, Any]) -> dict[str, Any]:
    # include_from_parent lands the parent id as `_audiences_id`; rename it to the `_audience_id`
    # column the previous implementation injected onto every contact row.
    audience_id = row.pop("_audiences_id", None)
    if audience_id is not None:
        row["_audience_id"] = audience_id
    return row


def _fan_out_resource(
    config: ResendEndpointConfig,
    auth: AuthConfigBase,
    team_id: int,
    job_id: str,
    manager: ResumableSourceManager[ResendResumeConfig],
) -> Resource:
    """Fan the contacts endpoint out over every audience via a dependent resource: the framework
    fetches audiences, then GETs each audience's contacts and injects the audience id per row."""
    if config.parent is None:
        raise ValueError(f"Resend endpoint {config.name} has no parent configured")

    parent_config = RESEND_ENDPOINTS[config.parent]

    child_params: dict[str, Any] = {
        "audience_id": {"type": "resolve", "resource": config.parent, "field": "id"},
    }

    rest_config: RESTAPIConfig = {
        "client": _client_config(auth),
        "resources": [
            {
                "name": config.parent,
                "endpoint": {
                    "path": parent_config.path,
                    "paginator": SinglePagePaginator(),
                    "data_selector": "data",
                },
            },
            {
                "name": config.name,
                "endpoint": {
                    "path": config.path,
                    "params": child_params,
                    "paginator": SinglePagePaginator(),
                    "data_selector": "data",
                },
                "include_from_parent": ["id"],
                "data_map": _inject_audience_id,
            },
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if manager.can_resume():
        resume = manager.load_state()
        # Only framework-shaped fan-out state is resumable. A pre-migration bookmark
        # (last_completed_parent_id) can't be translated into the completed/current map, so such a
        # sync restarts fresh — safe, because the merge dedupes re-pulled rows on the primary key.
        if resume is not None and resume.fanout_state is not None:
            initial_paginator_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state:
            manager.save_state(ResendResumeConfig(fanout_state=state))

    resources = rest_api_resources(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    return next(r for r in resources if r.name == config.name)


def resend_source(
    auth: AuthConfigBase,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ResendResumeConfig],
) -> SourceResponse:
    config = RESEND_ENDPOINTS[endpoint]

    if config.parent is not None:
        resource = _fan_out_resource(config, auth, team_id, job_id, resumable_source_manager)
    else:
        resource = _simple_resource(config, auth, team_id, job_id, resumable_source_manager)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(token: str) -> bool:
    # /domains is a cheap read-only call that requires a valid credential with at least read scope —
    # Resend returns 401 for bad tokens and 200 for good ones. Works for a static API key or an OAuth
    # access token (both are sent as bearer tokens).
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(token,)),
        f"{RESEND_BASE_URL}/domains",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    return ok
