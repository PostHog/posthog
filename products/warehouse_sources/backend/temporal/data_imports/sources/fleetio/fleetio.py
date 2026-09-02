import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from requests import PreparedRequest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import AuthConfigBase
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.fleetio.settings import (
    FLEETIO_ENDPOINTS,
    FleetioEndpointConfig,
)

FLEETIO_API_HOST = "https://secure.fleetio.com"

# A Fleetio API key is locked to whatever date version was current when it was created, but the
# `X-Api-Version` header overrides that lock per request. We pin a modern date version explicitly so
# every index endpoint serves the same cursor-pagination + `filter`/`sort` contract regardless of the
# key's locked version. Two labels are supported:
#   "v1"         -> the 2024-06-30 date version, served under the integer `/api/v1` path.
#   "2025-05-05" -> the same pagination/filter contract, but Fleetio drops the integer path segment
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


@dataclasses.dataclass(frozen=True)
class _VersionContract:
    base_url: str
    version_header: str


# Maps every supported label to the wire contract it selects. Coverage is exhaustive by construction
# (`_resolve_contract` raises on an unmapped pin) — never fall through to a default, which would send
# no version header and silently track "latest", the drift versioning exists to prevent.
_VERSION_CONTRACTS: dict[str, _VersionContract] = {
    FLEETIO_LEGACY_VERSION: _VersionContract(base_url=f"{FLEETIO_API_HOST}/api/v1", version_header=FLEETIO_API_VERSION),
    FLEETIO_VERSION_2025_05_05: _VersionContract(
        base_url=f"{FLEETIO_API_HOST}/api", version_header=FLEETIO_VERSION_2025_05_05
    ),
}

# Base URL of the legacy contract; retained as a module constant for readability at call sites.
FLEETIO_BASE_URL = _VERSION_CONTRACTS[FLEETIO_LEGACY_VERSION].base_url
PER_PAGE = 100
DEFAULT_INCREMENTAL_FIELD = "updated_at"


def _resolve_contract(api_version: str) -> _VersionContract:
    try:
        return _VERSION_CONTRACTS[api_version]
    except KeyError:
        raise ValueError(f"Unsupported Fleetio API version pin: {api_version!r}")


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


@dataclasses.dataclass
class FleetioResumeConfig:
    # The cursor to start the next page from. None means "start at the first page".
    start_cursor: str | None = None


def validate_credentials(api_key: str, account_token: str, api_version: str) -> bool:
    # Probe a cheap index endpoint under the resolved version so the probe exercises the same base
    # path/version the source will sync with. Fleetio API keys are account-scoped (no per-endpoint
    # scopes), so one 200 confirms both headers are genuine. Both credentials are redacted from logged
    # URLs and captured samples — `Account-Token` is a connector-specific header name the generic auth
    # scrubbers don't recognise, so value-based redaction is required to keep it out of HTTP telemetry.
    contract = _resolve_contract(api_version)
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key, account_token)),
        f"{contract.base_url}/vehicles?per_page=1",
        headers=_non_secret_headers(contract.version_header),
        auth=FleetioAuth(api_key, account_token),
    )
    return ok


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

    params = _build_base_params(
        config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": contract.base_url,
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
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
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

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
        column_hints=resource.column_hints,
    )
