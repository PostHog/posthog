import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

import requests
from requests import Request

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    HttpBasicAuth,
    OAuth2Auth,
    OAuth2AuthRequestError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    HeaderLinkPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.greenhouse.settings import (
    GREENHOUSE_ENDPOINTS,
    GREENHOUSE_V3,
    GreenhouseEndpointConfig,
)

GREENHOUSE_BASE_HOST = "https://harvest.greenhouse.io"
# v3 mints short-lived JWTs from the customer's own OAuth2 client credentials; v1 has no
# token exchange (the API key is sent directly as HTTP Basic on every request).
GREENHOUSE_TOKEN_URL = "https://auth.greenhouse.io/token"
# Harvest's documented maximum page size, on both v1 and v3. Fewer requests keeps us comfortably
# under the per-10-second rate limit advertised via the `X-RateLimit-*` response headers.
PAGE_SIZE = 500

MISSING_V3_CREDENTIALS_ERROR = (
    "Greenhouse Harvest v3 requires OAuth client credentials. "
    "In Greenhouse, go to Configure → Dev Center → API Credential Management, create a "
    "**Harvest V3 (OAuth)** credential, and enter its client ID and client secret."
)
MISSING_V1_CREDENTIALS_ERROR = "Greenhouse Harvest v1 requires an API key."


def _base_url(api_version: str) -> str:
    return f"{GREENHOUSE_BASE_HOST}/{api_version}"


@dataclasses.dataclass
class GreenhouseResumeConfig:
    # Harvest paginates with RFC 5988 `Link` headers. We persist the full `rel="next"` URL
    # (it already carries `per_page` plus any timestamp filter) so a resumed run continues
    # from the same page rather than restarting the stream.
    next_url: str


def _format_datetime(value: Any) -> str:
    """Format an incremental cursor value as the ISO 8601 string Harvest's `*_after` filters expect."""
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if isinstance(value, date):
        return value.strftime("%Y-%m-%dT00:00:00.000Z")
    return str(value)


def _build_initial_params(
    config: GreenhouseEndpointConfig,
    api_version: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"per_page": PAGE_SIZE}

    if not (should_use_incremental_field and incremental_field and db_incremental_field_last_value is not None):
        return params

    cursor = _format_datetime(db_incremental_field_last_value)

    if api_version == GREENHOUSE_V3:
        # v3 filters on the timestamp field itself with a pipe-delimited operator
        # (`updated_at=gte|<iso>`) instead of v1's separate `*_after` params.
        if any(field["field"] == incremental_field for field in config.incremental_fields):
            params[incremental_field] = f"gte|{cursor}"
        return params

    filter_param = config.incremental_filter_params.get(incremental_field)
    if filter_param:
        # Both versions filter inclusively (`*_after` on v1, `gte` on v3) — merge dedupes the
        # boundary rows.
        params[filter_param] = cursor

    return params


def _build_auth(
    api_version: str, api_key: str | None, client_id: str | None, client_secret: str | None
) -> HttpBasicAuth | OAuth2Auth:
    """Build the per-version request auth.

    v1 sends the Harvest API key as HTTP Basic (key as username, blank password). v3 rejects Basic
    entirely and requires a Bearer JWT minted from the customer's OAuth2 client credentials, so the
    two versions take different secrets. Supplied via framework auth either way, so the credential
    is redacted from logs and error messages.
    """
    if api_version == GREENHOUSE_V3:
        if not client_id or not client_secret:
            raise ValueError(MISSING_V3_CREDENTIALS_ERROR)
        return OAuth2Auth(
            token_url=GREENHOUSE_TOKEN_URL,
            client_id=client_id,
            client_secret=client_secret,
            grant_type="client_credentials",
            # Greenhouse takes the client credentials as HTTP Basic on the token request, not in
            # the body. Its response carries `expires_at` (an absolute ISO 8601 string) rather than
            # `expires_in`, in an unpinned format — leave the expiry hint unparsed and let the
            # framework's conservative default TTL drive re-minting.
            client_auth_method="basic",
        )

    if not api_key:
        raise ValueError(MISSING_V1_CREDENTIALS_ERROR)
    return HttpBasicAuth(api_key, "")


def validate_credentials(
    api_version: str,
    api_key: str | None = None,
    client_id: str | None = None,
    client_secret: str | None = None,
    path: str = "/candidates",
    accept_forbidden: bool = True,
) -> tuple[bool, str | None]:
    """Probe a Harvest endpoint on ``api_version`` to confirm the credentials are genuine.

    Harvest credentials are scoped per-resource: a valid one may still 403 on an endpoint it wasn't
    granted. At source-create time (``accept_forbidden=True``) we treat 403 as success so users
    can connect with credentials scoped only to the endpoints they want; per-schema checks pass
    ``accept_forbidden=False`` to surface a missing-scope error for that specific endpoint.
    """
    try:
        auth = _build_auth(api_version, api_key, client_id, client_secret)
    except ValueError as e:
        return False, str(e)

    if isinstance(auth, OAuth2Auth):
        # Mint up front so a bad client credential reports itself instead of surfacing as an
        # unreachable probe — `validate_via_probe` swallows the exception into `(False, None)`.
        try:
            auth(Request(method="GET", url=_base_url(api_version)).prepare())
        except (OAuth2AuthRequestError, requests.RequestException):
            return False, "Invalid Greenhouse client credentials. Please check them and try again."

    _ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=tuple(v for v in (api_key, client_secret) if v)),
        f"{_base_url(api_version)}{path}?per_page=1",
        auth=auth,
    )

    if status == 200:
        return True, None

    if status == 403:
        if accept_forbidden:
            return True, None
        return False, "Your Greenhouse credentials do not have permission to access this endpoint."

    if status == 401:
        return False, "Invalid Greenhouse credentials. Please check them and try again."

    if status is None:
        return False, "Could not reach the Greenhouse API. Please try again."

    return False, f"Greenhouse API returned an unexpected status code: {status}"


def greenhouse_source(
    endpoint: str,
    team_id: int,
    job_id: str,
    api_version: str,
    resumable_source_manager: ResumableSourceManager[GreenhouseResumeConfig],
    api_key: str | None = None,
    client_id: str | None = None,
    client_secret: str | None = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = GREENHOUSE_ENDPOINTS[endpoint]

    params = _build_initial_params(
        config, api_version, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": _base_url(api_version),
            "auth": _build_auth(api_version, api_key, client_id, client_secret),
            # Both versions paginate with RFC 5988 `Link` headers; the paginator follows the
            # `rel="next"` URL verbatim. v1's carries per_page + filters, v3's carries an opaque
            # cursor that must travel alone — following it verbatim satisfies both.
            "paginator": HeaderLinkPaginator(),
            # Because that next URL is followed verbatim, pin every request (paginator and seeded
            # resume URLs included) to the base host and reject cross-host redirects: a spoofed
            # link must not be able to replay the credential — v3's minted Bearer token especially
            # — to another origin. `allowed_hosts=[]` means "same host as base_url only".
            "allowed_hosts": [],
            "allow_redirects": False,
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path_for_version(api_version),
                    "params": params,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(GreenhouseResumeConfig(next_url=str(state["next_url"])))

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
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Harvest orders list results by `id`, not by the timestamp cursor, so there is no way
        # to request ascending-by-cursor ordering. We keep `asc` (the watermark advances to the
        # max cursor value seen) and rely on the resumable `Link` cursor to make in-run retries
        # safe; merge semantics dedupe re-fetched rows.
        sort_mode="asc",
        column_hints=resource.column_hints,
    )
