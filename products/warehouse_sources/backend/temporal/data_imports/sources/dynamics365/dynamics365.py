import re
import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlparse

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import OAuth2Auth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponsePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.dynamics365.settings import (
    DYNAMICS365_ENDPOINTS,
    DYNAMICS365_LOGIN_HOST,
    DYNAMICS365_PAGE_SIZE,
    DYNAMICS365_REQUEST_TIMEOUT,
    Dynamics365EndpointConfig,
)

# The environment URL is customer-supplied and is where the minted access token is sent, so it is
# pinned to the hosts Microsoft actually serves Dataverse on: `{org}[.api].crm{n}.<suffix>`, where
# crm{n} is the region (crm = North America, crm4 = EMEA, crm11 = UK, ...) and the suffix covers
# commercial, China (21Vianet), and US government clouds. Anything else — including an internal
# host or an attacker's server — is refused before a token is minted.
_ORGANIZATION_HOST_RE = re.compile(
    r"^[a-z0-9][a-z0-9-]{0,62}(\.api)?\.crm[0-9]{0,2}\.(dynamics\.com|dynamics\.cn|microsoftdynamics\.us|appsplatform\.us)$"
)
# Entra tenant ids are GUIDs or verified domain names; both are interpolated into the token URL
# path, so anything that could escape that path segment is refused.
_TENANT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
# A watermark that reaches `$filter` as a string must look like a timestamp — the value is
# interpolated into an OData expression, so an arbitrary string can't be passed through.
_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$")

INVALID_ORGANIZATION_URL_ERROR = "Enter your Dynamics 365 environment URL, for example https://contoso.crm.dynamics.com"
INVALID_TENANT_ID_ERROR = "Enter the directory (tenant) ID of your Microsoft Entra ID tenant"
INVALID_WATERMARK_ERROR = "The stored incremental value is not a timestamp Dynamics 365 can filter on"


class Dynamics365ConfigurationError(Exception):
    """A customer-supplied value can't be used to build a Dataverse request."""


@dataclasses.dataclass(frozen=True)
class Dynamics365ResumeConfig:
    # Opaque `@odata.nextLink` of the next unfetched page (it embeds Dataverse's $skiptoken, which
    # must never be constructed by hand).
    next_url: Optional[str] = None


def normalize_organization_url(raw: str) -> str:
    """Validate the environment URL and reduce it to `https://<host>`.

    Rebuilding from the parsed hostname alone drops any port, userinfo, path, or query the user
    pasted, so the base URL can't be pointed at a non-Dataverse target.
    """
    value = (raw or "").strip().rstrip("/")
    if not value:
        raise Dynamics365ConfigurationError(INVALID_ORGANIZATION_URL_ERROR)
    if "://" not in value:
        value = f"https://{value}"
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not _ORGANIZATION_HOST_RE.match(host):
        raise Dynamics365ConfigurationError(INVALID_ORGANIZATION_URL_ERROR)
    return f"https://{host}"


def token_url(tenant_id: str) -> str:
    value = (tenant_id or "").strip()
    if not _TENANT_ID_RE.match(value):
        raise Dynamics365ConfigurationError(INVALID_TENANT_ID_ERROR)
    return f"https://{DYNAMICS365_LOGIN_HOST}/{value}/oauth2/v2.0/token"


def base_url(organization_url: str, api_version: str) -> str:
    return f"{organization_url}/api/data/{api_version}"


def make_auth(tenant_id: str, client_id: str, client_secret: str, organization_url: str) -> OAuth2Auth:
    """Build the client-credentials auth for a Dataverse application user.

    The app registration's secret is exchanged for an access token scoped to the environment
    itself (`https://{org}.crm.dynamics.com/.default`); the framework caches it for the run and
    re-mints on expiry.
    """
    return OAuth2Auth(
        token_url=token_url(tenant_id),
        client_id=client_id,
        client_secret=client_secret,
        grant_type="client_credentials",
        scopes=f"{organization_url}/.default",
    )


def request_headers() -> dict[str, str]:
    return {
        "Accept": "application/json",
        "OData-MaxVersion": "4.0",
        "OData-Version": "4.0",
        # Without this Dataverse pages at 5,000 rows anyway, but declaring it keeps the page size
        # stable if the server default ever changes.
        "Prefer": f"odata.maxpagesize={DYNAMICS365_PAGE_SIZE}",
    }


def format_odata_datetime(value: Any) -> str:
    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=UTC)
        return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%dT00:00:00Z")
    text = str(value).strip()
    if not _TIMESTAMP_RE.match(text):
        raise Dynamics365ConfigurationError(INVALID_WATERMARK_ERROR)
    return text.replace(" ", "T")


def resolve_incremental_field(config: Dynamics365EndpointConfig, requested: Optional[str]) -> str:
    """Honour the cursor the user picked in the schema settings, ignoring anything unadvertised.

    The name is interpolated into `$filter` and `$orderby`, so only the advertised columns are
    accepted — an unexpected value falls back to the endpoint default rather than reaching OData.
    """
    advertised = {incremental["field"] for incremental in config.incremental_fields}
    if requested in advertised:
        return str(requested)
    return config.default_incremental_field


def build_query_params(
    config: Dynamics365EndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
    incremental_field: Optional[str],
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if config.select:
        params["$select"] = ",".join(config.select)
    if not should_use_incremental_field:
        return params

    cursor = resolve_incremental_field(config, incremental_field)
    # Dataverse's default order is undocumented, so the cursor column is ordered explicitly to make
    # the ascending `sort_mode` the pipeline checkpoints against true.
    params["$orderby"] = f"{cursor} asc"
    if db_incremental_field_last_value is not None:
        params["$filter"] = f"{cursor} gt {format_odata_datetime(db_incremental_field_last_value)}"
    return params


def strip_odata_annotations(row: dict[str, Any]) -> dict[str, Any]:
    """Drop the OData control annotations Dataverse mixes into every record.

    Each row carries `@odata.etag` (and, when requested, formatted-value annotations); those aren't
    table columns and an `@` in a column name is hostile to everything downstream.
    """
    return {key: value for key, value in row.items() if "@" not in key}


def _client_config(auth: OAuth2Auth, organization_url: str, api_version: str) -> ClientConfig:
    return {
        "base_url": base_url(organization_url, api_version),
        "headers": request_headers(),
        "auth": auth,
        # `@odata.nextLink` is an absolute URL carrying an opaque $skiptoken plus the original
        # query, so the filter and ordering persist across pages.
        "paginator": JSONResponsePaginator(next_url_path="'@odata.nextLink'"),
        # Pin every request — including next links — to the validated environment host, and refuse
        # redirects, so a spoofed link can't carry the access token off-host.
        "allowed_hosts": [],
        "allow_redirects": False,
        "request_timeout": DYNAMICS365_REQUEST_TIMEOUT,
    }


def dynamics365_source(
    organization_url: str,
    tenant_id: str,
    client_id: str,
    client_secret: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    api_version: str,
    resumable_source_manager: ResumableSourceManager[Dynamics365ResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: Optional[str] = None,
) -> SourceResponse:
    config = DYNAMICS365_ENDPOINTS[endpoint]
    organization = normalize_organization_url(organization_url)
    auth = make_auth(tenant_id, client_id, client_secret, organization)

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_url is not None:
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # The hook fires after a page has been yielded, so a crash re-yields the last batch (the
        # merge dedupes on the GUID primary key) instead of skipping it.
        if state is not None and state.get("next_url") is not None:
            resumable_source_manager.save_state(Dynamics365ResumeConfig(next_url=str(state["next_url"])))

    endpoint_config: Endpoint = {
        "path": f"/{config.entity_set}",
        "params": build_query_params(
            config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
        ),
        "data_selector": "value",
        # An OData collection response always carries `value`. Failing loud beats silently syncing
        # zero rows if a request ever comes back shaped like something else.
        "data_selector_required": True,
    }
    rest_config: RESTAPIConfig = {
        "client": _client_config(auth, organization, api_version),
        "resources": [
            {
                "name": endpoint,
                "endpoint": endpoint_config,
                "data_map": strip_odata_annotations,
            }
        ],
    }
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
        primary_keys=list(config.primary_keys),
        # Incremental runs order by the cursor column explicitly; full refreshes are unordered but
        # commit no watermark.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[config.partition_key],
    )


def probe_credentials(
    organization_url: str,
    tenant_id: str,
    client_id: str,
    client_secret: str,
    api_version: str,
    endpoint: Optional[str] = None,
    *,
    ok_statuses: tuple[int, ...] = (200,),
) -> tuple[bool, int | None]:
    """Mint a token and read one row from a table, reporting `(is_valid, status_code)`.

    Raises `Dynamics365ConfigurationError` when the environment URL or tenant id can't be used at
    all — the caller turns that into a field-level message instead of a failed probe.
    """
    organization = normalize_organization_url(organization_url)
    # An unknown (or absent) schema name falls back to accounts, the table every environment has.
    config = DYNAMICS365_ENDPOINTS.get(endpoint or "", DYNAMICS365_ENDPOINTS["Accounts"])
    auth = make_auth(tenant_id, client_id, client_secret, organization)
    url = f"{base_url(organization, api_version)}/{config.entity_set}?$top=1&$select={config.primary_keys[0]}"
    return validate_via_probe(
        lambda: make_tracked_session(redact_values=(client_secret,)),
        url,
        headers=request_headers(),
        auth=auth,
        ok_statuses=ok_statuses,
        # The environment host is pinned by normalize_organization_url; refuse a redirect rather
        # than replay the token somewhere else.
        allow_redirects=False,
    )
