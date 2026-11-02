import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    JSONResponsePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import Endpoint
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.utils import (
    resolve_request_url,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.safetyculture.settings import (
    SAFETYCULTURE_ENDPOINTS,
)

SAFETYCULTURE_BASE_URL = "https://api.safetyculture.io"
# Cheap feed used to confirm an API token is genuine. Feed access is permission-scoped, so a 403
# here still proves the token itself is valid (see `validate_credentials` on the source class).
DEFAULT_PROBE_PATH = "/feed/users"
STRUCTURES_PAGE_SIZE = 100  # Documented maximum for Search structures.


@dataclasses.dataclass(frozen=True)
class SafetyCultureResumeConfig:
    # The next page to fetch, resolved from the API's `metadata.next_page` (the docs forbid
    # constructing it yourself). It embeds every filter — including `modified_after` on an
    # incremental sync — so a crashed sync resumes from the page after the last one yielded; merge
    # dedupes the re-pulled page on `id`. Historic saves stored a relative path; the paginator
    # resolves either form against the API host on load.
    next_page: str | None = None
    # Structures search only: the structure type being walked and the page token within it.
    structure_type_index: int | None = None
    page_token: str | None = None


def _format_modified_after(value: Any) -> str:
    """Format an incremental cursor as the Internet Date-Time string SafetyCulture expects.

    Since 2025-02-01 the Feed APIs reject anything that isn't `{Y}-{m}-{d}T{H}:{M}:{S}[.{frac}]Z`.
    """
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    return str(value)


class SafetyCultureFeedPaginator(JSONResponsePaginator):
    """Follows SafetyCulture Data Feed pagination.

    Every feed wraps records in `{"metadata": {"next_page", "remaining_records"}, "data": [...]}`.
    `metadata.next_page` is a RELATIVE path (e.g. `/feed/users?opaque-cursor=xyz`) that must be
    followed verbatim, so it's resolved against the API host before it becomes a request URL. An
    empty page also terminates the feed defensively, so a lingering cursor can never loop forever.
    """

    def __init__(self) -> None:
        super().__init__(next_url_path="metadata.next_page")

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if not data:
            self._has_next_page = False
            return
        super().update_state(response, data)
        self._absolutize()

    def set_resume_state(self, state: dict[str, Any]) -> None:
        super().set_resume_state(state)
        self._absolutize()

    def _absolutize(self) -> None:
        if self._next_url and not self._next_url.startswith(("http://", "https://")):
            self._next_url = resolve_request_url(SAFETYCULTURE_BASE_URL, self._next_url)


class SafetyCultureStructuresPaginator(BasePaginator):
    """Walks Search structures once per structure type.

    Every search is scoped to one type, and the page token sits inside the JSON body at
    `params.page.page_token`. When a type's `next_page_token` runs out, the paginator moves on to
    the next type with a fresh first-page request. An empty page or a repeated token also ends a
    type, so a lingering token can never loop forever.
    """

    def __init__(self, structure_types: tuple[str, ...]) -> None:
        super().__init__()
        self._structure_types = structure_types
        self._type_index = 0
        self._page_token: Optional[str] = None
        self._has_next_page = bool(structure_types)

    def init_request(self, request: Request) -> None:
        self._apply(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        body = response.json()
        token = body.get("next_page_token") if isinstance(body, dict) else None
        if data and token and token != self._page_token:
            self._page_token = token
            return
        self._page_token = None
        self._type_index += 1
        self._has_next_page = self._type_index < len(self._structure_types)

    def update_request(self, request: Request) -> None:
        if self._has_next_page:
            self._apply(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        if not self._has_next_page:
            return None
        return {"structure_type_index": self._type_index, "page_token": self._page_token}

    def set_resume_state(self, state: dict[str, Any]) -> None:
        index = state.get("structure_type_index")
        if isinstance(index, int) and 0 <= index < len(self._structure_types):
            self._type_index = index
            self._page_token = state.get("page_token") or None

    def _apply(self, request: Request) -> None:
        body = dict(request.json or {})
        params = dict(body.get("params") or {})
        page: dict[str, Any] = {"page_size": STRUCTURES_PAGE_SIZE}
        if self._page_token:
            page["page_token"] = self._page_token
        params["page"] = page
        body["params"] = params
        body["structure_type"] = {"system_structure_type": self._structure_types[self._type_index]}
        request.json = body


def safetyculture_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SafetyCultureResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = SAFETYCULTURE_ENDPOINTS[endpoint]

    # Static params ride only on the first request; every later page comes from the verbatim
    # `metadata.next_page`, which already carries them. `modified_after` is added only for an
    # incremental sync that actually has a watermark to filter from.
    params: dict[str, Any] = dict(config.params)
    if config.supports_incremental and should_use_incremental_field and db_incremental_field_last_value:
        params["modified_after"] = _format_modified_after(db_incremental_field_last_value)

    endpoint_config: Endpoint
    if config.structure_types:
        # An empty query lists every structure of the type. Field values carry the org's custom
        # structure fields, the main reason to sync structures over the sites and groups feeds.
        endpoint_config = {
            "path": config.path,
            "method": "POST",
            "json": {"params": {"query": "", "include_fields": True}},
            "paginator": SafetyCultureStructuresPaginator(config.structure_types),
            "data_selector": "results",
        }
    else:
        endpoint_config = {
            "path": config.path,
            "params": params,
            "data_selector": "data",
            # A 200 whose body isn't the documented {"metadata", "data": [...]} envelope is
            # treated as transient (a truncating proxy, a flaky gateway) and retried.
            "data_selector_malformed_retryable": True,
        }

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": SAFETYCULTURE_BASE_URL,
            # Auth (Bearer) goes through the framework auth config so its value is redacted from
            # logs and raised errors; only the non-secret Accept header is set here.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "bearer", "token": api_token},
            "paginator": SafetyCultureFeedPaginator(),
            # `metadata.next_page` is followed verbatim, so pin every request (and the Bearer token)
            # to api.safetyculture.io and refuse redirects — a tampered/off-host next_page or a 3xx
            # can't retarget the credentialed request. `allowed_hosts=[]` means base-host only.
            "allowed_hosts": [],
            "allow_redirects": False,
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": endpoint_config,
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if config.structure_types:
            if resume is not None and resume.structure_type_index is not None:
                initial_paginator_state = {
                    "structure_type_index": resume.structure_type_index,
                    "page_token": resume.page_token,
                }
        elif resume is not None and resume.next_page:
            initial_paginator_state = {"next_url": resume.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist AFTER a page is yielded and only while a next page remains, so a crash re-fetches
        # the next page (merge dedupes) rather than skipping it. A null `next_page` (feed end) or an
        # empty page yields state=None and nothing is saved.
        if not state:
            return
        if state.get("structure_type_index") is not None:
            resumable_source_manager.save_state(
                SafetyCultureResumeConfig(
                    structure_type_index=state["structure_type_index"], page_token=state.get("page_token")
                )
            )
        elif state.get("next_url"):
            resumable_source_manager.save_state(SafetyCultureResumeConfig(next_page=state["next_url"]))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Incremental feeds paginate by advancing `modified_after` in the server-issued `next_page`
        # path, so rows arrive oldest-modified-first — matching the pipeline's ascending watermark.
        sort_mode="asc",
        column_hints=resource.column_hints,
    )


def check_access(
    api_token: str, path: str = DEFAULT_PROBE_PATH, structure_type: Optional[str] = None
) -> tuple[int, Optional[str]]:
    """Probe a single feed to validate the API token.

    With ``structure_type`` set, ``path`` is the Search structures endpoint, which only answers a
    POST scoped to one structure type.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    session = make_tracked_session(
        headers={"Authorization": f"Bearer {api_token}", "Accept": "application/json"},
        redact_values=(api_token,),
    )
    try:
        if structure_type:
            response = session.post(
                f"{SAFETYCULTURE_BASE_URL}{path}",
                json={
                    "structure_type": {"system_structure_type": structure_type},
                    "params": {"page": {"page_size": 1}},
                },
                timeout=15,
            )
        else:
            response = session.get(f"{SAFETYCULTURE_BASE_URL}{path}", timeout=15)
    except Exception as e:
        return 0, f"Could not connect to SafetyCulture: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"SafetyCulture returned HTTP {response.status_code}"

    return 200, None
