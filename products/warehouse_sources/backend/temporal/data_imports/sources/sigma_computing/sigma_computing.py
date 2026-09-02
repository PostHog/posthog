from typing import Any, Optional, cast

import requests

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    PaginatorConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.sigma_computing.settings import (
    SIGMA_ENDPOINTS,
    SigmaComputingEndpointConfig,
    resolve_base_url,
)

TOKEN_ERROR = "Sigma rejected the API client credentials"
VALIDATE_TIMEOUT = 15


class SigmaAuthError(Exception):
    pass


@frozen
class SigmaComputingResumeConfig:
    # Opaque framework checkpoint: `{"cursor": ...}` for a top-level endpoint's
    # JSONResponseCursorPaginator, or the fan-out manager's combined state for a workbook-scoped
    # child endpoint - round-tripped into `initial_paginator_state` on resume. Frozen since it's
    # only ever constructed fresh and handed to `resumable_source_manager.save_state`.
    paginator_state: dict[str, Any]


def _paginator_config() -> PaginatorConfig:
    return {"type": "cursor", "cursor_path": "nextPage", "cursor_param": "page"}


def _client_config(base_url: str, client_id: str, client_secret: str) -> ClientConfig:
    return {
        "base_url": base_url,
        "headers": {"Accept": "application/json"},
        # The framework auth mints (and re-mints on expiry) the ~1h access token, and redacts the
        # client secret / access token from logs and samples.
        "auth": {
            "type": "oauth2",
            "token_url": f"{base_url}/v2/auth/token",
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "client_credentials",
        },
    }


def get_resource(name: str) -> EndpointResource:
    config = SIGMA_ENDPOINTS[name]
    endpoint: Endpoint = {
        "path": config.path,
        "data_selector": "entries",
        "params": {"limit": config.page_size},
        "paginator": _paginator_config(),
    }
    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": "replace",
        "endpoint": endpoint,
        "table_format": "delta",
    }


def _mint_token(base_url: str, client_id: str, client_secret: str) -> str:
    session = make_tracked_session(redact_values=(client_secret,))
    try:
        response = session.post(
            f"{base_url}/v2/auth/token",
            data={"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret},
            timeout=VALIDATE_TIMEOUT,
        )
    except requests.exceptions.RequestException as e:
        raise SigmaAuthError(str(e)) from e

    if response.status_code != 200:
        raise SigmaAuthError(f"{TOKEN_ERROR} (HTTP {response.status_code})")

    token = response.json().get("access_token")
    if not isinstance(token, str) or not token:
        raise SigmaAuthError(f"{TOKEN_ERROR}: no access token returned")
    return token


def validate_credentials(
    region: str,
    client_id: str,
    client_secret: str,
    schema_name: Optional[str] = None,
) -> tuple[bool, str | None]:
    """Mint a token, then probe the cheap Workbooks list to confirm the client can read the org.

    At source-create (`schema_name is None`) a 403 is accepted: the client credentials are
    genuine but may simply lack the Workbooks scope while holding others. A scoped probe (a
    specific schema being checked) treats 403 as a hard failure.
    """
    try:
        base_url = resolve_base_url(region)
    except ValueError as e:
        return False, str(e)

    try:
        token = _mint_token(base_url, client_id, client_secret)
    except SigmaAuthError as e:
        return False, str(e)

    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(client_secret, token)),
        f"{base_url}/v2/workbooks",
        headers={"Authorization": f"Bearer {token}"},
        ok_statuses=(200, 403) if schema_name is None else (200,),
        timeout=VALIDATE_TIMEOUT,
    )
    if ok:
        return True, None
    if status == 401:
        return False, "Sigma rejected the access token for this client."
    if status == 403:
        return False, "Your Sigma API client does not have permission for this resource."
    if status is None:
        return False, "Could not reach Sigma. Please check your network and try again."
    return False, f"Sigma API returned an unexpected status: {status}"


def _make_source_response(endpoint_config: SigmaComputingEndpointConfig, items_fn: Any) -> SourceResponse:
    return SourceResponse(
        name=endpoint_config.name,
        items=items_fn,
        primary_keys=(
            endpoint_config.primary_key
            if isinstance(endpoint_config.primary_key, list)
            else [endpoint_config.primary_key]
        ),
        # No list endpoint documents an ordering guarantee or a server-side time filter, so every
        # sync is a full refresh with nothing downstream depending on row order.
        sort_mode=None,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )


def sigma_computing_source(
    region: str,
    client_id: str,
    client_secret: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SigmaComputingResumeConfig],
) -> SourceResponse:
    endpoint_config = SIGMA_ENDPOINTS[endpoint]
    base_url = resolve_base_url(region)
    client_config = _client_config(base_url, client_id, client_secret)

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = resume_config.paginator_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's a next page to resume to; the manager's 24h Redis TTL handles
        # cleanup once a sync completes.
        if state:
            resumable_source_manager.save_state(SigmaComputingResumeConfig(paginator_state=dict(state)))

    if endpoint_config.fanout:
        dependent_resource = build_dependent_resource(
            endpoint_configs=cast(Any, SIGMA_ENDPOINTS),
            child_endpoint=endpoint,
            fanout=endpoint_config.fanout,
            client_config=client_config,
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            page_size_param="limit",
            parent_endpoint_extra={"paginator": _paginator_config(), "data_selector": "entries"},
            child_endpoint_extra={"paginator": _paginator_config(), "data_selector": "entries"},
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        )
        return _make_source_response(endpoint_config, lambda: dependent_resource)

    config: RESTAPIConfig = {
        "client": client_config,
        "resource_defaults": {},
        "resources": [get_resource(endpoint)],
    }

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    return _make_source_response(endpoint_config, lambda: resource)
