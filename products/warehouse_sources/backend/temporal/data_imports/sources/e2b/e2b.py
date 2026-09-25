import re
import functools
import dataclasses
from collections.abc import Callable, Iterable, Iterator
from typing import Any, Optional

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    RESTClient,
    create_auth,
    create_paginator,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.e2b.settings import (
    E2B_ENDPOINTS,
    E2B_PAGE_LIMIT,
    E2BEndpointConfig,
)

# E2B exposes a single global base URL; there are no regional hosts.
E2B_BASE_URL = "https://api.e2b.app"

# The next cursor is returned in this response header and echoed back as a query param.
NEXT_TOKEN_HEADER = "X-Next-Token"
NEXT_TOKEN_PARAM = "nextToken"

# Endpoint name of the batched latest-metrics table, which needs an iterator of its own: it turns a
# page of sandboxes into a single `sandbox_ids=` request rather than one request per sandbox.
SANDBOX_METRICS_LATEST = "sandbox_metrics_latest"

# E2B lets users stash arbitrary key/value data on a sandbox, and its own docs suggest keeping secrets
# (API keys, tokens) there. Writing it to the warehouse table would let anyone with table read access
# read credentials they can't see in the protected source config, so we drop it before ingesting.
SENSITIVE_FIELDS = ("metadata",)

# Shared with the source's 401 and 403 entries in `get_non_retryable_errors` so a rejected key reads
# the same whether it surfaces while the source is being set up or during a later sync.
INVALID_CREDENTIALS_ERROR = (
    "Your E2B API key is invalid or has been revoked. Create a new team-scoped API key in your E2B "
    "dashboard, then reconnect."
)
NO_ACCESS_ERROR = (
    "Your E2B API key does not have access to this data. Check the key's team scope in your E2B "
    "dashboard, then reconnect."
)
# E2B takes the team in the path even when the API key already identifies the team, and exposes no
# endpoint an API key can call to look it up, so the user has to supply it.
TEAM_ID_REQUIRED_ERROR = (
    "Add your E2B team ID to this source to sync team metrics. You can copy it from the URL of your E2B dashboard."
)
TEAM_ID_INVALID_ERROR = (
    "Your E2B team ID contains unsupported characters. It should be the team UUID or the project ID "
    "shown in your E2B dashboard."
)

_TEAM_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")

# Called with the paginator state after each page is yielded, or `None` on the last page.
ResumeHook = Callable[[Optional[dict[str, Any]]], None]


class E2BRetryableError(Exception):
    pass


class E2BConfigurationError(Exception):
    pass


def _scrub(item: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if key not in SENSITIVE_FIELDS}


def _require_team_id(e2b_team_id: str | None) -> str:
    """Return an E2B team ID that is safe to interpolate into a request path."""
    cleaned = (e2b_team_id or "").strip()
    if not cleaned:
        raise E2BConfigurationError(TEAM_ID_REQUIRED_ERROR)
    if not _TEAM_ID_RE.match(cleaned):
        raise E2BConfigurationError(TEAM_ID_INVALID_ERROR)
    return cleaned


@dataclasses.dataclass
class E2BResumeConfig:
    # Opaque cursor to fetch the next page from (E2B's `nextToken`). `None` starts at the first page.
    # A job only ever syncs one endpoint, so a single token slot is unambiguous.
    next_token: str | None = None
    # A fan-out endpoint checkpoints a different shape — which parents finished, and where the
    # in-progress parent stopped — so it gets its own slot rather than overloading `next_token`.
    fanout: dict[str, Any] | None = None


class HeaderCursorPaginator(BasePaginator):
    """E2B returns the next-page cursor in a response header (not the body), and expects it echoed
    back as a query param. No built-in paginator reads a cursor from a header, so this small subclass
    does — resumably. Terminates when the header is absent, or repeats the cursor just sent (a
    defensive guard against an endpoint that echoes the token instead of dropping it)."""

    def __init__(self, header_name: str = NEXT_TOKEN_HEADER, cursor_param: str = NEXT_TOKEN_PARAM) -> None:
        super().__init__()
        self.header_name = header_name
        self.cursor_param = cursor_param
        self._cursor_value: Optional[str] = None

    def init_request(self, request: Request) -> None:
        # Apply a seeded resume cursor to the first request so a resumed run starts mid-list.
        if self._cursor_value is not None:
            if request.params is None:
                request.params = {}
            request.params[self.cursor_param] = self._cursor_value

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        sent = self._cursor_value
        next_token = response.headers.get(self.header_name) or None
        if not next_token or next_token == sent:
            self._has_next_page = False
        else:
            self._cursor_value = next_token
            self._has_next_page = True

    def update_request(self, request: Request) -> None:
        if self._cursor_value is not None:
            if request.params is None:
                request.params = {}
            request.params[self.cursor_param] = self._cursor_value

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"next_token": self._cursor_value} if self._has_next_page and self._cursor_value is not None else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        next_token = state.get("next_token")
        if next_token is not None:
            self._cursor_value = next_token
            self._has_next_page = True


def _client_config(api_key: str) -> ClientConfig:
    # One tracked session reused across every page so urllib3 keeps the connection alive.
    # `redact_values` masks the key from tracked HTTP samples (the `X-API-Key` header isn't on the
    # generic scrubber's denylist); `allow_redirects=False` keeps it from replaying to another host;
    # `capture=False` keeps raw response bodies (which can hold secret-bearing sandbox metadata the
    # name-based scrubbers miss) out of sample storage, since `_scrub` only runs after capture.
    session = make_tracked_session(redact_values=(api_key,), allow_redirects=False, capture=False)

    return {
        "base_url": E2B_BASE_URL,
        "headers": {"Accept": "application/json"},
        # Auth via the framework so the key is injected per-request and redacted from logs.
        "auth": {"type": "api_key", "api_key": api_key, "name": "X-API-Key", "location": "header"},
        "paginator": HeaderCursorPaginator(),
        "session": session,
        # Same-host-only (base_url host is implicitly allowed) + no redirects: an off-host
        # pagination/resume URL or a 3xx can't replay the API key to another origin.
        "allowed_hosts": [],
        "allow_redirects": False,
        "capture": False,
    }


def _make_client(client_config: ClientConfig) -> RESTClient:
    return RESTClient(
        base_url=client_config["base_url"],
        headers=client_config.get("headers"),
        auth=create_auth(client_config.get("auth")),
        paginator=create_paginator(client_config.get("paginator")),
        session=client_config.get("session"),
        allowed_hosts=client_config.get("allowed_hosts"),
        allow_redirects=client_config.get("allow_redirects", True),
        capture=client_config.get("capture", True),
    )


def _fetch_latest_metrics(client: RESTClient, sandbox_ids: list[str]) -> list[dict[str, Any]]:
    """Fetch the latest metric sample for a batch of sandboxes and key each one by its sandbox id.

    The endpoint answers with `{"sandboxes": {"<sandboxID>": {...}}}`, so the id only exists as a
    map key — the rows have to carry it or nothing joins them back to a sandbox.
    """
    rows: list[dict[str, Any]] = []
    for page in client.paginate(
        path=E2B_ENDPOINTS[SANDBOX_METRICS_LATEST].path,
        params={"sandbox_ids": ",".join(sandbox_ids)},
        paginator=SinglePagePaginator(),
        data_selector="sandboxes",
        data_selector_required=True,
    ):
        for by_sandbox in page:
            rows.extend({**metric, "sandboxID": sandbox_id} for sandbox_id, metric in by_sandbox.items())
    return rows


def _iter_latest_metrics(
    client: RESTClient,
    save_checkpoint: ResumeHook,
    initial_paginator_state: Optional[dict[str, Any]],
) -> Iterator[list[dict[str, Any]]]:
    """Walk the sandbox list and turn each page into one batched metrics request.

    `/sandboxes/metrics` accepts up to 100 sandbox ids per call, the same cap as the sandbox list's
    page size, so a page costs one extra request instead of the one-per-sandbox the declarative
    fan-out would issue. The shared helper can't express that batching, hence the custom iterator.
    """
    for sandboxes in client.paginate(
        path=E2B_ENDPOINTS["sandboxes"].path,
        params={"limit": E2B_PAGE_LIMIT},
        data_selector_required=True,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    ):
        sandbox_ids = [sandbox["sandboxID"] for sandbox in sandboxes if sandbox.get("sandboxID")]
        if sandbox_ids:
            yield _fetch_latest_metrics(client, sandbox_ids)


def _top_level_resource(
    config: E2BEndpointConfig,
    client_config: ClientConfig,
    path: str,
    team_id: int,
    job_id: str,
    save_checkpoint: ResumeHook,
    initial_paginator_state: Optional[dict[str, Any]],
) -> Resource:
    endpoint: Endpoint = {
        "path": path,
        # Require the documented shape so a wrapped/error body (a response-shape change) fails loud
        # instead of syncing the object as a row.
        "data_selector_required": True,
    }
    if config.data_selector:
        endpoint["data_selector"] = config.data_selector
    if config.page_size_param is None:
        # No page-size param documented means the endpoint answers in one response; the client's
        # cursor paginator would send a `nextToken` it never issued.
        endpoint["paginator"] = SinglePagePaginator()
    else:
        endpoint["params"] = {config.page_size_param: config.page_size}

    rest_config: RESTAPIConfig = {
        "client": client_config,
        "resources": [
            {
                "name": config.name,
                "endpoint": endpoint,
                # Drop secret-bearing sandbox metadata before ingesting.
                "data_map": _scrub,
            }
        ],
    }
    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def e2b_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[E2BResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
    e2b_team_id: Optional[str] = None,
) -> SourceResponse:
    config = E2B_ENDPOINTS[endpoint]
    client_config = _client_config(api_key)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("next_token") is not None:
            resumable_source_manager.save_state(E2BResumeConfig(next_token=state["next_token"]))

    def save_fanout_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state:
            resumable_source_manager.save_state(E2BResumeConfig(fanout=state))

    cursor_state: Optional[dict[str, Any]] = (
        {"next_token": resume.next_token} if resume is not None and resume.next_token is not None else None
    )

    items: Callable[[], Iterable[Any]]
    column_hints: Optional[dict[str, Any]] = None

    if endpoint == SANDBOX_METRICS_LATEST:
        client = _make_client(client_config)
        # Bound, not called: the iterator is a generator, so a stored one would be exhausted on a
        # second pass.
        items = functools.partial(_iter_latest_metrics, client, save_checkpoint, cursor_state)
    elif config.fanout is not None:
        child_endpoint_extra: Endpoint = {"data_selector_required": True}
        if config.data_selector:
            child_endpoint_extra["data_selector"] = config.data_selector
        if config.page_size_param is None:
            child_endpoint_extra["paginator"] = SinglePagePaginator()
        dependent = build_dependent_resource(
            endpoint_configs=E2B_ENDPOINTS,
            child_endpoint=endpoint,
            fanout=config.fanout,
            client_config=client_config,
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            child_endpoint_extra=child_endpoint_extra,
            page_size_param=config.page_size_param,
            resume_hook=save_fanout_checkpoint,
            initial_paginator_state=resume.fanout if resume is not None else None,
        )
        items = functools.partial(iter, dependent)
    else:
        path = config.path
        if config.requires_team_id:
            path = path.replace("{team_id}", _require_team_id(e2b_team_id))
        resource = _top_level_resource(config, client_config, path, team_id, job_id, save_checkpoint, cursor_state)
        items = functools.partial(iter, resource)
        column_hints = resource.column_hints

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=config.primary_keys,
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=column_hints,
    )


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    # Cheapest authenticated probe: list a single sandbox. 200 means the team-scoped key is genuine.
    # A 401 and a 403 need different next steps — a revoked key has to be replaced, a key scoped to
    # the wrong team does not — so they map to their own messages. Anything else — a timeout,
    # connection error, rate limit, or 5xx — is a transient upstream problem that says nothing about
    # the key, so raise rather than mislabel a valid key "invalid" and send the user down the wrong
    # recovery path.
    # `redact_values` masks the key from tracked HTTP samples (the `X-API-Key` header isn't on the
    # generic scrubber's denylist); `allow_redirects=False` keeps the key from replaying to another host;
    # `capture=False` keeps the raw response body out of sample storage, since a sandbox's user-set
    # metadata can carry secrets the name-based scrubbers can't recognise (see `SENSITIVE_FIELDS`).
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,), allow_redirects=False, capture=False),
        f"{E2B_BASE_URL}/v2/sandboxes?limit=1",
        headers={"X-API-Key": api_key, "Accept": "application/json"},
    )
    if ok:
        return True, None
    if status == 401:
        return False, INVALID_CREDENTIALS_ERROR
    if status == 403:
        return False, NO_ACCESS_ERROR
    raise E2BRetryableError(f"E2B credential probe failed (retryable): status={status}")
