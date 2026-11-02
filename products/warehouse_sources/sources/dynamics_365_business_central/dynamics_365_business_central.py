import re
import dataclasses
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    OAuth2Auth,
    OAuth2AuthRequestError,
    strip_oauth2_permanent_marker,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponsePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.dynamics_365_business_central.settings import (
    BUSINESS_CENTRAL_ENDPOINTS,
    COMPANIES_ENDPOINT,
    BusinessCentralEndpoint,
)

BUSINESS_CENTRAL_HOST = "api.businesscentral.dynamics.com"
BUSINESS_CENTRAL_BASE = f"https://{BUSINESS_CENTRAL_HOST}"
# Entra ID (Azure AD) token endpoint. The tenant is a path segment; the host is fixed.
ENTRA_TOKEN_URL_TEMPLATE = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
# Client-credentials flow asks for the app's admin-consented Business Central permissions.
BUSINESS_CENTRAL_SCOPE = f"{BUSINESS_CENTRAL_BASE}/.default"

# `@odata.nextLink` is an absolute, self-contained URL, so the next-URL paginator follows it
# directly. Quoted because the key contains a literal `.` that jsonpath would otherwise split.
NEXT_LINK_PATH = "'@odata.nextLink'"
# OData v4 list responses wrap rows in a `value` array.
DATA_SELECTOR = "value"

REQUEST_TIMEOUT_SECONDS = (10.0, 300.0)
VALIDATE_TIMEOUT_SECONDS = 15.0
# Business Central pages can carry thousands of wide rows; keep the source->Arrow conversion
# smaller than the pipeline default so a page of documents doesn't spike worker memory.
CHUNK_SIZE = 2000
CHUNK_SIZE_BYTES = 100 * 1024 * 1024

# The tenant, environment and API version are customer-supplied and land in the request path.
# The host is fixed, so pinning these to safe characters is what stops a value like `../../`
# retargeting the credentialed request to another path on the API.
_TENANT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_ENVIRONMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,29}$")
_API_VERSION_RE = re.compile(r"^v[0-9]+(\.[0-9]+)?$")
# The cursor field is interpolated into an OData `$filter` expression, so only a bare property
# name is accepted — anything else falls back to the endpoint's advertised field.
_FIELD_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class BusinessCentralConfigurationError(Exception):
    """A tenant id, environment name or API version that can't be put in a request path."""


@dataclasses.dataclass(frozen=True)
class Dynamics365BusinessCentralResumeConfig:
    # Framework resume snapshot for the current endpoint: `{"next_url": ...}` for the top-level
    # `companies` walk, or the per-company fan-out shape
    # `{"completed": [...], "current": ..., "child_state": {...}}` for everything else.
    paginator_state: Optional[dict[str, Any]] = None


def build_base_url(tenant_id: str, environment: str, api_version: str) -> str:
    """Build the per-tenant, per-environment API root.

    Business Central has no shared host path: every request goes to
    `/v2.0/{tenant}/{environment}/api/{version}`.
    """
    if not _TENANT_ID_RE.match(tenant_id):
        raise BusinessCentralConfigurationError(
            "Business Central tenant ID must be the Microsoft Entra tenant GUID or domain, with no slashes or spaces."
        )
    if not _ENVIRONMENT_RE.match(environment):
        raise BusinessCentralConfigurationError(
            "Business Central environment name must be letters, numbers and hyphens only (for example `production`)."
        )
    if not _API_VERSION_RE.match(api_version):
        raise BusinessCentralConfigurationError(f"Unsupported Business Central API version: {api_version}")

    return f"{BUSINESS_CENTRAL_BASE}/v2.0/{tenant_id}/{environment}/api/{api_version}"


def build_auth(tenant_id: str, client_id: str, client_secret: str) -> OAuth2Auth:
    """Entra ID service-to-service auth: the framework mints a ~1h token and re-mints on expiry."""
    if not _TENANT_ID_RE.match(tenant_id):
        raise BusinessCentralConfigurationError(
            "Business Central tenant ID must be the Microsoft Entra tenant GUID or domain, with no slashes or spaces."
        )

    return OAuth2Auth(
        token_url=ENTRA_TOKEN_URL_TEMPLATE.format(tenant_id=tenant_id),
        client_id=client_id,
        client_secret=client_secret,
        grant_type="client_credentials",
        scopes=BUSINESS_CENTRAL_SCOPE,
    )


def _format_odata_datetime(value: Any) -> Optional[str]:
    """Render an incremental watermark as an OData v4 Edm.DateTimeOffset literal."""
    if isinstance(value, datetime):
        moment = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    elif isinstance(value, date):
        moment = datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        moment = parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    else:
        return None
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def build_incremental_params(
    endpoint: BusinessCentralEndpoint,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: Optional[str] = None,
) -> dict[str, str]:
    """Build the server-side `$filter` window for an incremental sync.

    Honors the cursor field the user picked in the schema settings, falling back to the
    endpoint's advertised one. Returns `{}` for a full refresh or a first sync — the OData
    filter rides on `@odata.nextLink`, so once set it bounds every page, not just the first.
    """
    if endpoint.cursor_field is None or not should_use_incremental_field:
        return {}

    field = (
        incremental_field if incremental_field and _FIELD_NAME_RE.match(incremental_field) else endpoint.cursor_field
    )
    watermark = _format_odata_datetime(db_incremental_field_last_value)
    if watermark is None:
        return {}

    return {"$filter": f"{field} gt {watermark}"}


def _strip_odata_annotations(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if not key.startswith("@")}


def _row_transform(company_scoped: bool) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Drop OData control annotations (`@odata.etag`) and, for fan-out children, rename the
    injected parent fields to the `company_id` / `company_name` columns the primary key uses."""

    def _transform(row: dict[str, Any]) -> dict[str, Any]:
        out = _strip_odata_annotations(row)
        if company_scoped:
            out["company_id"] = out.pop("_companies_id", None)
            out["company_name"] = out.pop("_companies_name", None)
        return out

    return _transform


def _companies_resource(as_parent: bool) -> EndpointResource:
    endpoint: Endpoint = {
        "path": COMPANIES_ENDPOINT,
        "data_selector": DATA_SELECTOR,
        "paginator": JSONResponsePaginator(next_url_path=NEXT_LINK_PATH),
    }
    resource: EndpointResource = {"name": COMPANIES_ENDPOINT, "endpoint": endpoint}
    if not as_parent:
        # Only map when companies is the synced table: as a fan-out parent its rows are read only
        # for the `id`/`name` bindings, so reshaping them would be wasted work.
        resource["data_map"] = _row_transform(company_scoped=False)
    return resource


def _company_scoped_resource(endpoint_config: BusinessCentralEndpoint, params: dict[str, str]) -> EndpointResource:
    endpoint: Endpoint = {
        "path": f"companies({{company_id}})/{endpoint_config.name}",
        "params": {
            "company_id": {"type": "resolve", "resource": COMPANIES_ENDPOINT, "field": "id"},
            **params,
        },
        "data_selector": DATA_SELECTOR,
        "paginator": JSONResponsePaginator(next_url_path=NEXT_LINK_PATH),
        # A company that doesn't have the extension backing this entity answers 404; skip it
        # rather than failing the whole sync for the tenant's other companies.
        "response_actions": [{"status_code": 404, "action": "ignore"}],
    }
    return {
        "name": endpoint_config.name,
        "endpoint": endpoint,
        "include_from_parent": ["id", "name"],
        "data_map": _row_transform(company_scoped=True),
    }


def _build_resources(endpoint_config: BusinessCentralEndpoint, params: dict[str, str]) -> list[EndpointResource | str]:
    if not endpoint_config.company_scoped:
        return [_companies_resource(as_parent=False)]
    return [_companies_resource(as_parent=True), _company_scoped_resource(endpoint_config, params)]


def dynamics_365_business_central_source(
    tenant_id: str,
    environment: str,
    client_id: str,
    client_secret: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[Dynamics365BusinessCentralResumeConfig],
    api_version: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: Optional[str] = None,
) -> SourceResponse:
    endpoint_config = BUSINESS_CENTRAL_ENDPOINTS[endpoint]
    base_url = build_base_url(tenant_id, environment, api_version)

    params = build_incremental_params(
        endpoint_config,
        should_use_incremental_field,
        db_incremental_field_last_value,
        incremental_field,
    )

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": base_url,
            "headers": {"Accept": "application/json"},
            "auth": build_auth(tenant_id, client_id, client_secret),
            # The client secret only ever leaves the process in the Entra token exchange (which
            # builds its own session), but redact it here too so it can never surface in a logged
            # URL from the data requests. `capture=False`: these rows are ledger entries, payments,
            # bank-account and tax fields the name-based scrubbers can't recognise, so the bodies
            # stay out of the HTTP sample store (requests are still metered and logged) rather than
            # becoming readable outside the warehouse table access path.
            "session": make_tracked_session(redact_values=(client_secret,), capture=False),
            "paginator": JSONResponsePaginator(next_url_path=NEXT_LINK_PATH),
            # `@odata.nextLink` comes back from the API, so pin it (and any resumed URL) to the
            # Business Central host and reject redirects — the bearer token must not follow a
            # tampered link off-origin.
            "allowed_hosts": [BUSINESS_CENTRAL_HOST],
            "allow_redirects": False,
            "request_timeout": REQUEST_TIMEOUT_SECONDS,
        },
        "resource_defaults": {},
        "resources": _build_resources(endpoint_config, params),
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.paginator_state is not None:
            initial_paginator_state = resume.paginator_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # The framework checkpoints after a page is yielded, so a crash re-yields the last page
        # (merge dedupes on the primary key) instead of skipping it.
        if state:
            resumable_source_manager.save_state(Dynamics365BusinessCentralResumeConfig(paginator_state=state))

    resources = rest_api_resources(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    target = next(resource for resource in resources if resource.name == endpoint)

    return SourceResponse(
        name=endpoint,
        items=lambda: target,
        primary_keys=list(endpoint_config.primary_keys),
        # Business Central doesn't document the default order of its API pages and `$skiptoken`
        # paging rejects an `$orderby` on some entities, so incremental endpoints must only
        # persist their watermark at successful job end — which "desc" guarantees.
        sort_mode="desc" if endpoint_config.cursor_field else "asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
        chunk_size=CHUNK_SIZE,
        chunk_size_bytes=CHUNK_SIZE_BYTES,
        column_hints=target.column_hints,
    )


def validate_credentials(
    tenant_id: str,
    environment: str,
    client_id: str,
    client_secret: str,
    api_version: str,
) -> tuple[bool, str | None]:
    """Mint an Entra ID token and list companies — the cheapest proof the app can read the tenant."""
    try:
        base_url = build_base_url(tenant_id, environment, api_version)
        auth = build_auth(tenant_id, client_id, client_secret)
    except BusinessCentralConfigurationError as e:
        return False, str(e)

    session = make_tracked_session(redact_values=(client_secret,), allow_redirects=False)
    try:
        response = session.get(
            f"{base_url}/{COMPANIES_ENDPOINT}",
            auth=auth,
            timeout=VALIDATE_TIMEOUT_SECONDS,
            allow_redirects=False,
        )
    except OAuth2AuthRequestError as e:
        return False, f"Microsoft Entra ID rejected the token request: {strip_oauth2_permanent_marker(str(e))}"
    except Exception:
        return False, "Could not reach Business Central. Please check the tenant ID and environment name."

    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return (
            False,
            "Business Central denied access. Grant your Entra app the API.ReadWrite.All permission with admin "
            "consent, and add it as a Business Central user in this environment.",
        )
    if response.status_code == 404:
        return False, f"No Business Central environment named `{environment}` was found for this tenant."
    return False, f"Business Central returned HTTP {response.status_code}"
