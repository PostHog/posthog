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
from products.warehouse_sources.backend.temporal.data_imports.sources.personio.settings import PERSONIO_ENDPOINTS

PERSONIO_BASE_URL = "https://api.personio.de"
TOKEN_URL = f"{PERSONIO_BASE_URL}/v2/auth/token"


@dataclasses.dataclass
class PersonioResumeConfig:
    # Personio v2 paginates via _meta.links.next.href, a self-contained URL (opaque cursor), so
    # the URL is all we persist. Optional/defaulted so previously saved state (which always carried
    # next_url) still parses via dataclass(**saved).
    next_url: Optional[str] = None


def _make_auth(client_id: str, client_secret: str) -> OAuth2Auth:
    """Personio v2 uses OAuth2 client-credentials with the credentials carried in the request body.

    Tokens last ~24h; the framework mints one lazily, caches it for the run, and re-mints on
    expiry — replacing the pre-framework mint-once-then-reactive-401-remint handling."""
    return OAuth2Auth(
        token_url=TOKEN_URL,
        client_id=client_id,
        client_secret=client_secret,
        grant_type="client_credentials",
        client_auth_method="body",
    )


def _format_updated_at(value: Any) -> str:
    """Format an incremental cursor for Personio's RFC3339 date-time filters."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%dT00:00:00Z")
    return str(value)


class PersonioPaginator(JSONResponsePaginator):
    """Follow Personio's self-contained ``_meta.links.next.href`` link, stopping on an empty page.

    Personio returns a next href until the listing is exhausted; the hand-rolled source also
    stopped as soon as a page came back empty (even if a next link was still present), so mirror
    that guard here. Resume state (the pending ``next_url``) is inherited from the base next-url
    paginator."""

    def __init__(self) -> None:
        super().__init__(next_url_path="_meta.links.next.href")

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if not data:
            self._has_next_page = False
            return
        super().update_state(response, data)


def validate_credentials(client_id: str, client_secret: str) -> bool:
    """Confirm the credentials are valid by minting a token — scopes are granted per credential,
    so a successful mint is the only universal probe."""
    auth = _make_auth(client_id, client_secret)
    # Force the lazy token mint through the public auth callable; a bad credential raises here.
    probe = Request(method="GET", url=PERSONIO_BASE_URL).prepare()
    try:
        auth(probe)
    except (OAuth2AuthRequestError, requests.RequestException):
        return False
    return True


def personio_source(
    client_id: str,
    client_secret: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[PersonioResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = PERSONIO_ENDPOINTS[endpoint]
    auth = _make_auth(client_id, client_secret)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    params: dict[str, Any] = {"limit": config.page_size}
    if (
        config.incremental_param is not None
        and should_use_incremental_field
        and db_incremental_field_last_value is not None
    ):
        params[config.incremental_param] = _format_updated_at(db_incremental_field_last_value)

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resume is not None and resume.next_url is not None:
        initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # The framework calls the hook AFTER a page is yielded and only while a next page remains,
        # so a crash re-yields the last batch (merge dedupes on primary key) rather than skipping it.
        if state is not None and state.get("next_url") is not None:
            resumable_source_manager.save_state(PersonioResumeConfig(next_url=state["next_url"]))

    endpoint_config: Endpoint = {
        "path": config.path,
        "params": params,
        "data_selector": "_data",
        "paginator": PersonioPaginator(),
    }
    client_config: ClientConfig = {
        "base_url": PERSONIO_BASE_URL,
        "auth": auth,
        # Pin every request — including _meta.links.next.href links and the seeded resume URL — to
        # api.personio.de so a tampered next/resume link can't exfiltrate the bearer token. Disable
        # redirects so a 3xx can't bounce the authenticated request (and token) off-host either.
        "allowed_hosts": [],
        "allow_redirects": False,
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
        sort_mode="asc",
    )
