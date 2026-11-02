import dataclasses
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime
from typing import Any, Optional, cast

from requests import PreparedRequest

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
    JSONResponseCursorPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SortMode, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.fleetio.settings import (
    FLEETIO_ENDPOINTS,
    PER_PAGE,
    FleetioEndpointConfig,
)

FLEETIO_API_HOST = "https://secure.fleetio.com"

# A Fleetio API key is locked to whatever date version was current when it was created, but the
# `X-Api-Version` header overrides that lock per request. We pin a modern date version explicitly so
# every index endpoint serves the same cursor-pagination + `filter`/`sort` contract regardless of the
# key's locked version. Two labels are supported:
#   "v1"         -> the 2024-06-30 date version, which carries each resource's API generation in the
#                   path (`/api/v1/vehicles`, `/api/v2/service_entries/{id}/service_entry_line_items`).
#   "2025-05-05" -> the same pagination/filter contract, but Fleetio dropped the generation segment
#                   from this version onward (resources move to `/api/{resource}`).
# See https://developer.fleetio.com/docs/overview/versioning.
FLEETIO_LEGACY_VERSION = "v1"
FLEETIO_VERSION_2025_05_05 = "2025-05-05"

# Oldest -> newest. `FleetioSource` declares these as its supported versions and defaults to the last.
SUPPORTED_VERSIONS = (FLEETIO_LEGACY_VERSION, FLEETIO_VERSION_2025_05_05)
DEFAULT_VERSION = SUPPORTED_VERSIONS[-1]

# Kept for the legacy "v1" wire contract's `X-Api-Version` value (the label and header diverge only
# for that label). Referenced by tests as the header the "v1" pin sends.
FLEETIO_API_VERSION = "2024-06-30"

# Shared by every supported version; the per-resource generation segment, where a version still uses
# one, is part of the resource path rather than the base.
FLEETIO_BASE_URL = f"{FLEETIO_API_HOST}/api"


@dataclasses.dataclass(frozen=True)
class _VersionContract:
    version_header: str
    uses_path_version_segment: bool


# Maps every supported label to the wire contract it selects. Coverage is exhaustive by construction
# (`_resolve_contract` raises on an unmapped pin) — never fall through to a default, which would send
# no version header and silently track "latest", the drift versioning exists to prevent.
_VERSION_CONTRACTS: dict[str, _VersionContract] = {
    FLEETIO_LEGACY_VERSION: _VersionContract(version_header=FLEETIO_API_VERSION, uses_path_version_segment=True),
    FLEETIO_VERSION_2025_05_05: _VersionContract(
        version_header=FLEETIO_VERSION_2025_05_05, uses_path_version_segment=False
    ),
}

DEFAULT_INCREMENTAL_FIELD = "updated_at"


def _resolve_contract(api_version: str) -> _VersionContract:
    try:
        return _VERSION_CONTRACTS[api_version]
    except KeyError:
        raise ValueError(f"Unsupported Fleetio API version pin: {api_version!r}")


def _resource_path(contract: _VersionContract, config: FleetioEndpointConfig) -> str:
    if contract.uses_path_version_segment:
        return f"/{config.path_version}{config.path}"
    return config.path


class FleetioAuth(AuthConfigBase):
    """Fleetio authenticates with two separate headers, not one.

    `Authorization: Token <api_key>` carries the API key and `Account-Token: <account_token>` selects
    the account. The generic auth types each carry a single credential header, so both are set here and
    both reported as secret so the tracked session masks them wherever they surface in logs or captured
    samples — the `Account-Token` header name is connector-specific and not one the generic auth
    scrubbers recognise.
    """

    def __init__(self, api_key: str, account_token: str) -> None:
        self.api_key = api_key
        self.account_token = account_token

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        request.headers["Authorization"] = f"Token {self.api_key}"
        request.headers["Account-Token"] = self.account_token
        return request

    def secret_values(self) -> tuple[str, ...]:
        return tuple(value for value in (self.api_key, self.account_token) if value)


def _non_secret_headers(version_header: str) -> dict[str, str]:
    # Only the non-secret version/accept headers live here; the credentials go through FleetioAuth so
    # their values are registered for redaction. Pinning the version is what guarantees the
    # cursor-pagination + filter/sort contract.
    return {"X-Api-Version": version_header, "Accept": "application/json"}


def _format_incremental_value(value: Any) -> str:
    """Format an incremental cursor value for Fleetio's `filter[...][gt]` parameter.

    Fleetio parses standard ISO 8601 timestamps (Rails `Time.zone.parse`), so isoformat with an
    explicit UTC offset is accepted. Naive datetimes are treated as UTC.
    """
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).isoformat()
    return str(value)


def _build_base_params(
    config: FleetioEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    """Build the query params reused on every page (the cursor is added per request by the paginator).

    Sort ascending on the field we checkpoint against so `SourceResponse.sort_mode="asc"` holds and
    the watermark advances correctly: the chosen incremental field when syncing incrementally, else a
    stable field (`created_at`) to keep full-refresh pagination from skipping/duplicating rows as data
    is inserted mid-sync.
    """
    params: dict[str, Any] = {"per_page": PER_PAGE}

    sort_field = (incremental_field if should_use_incremental_field else None) or config.partition_key or "created_at"
    params[f"sort[{sort_field}]"] = "asc"

    if should_use_incremental_field and db_incremental_field_last_value is not None:
        # `filter[<field>][gt]` is the documented server-side timestamp filter for API versions
        # 2024-01-01+ (the `gt` operator mirrors the legacy `q[<field>_gt]` ransack predicate). The
        # cursor envelope carries the active filter forward, so it stays applied on every page rather
        # than only the first — no unbounded history re-walk on incremental syncs.
        filter_field = incremental_field or DEFAULT_INCREMENTAL_FIELD
        params[f"filter[{filter_field}][gt]"] = _format_incremental_value(db_incremental_field_last_value)

    return params


def _client_config(api_key: str, account_token: str, contract: _VersionContract) -> ClientConfig:
    return {
        "base_url": FLEETIO_BASE_URL,
        "headers": _non_secret_headers(contract.version_header),
        "auth": FleetioAuth(api_key, account_token),
        # Every index endpoint returns the cursor envelope ({"records": [...], "next_cursor": ...});
        # the cursor is carried forward as the `start_cursor` query param.
        "paginator": JSONResponseCursorPaginator(cursor_path="next_cursor", cursor_param="start_cursor"),
        # Pin every request — including the paginator's next-page cursor requests — to the Fleetio
        # host and refuse redirects, so a tampered/spoofed response can't exfiltrate the two
        # credential headers to another origin.
        "allowed_hosts": [],
        "allow_redirects": False,
    }


@dataclasses.dataclass(frozen=True)
class FleetioResumeConfig:
    # The cursor to start the next page from, for a top-level endpoint. None means "start at the
    # first page".
    start_cursor: str | None = None
    # Fan-out endpoints resume by parent: the parent paths already fully synced, the parent in
    # progress, and that parent's paginator state — see
    # `common.rest_source.__init__._make_paginate_dependent_resource`.
    completed: list[str] | None = None
    current: str | None = None
    child_state: dict[str, Any] | None = None


def validate_credentials(api_key: str, account_token: str, api_version: str) -> bool:
    # Probe a cheap index endpoint under the resolved version so the probe exercises the same base
    # path/version the source will sync with. Fleetio API keys are account-scoped (no per-endpoint
    # scopes), so one 200 confirms both headers are genuine. Both credentials are redacted from logged
    # URLs and captured samples — `Account-Token` is a connector-specific header name the generic auth
    # scrubbers don't recognise, so value-based redaction is required to keep it out of HTTP telemetry.
    contract = _resolve_contract(api_version)
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key, account_token)),
        f"{FLEETIO_BASE_URL}{_resource_path(contract, FLEETIO_ENDPOINTS['vehicles'])}?per_page=1",
        headers=_non_secret_headers(contract.version_header),
        auth=FleetioAuth(api_key, account_token),
    )
    return ok


def _make_source_response(
    config: FleetioEndpointConfig,
    items: Callable[[], Iterable[Any]],
    sort_mode: SortMode | None,
    column_hints: dict[str, Any] | None = None,
) -> SourceResponse:
    return SourceResponse(
        name=config.name,
        items=items,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode=sort_mode,
        column_hints=column_hints,
    )


def _top_level_source(
    config: FleetioEndpointConfig,
    contract: _VersionContract,
    api_key: str,
    account_token: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[FleetioResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
    incremental_field: str | None,
) -> SourceResponse:
    params = _build_base_params(
        config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key, account_token, contract),
        "resources": [
            {
                "name": config.name,
                "endpoint": {
                    "path": _resource_path(contract, config),
                    "params": params,
                    "data_selector": "records",
                    # A 200 body without `records` (e.g. a bare list because the version pin was
                    # ignored and a legacy page-based response came back) means the response shape
                    # changed — fail loud instead of silently syncing 0 rows or one page.
                    "data_selector_required": True,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.start_cursor:
            initial_paginator_state = {"cursor": resume.start_cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields the
        # last page (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(FleetioResumeConfig(start_cursor=state["cursor"]))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return _make_source_response(config, lambda: resource, sort_mode="asc", column_hints=resource.column_hints)


def _fanout_source(
    config: FleetioEndpointConfig,
    contract: _VersionContract,
    api_key: str,
    account_token: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[FleetioResumeConfig],
) -> SourceResponse:
    assert config.fanout is not None
    parent_config = FLEETIO_ENDPOINTS[config.fanout.parent_name]

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
                FleetioResumeConfig(
                    completed=state.get("completed"),
                    current=state.get("current"),
                    child_state=state.get("child_state"),
                )
            )

    dependent_resource = cast(
        Iterable[Any],
        build_dependent_resource(
            endpoint_configs=FLEETIO_ENDPOINTS,
            child_endpoint=config.name,
            fanout=config.fanout,
            client_config=_client_config(api_key, account_token, contract),
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            # The parent and child sit on different API generations, so each resource's path has to
            # carry its own version segment rather than share one from the client base URL.
            parent_endpoint_extra={
                "path": _resource_path(contract, parent_config),
                "data_selector": "records",
                "data_selector_required": True,
            },
            child_endpoint_extra={
                "path": _resource_path(contract, config),
                "data_selector": "records",
                "data_selector_required": True,
            },
            page_size_param="per_page",
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_state,
        ),
    )

    # Rows arrive grouped by parent service entry, so the partition key is not globally ascending.
    return _make_source_response(config, lambda: dependent_resource, sort_mode=None)


def fleetio_source(
    api_key: str,
    account_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[FleetioResumeConfig],
    api_version: str = DEFAULT_VERSION,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = FLEETIO_ENDPOINTS[endpoint]
    contract = _resolve_contract(api_version)

    if config.fanout is not None:
        return _fanout_source(
            config,
            contract,
            api_key,
            account_token,
            team_id,
            job_id,
            resumable_source_manager,
        )

    return _top_level_source(
        config,
        contract,
        api_key,
        account_token,
        team_id,
        job_id,
        resumable_source_manager,
        should_use_incremental_field,
        db_incremental_field_last_value,
        incremental_field,
    )
