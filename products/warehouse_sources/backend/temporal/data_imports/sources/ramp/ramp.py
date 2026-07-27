import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

import requests
from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    OAuth2Auth,
    OAuth2AuthRequestError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponsePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.ramp.settings import RAMP_ENDPOINTS, TOKEN_SCOPES

RAMP_HOSTS = {
    "production": "https://api.ramp.com",
    "sandbox": "https://demo-api.ramp.com",
}
# Ramp list pages cap at 100 items.
PAGE_SIZE = 100


@dataclasses.dataclass
class RampResumeConfig:
    # Ramp paginates via the self-contained page.next URL. Optional/defaulted so previously
    # saved state (which always carried next_url) still parses via dataclass(**saved).
    next_url: Optional[str] = None


def _base_url(environment: str) -> str:
    host = RAMP_HOSTS.get(environment)
    if host is None:
        raise ValueError(f"Invalid Ramp environment: {environment}")
    return host


def _api_base_url(environment: str) -> str:
    return f"{_base_url(environment)}/developer/v1"


def _token_url(environment: str) -> str:
    return f"{_api_base_url(environment)}/token"


def _make_auth(environment: str, client_id: str, client_secret: str) -> OAuth2Auth:
    """Ramp uses OAuth2 client-credentials with HTTP Basic client auth.

    Tokens last ~10 days; the framework mints one lazily, caches it for the run, and re-mints
    on expiry — replacing the pre-framework mint-once-then-reactive-401-remint handling."""
    return OAuth2Auth(
        token_url=_token_url(environment),
        client_id=client_id,
        client_secret=client_secret,
        grant_type="client_credentials",
        scopes=TOKEN_SCOPES,
        client_auth_method="basic",
    )


def _format_timestamp(value: Any) -> str:
    """Format an incremental cursor for Ramp's from_date filter (ISO 8601 UTC)."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%dT00:00:00Z")
    return str(value)


class RampPaginator(JSONResponsePaginator):
    """Follow Ramp's self-contained ``page.next`` link, stopping on an empty page.

    Ramp returns a ``page.next`` URL until the listing is exhausted; the hand-rolled source
    also stopped as soon as a page came back empty (even if a ``next`` link was still present),
    so mirror that guard here. Resume state (the pending ``next_url``) is inherited from the
    base next-url paginator."""

    def __init__(self) -> None:
        super().__init__(next_url_path="page.next")

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if not data:
            self._has_next_page = False
            return
        super().update_state(response, data)


def validate_credentials(environment: str, client_id: str, client_secret: str) -> tuple[bool, str | None]:
    """Confirm the developer app credentials are valid by minting a token.

    Distinguishes a genuine credential rejection (permanent 4xx from the token endpoint) from a
    transient connectivity problem so the user sees an actionable message instead of a blanket
    "invalid credentials"."""
    auth = _make_auth(environment, client_id, client_secret)
    # Force the lazy token mint through the public auth callable; a bad credential raises here.
    probe = Request(method="GET", url=_api_base_url(environment)).prepare()
    try:
        auth(probe)
    except OAuth2AuthRequestError as e:
        if e.is_permanent:
            return (
                False,
                "Ramp rejected the credentials. Check the client ID and secret, and that the developer "
                "app has the required scopes.",
            )
        return False, "Ramp is temporarily unavailable. Please check your selected environment and retry."
    except requests.RequestException as e:
        return False, f"Could not reach Ramp ({e}). Please check your network and selected environment, then retry."
    return True, None


def ramp_source(
    environment: str,
    client_id: str,
    client_secret: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[RampResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = RAMP_ENDPOINTS[endpoint]
    auth = _make_auth(environment, client_id, client_secret)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    params: dict[str, Any] = {"page_size": PAGE_SIZE}
    if (
        config.incremental_param is not None
        and should_use_incremental_field
        and db_incremental_field_last_value is not None
    ):
        params[config.incremental_param] = _format_timestamp(db_incremental_field_last_value)

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resume is not None and resume.next_url is not None:
        initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # The framework calls the hook AFTER a page is yielded and only while a next page remains,
        # so a crash re-yields the last batch (merge dedupes on primary key) rather than skipping it.
        if state is not None and state.get("next_url") is not None:
            resumable_source_manager.save_state(RampResumeConfig(next_url=state["next_url"]))

    endpoint_config: Endpoint = {
        "path": config.path,
        "params": params,
        "data_selector": "data",
        "paginator": RampPaginator(),
    }
    client_config: ClientConfig = {
        "base_url": _api_base_url(environment),
        "auth": auth,
        # Pin every request — including page.next links and the seeded resume URL — to the
        # configured Ramp host so a tampered next/resume link can't exfiltrate the bearer token.
        "allowed_hosts": [],
    }
    rest_config: RESTAPIConfig = {
        "client": client_config,
        "resources": [{"name": endpoint, "endpoint": endpoint_config}],
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
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Result ordering within a from_date window is not documented, so the
        # pipeline defers incremental watermark commits until a run completes.
        sort_mode="desc" if config.incremental_fields else "asc",
    )
