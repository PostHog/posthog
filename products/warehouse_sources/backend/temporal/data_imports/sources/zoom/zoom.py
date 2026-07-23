import dataclasses
from typing import Any, Optional, cast

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    OAuth2Auth,
    OAuth2GrantType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.zoom.settings import (
    ZOOM_ENDPOINTS,
    ZoomEndpointConfig,
)

ZOOM_API_BASE = "https://api.zoom.us/v2"
ZOOM_OAUTH_URL = "https://zoom.us/oauth/token"

# Zoom paginates every list endpoint with an opaque `next_page_token` carried in the body and echoed
# back as a query param; the framework's cursor paginator stops when the token comes back empty.
_CURSOR_PATH = "next_page_token"
_CURSOR_PARAM = "next_page_token"


@dataclasses.dataclass
class ZoomResumeConfig:
    # Top-level (users): the opaque cursor for the next page. Kept under its original name so state
    # saved by the previous implementation still deserializes.
    next_page_token: str = ""
    # Retained for backwards compatibility with state saved by the previous fan-out implementation
    # (`ResumableSourceManager` reconstructs the dataclass from saved keys). No longer written.
    user_index: int = 0
    # Fan-out (meetings/webinars): the framework's dependent-resource resume state
    # (`{"completed": [...], "current": ..., "child_state": ...}`).
    fanout_state: Optional[dict[str, Any]] = None


def _oauth_auth(account_id: str, client_id: str, client_secret: str) -> OAuth2Auth:
    """Server-to-Server OAuth for Zoom: exchange the account credentials for a short-lived bearer
    token (Basic client auth, `account_id` in the token-request body), minted lazily and re-minted
    before expiry by the framework. Using the framework auth keeps the client secret and the minted
    token redacted from logs and error messages."""
    return OAuth2Auth(
        token_url=ZOOM_OAUTH_URL,
        client_id=client_id,
        client_secret=client_secret,
        grant_type=cast(OAuth2GrantType, "account_credentials"),
        client_auth_method="basic",
        extra_token_request_params={"account_id": account_id},
    )


def _client_config(account_id: str, client_id: str, client_secret: str) -> ClientConfig:
    return {
        "base_url": ZOOM_API_BASE,
        "auth": _oauth_auth(account_id, client_id, client_secret),
        "paginator": JSONResponseCursorPaginator(cursor_path=_CURSOR_PATH, cursor_param=_CURSOR_PARAM),
    }


def _top_level_resource(
    client_config: ClientConfig,
    config: ZoomEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ZoomResumeConfig],
) -> Resource:
    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_page_token:
            initial_paginator_state = {"cursor": resume.next_page_token}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only while a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(ZoomResumeConfig(next_page_token=state["cursor"]))

    rest_config: RESTAPIConfig = {
        "client": client_config,
        "resource_defaults": {},
        "resources": [
            {
                "name": config.name,
                "endpoint": {
                    "path": config.path,
                    "params": {"page_size": config.page_size, **config.params},
                    "data_selector": config.data_key,
                },
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


def _fan_out_resource(
    client_config: ClientConfig,
    config: ZoomEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ZoomResumeConfig],
) -> Resource:
    users_config = ZOOM_ENDPOINTS["users"]

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.fanout_state:
            initial_paginator_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state is not None:
            resumable_source_manager.save_state(ZoomResumeConfig(fanout_state=state))

    child_params: dict[str, Any] = {
        "user_id": {"type": "resolve", "resource": "users", "field": "id"},
        "page_size": config.page_size,
        **config.params,
    }

    rest_config: RESTAPIConfig = {
        "client": client_config,
        "resource_defaults": {},
        "resources": [
            {
                "name": "users",
                "endpoint": {
                    "path": users_config.path,
                    "params": {"page_size": users_config.page_size},
                    "data_selector": users_config.data_key,
                },
            },
            {
                "name": config.name,
                "include_from_parent": [],
                "endpoint": {
                    "path": config.path,
                    "params": child_params,
                    "data_selector": config.data_key,
                    # A user without the relevant license returns 400/404 for that feature; skip that
                    # user without aborting the whole sync (an empty page that stops this user's
                    # pagination). Any other non-2xx still raises.
                    "response_actions": [
                        {"status_code": 400, "action": "ignore"},
                        {"status_code": 404, "action": "ignore"},
                    ],
                },
            },
        ],
    }

    resources = rest_api_resources(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    return next(r for r in resources if r.name == config.name)


def zoom_source(
    account_id: str,
    client_id: str,
    client_secret: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ZoomResumeConfig],
) -> SourceResponse:
    config = ZOOM_ENDPOINTS[endpoint]
    client_config = _client_config(account_id, client_id, client_secret)

    if config.fan_out:
        resource = _fan_out_resource(client_config, config, team_id, job_id, resumable_source_manager)
    else:
        resource = _top_level_resource(client_config, config, team_id, job_id, resumable_source_manager)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(
    account_id: str,
    client_id: str,
    client_secret: str,
    schema_name: Optional[str] = None,
) -> tuple[bool, str | None]:
    auth = _oauth_auth(account_id, client_id, client_secret)

    # Minting the token verifies the account ID / client ID / secret without touching a scoped
    # endpoint. Any failure here means the credentials themselves are wrong.
    try:
        auth._obtain_token()
    except Exception:
        return False, "Invalid Zoom account ID, client ID, or client secret"

    # At source-create (no specific schema) a genuine token is enough — users may only grant scopes
    # for the endpoints they intend to sync, so don't probe a scoped endpoint here.
    if schema_name is None:
        return True, None

    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(client_secret,)),
        f"{ZOOM_API_BASE}/users?page_size=1",
        auth=auth,
    )
    if ok:
        return True, None
    if status in (401, 403):
        return (
            False,
            "Zoom credentials are valid but lack the required scopes. Grant user/meeting/webinar read scopes and retry.",
        )
    return False, f"Zoom API returned an unexpected status ({status})"
