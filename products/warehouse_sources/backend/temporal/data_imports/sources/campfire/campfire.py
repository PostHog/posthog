import dataclasses
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, Optional, cast
from urllib.parse import urlencode, urlparse

from requests import PreparedRequest, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.campfire.settings import (
    CAMPFIRE_BASE_URL,
    CAMPFIRE_ENDPOINTS,
    LAST_MODIFIED_AT,
    LAST_MODIFIED_AT_PARAM,
    CampfireEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import AuthConfigBase
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponsePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    IncrementalConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse


@dataclasses.dataclass
class CampfireResumeConfig:
    # Top-level endpoints resume from the `next` link of the last fully-yielded page. Absolute
    # URL on api.meetcampfire.com, carrying the pagination cursor/offset plus any incremental
    # filter for this job.
    next_url: str | None = None
    # Fan-out endpoints resume by parent: the contract paths already fully synced, the contract
    # in progress, and that contract's paginator state — see
    # `common.rest_source.__init__._make_paginate_dependent_resource`.
    completed: list[str] | None = None
    current: str | None = None
    child_state: dict[str, Any] | None = None


class CampfireTokenAuth(AuthConfigBase):
    """Campfire authenticates with a `Authorization: Token <key>` header.

    Supplied through the framework auth config (rather than a hand-built header) so the key
    is scrubbed from every raised error message and logged/sampled request.
    """

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        request.headers["Authorization"] = f"Token {self.api_key}"
        return request

    def secret_values(self) -> tuple[str, ...]:
        return (self.api_key,) if self.api_key else ()


def _validate_next_url(next_url: str) -> None:
    """Only follow `next` links that stay on the Campfire API host over HTTPS.

    The API key rides in a header on every request, so following an off-host or downgraded
    link would hand the credential to whatever host the response named.
    """
    parsed = urlparse(next_url)
    expected = urlparse(CAMPFIRE_BASE_URL)
    if parsed.scheme != "https" or parsed.netloc != expected.netloc:
        raise ValueError(f"Campfire returned a next link on an unexpected host: {parsed.netloc!r}")


class CampfireNextUrlPaginator(JSONResponsePaginator):
    """Follows the DRF `next` link in the response body, host/scheme-pinned to the Campfire API.

    Both freshly returned `next` links and seeded resume URLs are validated before the client
    is allowed to send a request to them.
    """

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if self._has_next_page and self._next_url is not None:
            _validate_next_url(self._next_url)

    def set_resume_state(self, state: dict[str, Any]) -> None:
        next_url = state.get("next_url")
        if next_url is not None:
            _validate_next_url(next_url)
        super().set_resume_state(state)


def _format_incremental_value(value: Any) -> str:
    """Format the watermark for `last_modified_at__gte`, which accepts ISO 8601."""
    if isinstance(value, datetime):
        utc_value = value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return utc_value.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _client_config(api_key: str) -> ClientConfig:
    # capture=False keeps accounting responses (amounts, invoice/transaction IDs, free-form
    # business fields the name-based scrubbers can't recognise) out of HTTP sample storage.
    session = make_tracked_session(redact_values=(api_key,), capture=False)
    return {
        "base_url": CAMPFIRE_BASE_URL,
        # Auth (the Token header) is supplied via the framework auth config so its value is
        # redacted from logs; only the non-secret Accept header is set here.
        "headers": {"Accept": "application/json"},
        "auth": CampfireTokenAuth(api_key),
        "session": session,
        "paginator": CampfireNextUrlPaginator(),
    }


def _incremental_config(field_name: str) -> IncrementalConfig | None:
    """Bind a fan-out child's cursor to Campfire's server-side `last_modified_at` filter.

    None for any other field, which leaves the child merging on its primary key with no
    request window rather than sending a filter the endpoint does not have.
    """
    if field_name != LAST_MODIFIED_AT:
        return None
    return {
        "cursor_path": LAST_MODIFIED_AT,
        "start_param": LAST_MODIFIED_AT_PARAM,
        # The framework sends the param on every request, so a first sync needs a floor that
        # selects everything.
        "initial_value": "1970-01-01T00:00:00Z",
        "convert": _format_incremental_value,
    }


def _top_level_resource(
    config: CampfireEndpointConfig,
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CampfireResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> Iterable[Any]:
    params: dict[str, Any] = {**config.extra_params}
    if config.paginated:
        params["limit"] = config.page_size
    if config.use_cursor:
        # An empty `cursor=` opts the endpoint into cursor pagination; every later page
        # comes from the response's `next` link.
        params["cursor"] = ""
    if should_use_incremental_field and config.incremental_fields and db_incremental_field_last_value is not None:
        params[LAST_MODIFIED_AT_PARAM] = _format_incremental_value(db_incremental_field_last_value)

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    # A DRF envelope missing `results` (or a bare list where one is expected)
                    # yields nothing, matching the old lenient parse rather than failing.
                    "data_selector": config.data_selector,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_url:
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only while a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(CampfireResumeConfig(next_url=state["next_url"]))

    # Incremental filtering is applied above as a first-page query param; the framework's own
    # incremental injection is not used, so pass no last value here.
    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def _fanout_resource(
    config: CampfireEndpointConfig,
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CampfireResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
    incremental_field: str | None,
) -> Iterable[Any]:
    assert config.fanout is not None
    parent_config = CAMPFIRE_ENDPOINTS[config.fanout.parent_name]

    initial_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and (resume.completed or resume.current):
            initial_state = {
                "completed": resume.completed or [],
                "current": resume.current,
                "child_state": resume.child_state,
            }

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state is not None:
            resumable_source_manager.save_state(
                CampfireResumeConfig(
                    completed=state.get("completed"),
                    current=state.get("current"),
                    child_state=state.get("child_state"),
                )
            )

    return cast(
        Iterable[Any],
        build_dependent_resource(
            endpoint_configs=CAMPFIRE_ENDPOINTS,
            child_endpoint=endpoint,
            fanout=config.fanout,
            client_config=_client_config(api_key),
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=db_incremental_field_last_value,
            should_use_incremental_field=should_use_incremental_field,
            incremental_field=incremental_field,
            incremental_config_factory=_incremental_config,
            parent_endpoint_extra={"data_selector": parent_config.data_selector},
            child_endpoint_extra={"data_selector": config.data_selector},
            # The child endpoint documents no page-size param, so the parent listing asks for
            # its own through `fanout.parent_params`.
            page_size_param=None,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_state,
        ),
    )


def campfire_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CampfireResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = CAMPFIRE_ENDPOINTS[endpoint]

    if config.fanout is not None:
        resource = _fanout_resource(
            config,
            api_key,
            endpoint,
            team_id,
            job_id,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
            incremental_field,
        )
    else:
        resource = _top_level_resource(
            config,
            api_key,
            endpoint,
            team_id,
            job_id,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        # "desc" endpoints persist the incremental watermark only at successful job end —
        # their response order is undocumented, so per-batch persistence could advance the
        # watermark past rows a crashed run still owes.
        sort_mode=config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(api_key: str, path: str | None = None) -> bool:
    """Probe the key with the cheapest call on the given endpoint (chart of accounts when
    unset — every Campfire role, including view-only, can GET it)."""
    probe_path = path or CAMPFIRE_ENDPOINTS["chart_of_accounts"].path

    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,), capture=False),
        f"{CAMPFIRE_BASE_URL}{probe_path}?{urlencode({'limit': 1})}",
        headers={"Authorization": f"Token {api_key}", "Accept": "application/json"},
    )
    return ok
