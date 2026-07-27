import dataclasses
from typing import Any, Optional

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.codefresh.settings import (
    CODEFRESH_ENDPOINTS,
    CodefreshEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    OffsetPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe

# Only the US SaaS host is supported. EU / self-hosted installs use a different host, which we don't
# let the user retarget yet (it would mean sending the stored API key to an arbitrary host).
CODEFRESH_BASE_URL = "https://g.codefresh.io/api"


@dataclasses.dataclass
class CodefreshResumeConfig:
    # Offset pagination position (projects, pipelines, images, step_types).
    offset: int | None = None
    # Page pagination position (builds) plus the stable pagination session cursor so resumed pages
    # read against the same snapshot the first page opened.
    page: int | None = None
    session_id: str | None = None


class CodefreshPagePaginator(BasePaginator):
    """Codefresh's builds pagination: a 1-indexed ``page`` param, a ``pagination.nextPage`` flag,
    and a stable ``pagination.sessionId`` snapshot cursor that every page after the first must pin
    via the ``X-Pagination-Session-Id`` header, so builds created mid-sync can't shift the window
    underneath us. No built-in paginator covers the flag + header pair, hence this local subclass."""

    def __init__(self, page: int = 1, session_id: str | None = None) -> None:
        super().__init__()
        self.page = page
        self.session_id = session_id

    def _apply(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["page"] = self.page
        if self.session_id:
            # Pin every page to the snapshot the first page opened.
            request.headers = {**(request.headers or {}), "X-Pagination-Session-Id": self.session_id}

    def init_request(self, request: Request) -> None:
        self._apply(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            body = response.json()
        except Exception:
            body = None
        pagination = body.get("pagination") or {} if isinstance(body, dict) else {}
        self.session_id = pagination.get("sessionId") or self.session_id

        # An empty page terminates the stream even if the API keeps advertising nextPage. Without
        # this, a server-side cursor bug that streams empty pages forever would loop indefinitely.
        if not data or not pagination.get("nextPage"):
            self._has_next_page = False
            return

        self.page += 1
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        self._apply(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        # self.page already points at the next page to fetch (update_state incremented it).
        return {"page": self.page, "session_id": self.session_id} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        page = state.get("page")
        if page is not None:
            self.page = int(page)
            self._has_next_page = True
        session_id = state.get("session_id")
        if session_id:
            self.session_id = session_id

    def __str__(self) -> str:
        return f"CodefreshPagePaginator(page={self.page})"


def _flatten(item: dict[str, Any], flatten_key: Optional[str]) -> dict[str, Any]:
    """Lift the fields of a nested object (e.g. a pipeline's ``metadata``) to the row top level so
    the primary key / partition columns resolve against real top-level fields. Top-level fields win
    on a name clash."""
    if flatten_key and isinstance(item.get(flatten_key), dict):
        item = dict(item)
        nested = item.pop(flatten_key)
        return {**nested, **item}
    return item


def _redact_key(row: dict[str, Any], dotted_key: str) -> dict[str, Any]:
    """Return ``row`` with a possibly-nested field removed. ``"variables"`` drops a top-level field;
    ``"spec.variables"`` walks into ``spec`` and drops its ``variables``. Only the nodes on the path
    are copied, so the upstream item is left unmodified; a missing or non-dict node is a no-op."""
    head, _, rest = dotted_key.partition(".")
    if head not in row:
        return row
    if not rest:
        return {k: v for k, v in row.items() if k != head}
    nested = row[head]
    if not isinstance(nested, dict):
        return row
    return {**row, head: _redact_key(nested, rest)}


def _transform_row(item: dict[str, Any], config: CodefreshEndpointConfig) -> dict[str, Any]:
    """Flatten the row, then drop any redacted fields. Redaction runs after flattening so a key that
    only surfaces once a nested object is lifted (and a top-level key of the same name) are both
    caught. Redact keys may be dotted paths (e.g. ``spec.variables``) to reach nested fields."""
    row = _flatten(item, config.flatten_key)
    for key in config.redact_keys:
        row = _redact_key(row, key)
    return row


def _build_paginator_and_params(config: CodefreshEndpointConfig) -> tuple[BasePaginator, dict[str, Any]]:
    if config.pagination == "offset":
        # No usable body total; termination is short/empty page. The paginator injects limit+offset.
        return OffsetPaginator(limit=config.page_size, total_path=None), {}
    if config.pagination == "page":
        return CodefreshPagePaginator(), {"limit": config.page_size}
    # "none": single request, no pagination params (triggers).
    return SinglePagePaginator(), {}


def codefresh_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CodefreshResumeConfig],
) -> SourceResponse:
    config = CODEFRESH_ENDPOINTS[endpoint]
    paginator, params = _build_paginator_and_params(config)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": CODEFRESH_BASE_URL,
            # Auth is supplied via the framework auth config so its value is redacted from logs.
            # Codefresh expects the raw token as the Authorization header value — no "Bearer " prefix.
            "auth": {"type": "api_key", "api_key": api_key, "name": "Authorization", "location": "header"},
            "headers": {"Accept": "application/json"},
            "paginator": paginator,
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    # Codefresh returns either a bare array or an envelope ({docs: [...]},
                    # {workflows: {docs: [...]}}); data_key is the path to walk.
                    "data_selector": ".".join(config.data_key) if config.data_key else None,
                    # For bare-array endpoints a 200 body that isn't a list means the response shape
                    # changed — fail loud instead of syncing a stray object as a row.
                    "data_selector_required": config.data_key is None,
                },
                "data_map": lambda item, config=config: _transform_row(item, config),
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            if config.pagination == "offset" and resume.offset is not None:
                initial_paginator_state = {"offset": resume.offset}
            elif config.pagination == "page" and (resume.page is not None or resume.session_id is not None):
                initial_paginator_state = {"page": resume.page, "session_id": resume.session_id}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; the hook fires AFTER a page is yielded so a crash
        # re-pulls the page we just emitted rather than skipping it — merge dedupes the re-pulled
        # rows on the primary key. A short/last page passes None: nothing left to resume to.
        if not state:
            return
        if config.pagination == "offset" and state.get("offset") is not None:
            resumable_source_manager.save_state(CodefreshResumeConfig(offset=int(state["offset"])))
        elif config.pagination == "page" and state.get("page") is not None:
            resumable_source_manager.save_state(
                CodefreshResumeConfig(page=int(state["page"]), session_id=state.get("session_id"))
            )

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
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
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str, schema_name: Optional[str] = None) -> tuple[bool, str | None]:
    """Probe the token. Codefresh keys are scoped per resource, so at source-create (``schema_name``
    is ``None``) a 403 means the token is genuine but lacks scope for the probed resource — accept it
    and let the user pick the tables their key can reach. A 401 always means a bad token."""
    config = CODEFRESH_ENDPOINTS.get(schema_name) if schema_name else None
    path = config.path if config is not None else "/projects"

    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{CODEFRESH_BASE_URL}{path}?limit=1",
        headers={"Authorization": api_key, "Accept": "application/json"},
    )
    if ok:
        return True, None
    if status is None:
        return False, "Could not connect to Codefresh. Please try again."
    if status == 401:
        return False, "Your Codefresh API key is invalid or has been revoked."
    if status == 403:
        if schema_name:
            return False, f"Your Codefresh API key is missing the access scope required to sync '{schema_name}'."
        # Valid token, but it lacks scope for the probe resource — don't block source creation.
        return True, None
    if status == 429 or status >= 500:
        # Transient: a rate-limit or server error doesn't mean the key is bad. Surface it as a
        # retryable failure rather than telling the user their credentials are invalid.
        return False, "Codefresh is temporarily unavailable. Please try again in a moment."
    return False, f"Codefresh API returned an unexpected status ({status})."
