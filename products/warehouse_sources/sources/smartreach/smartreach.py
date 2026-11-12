import dataclasses
from collections.abc import Callable
from typing import Any, Optional, cast
from urllib.parse import urlencode

from products.warehouse_sources.sources.sdk import (
    ApiKeyAuthConfig,
    ClientConfig,
    Endpoint,
    JSONResponsePaginator,
    Resource,
    RESTAPIConfig,
    ResumableSourceManager,
    SinglePagePaginator,
    SourceResponse,
    build_dependent_resource,
    make_tracked_session,
    rest_api_resource,
    validate_via_probe,
)
from products.warehouse_sources.sources.smartreach.settings import (
    SMARTREACH_API_V1,
    SMARTREACH_API_V3,
    SMARTREACH_ENDPOINTS,
    SmartreachEndpointConfig,
)

# Each version is served under its own base path; auth (X-API-KEY) and links.next pagination are
# shared. v3 diverges in two request-shaping ways we branch on below: the base path, and where the
# row list sits in the response envelope (root vs `data.*`). v3 also requires a `team_id` query
# param on the list endpoints (see smartreach_source / check_access).
SMARTREACH_BASE_URLS: dict[str, str] = {
    SMARTREACH_API_V1: "https://api.smartreach.io/api/v1",
    SMARTREACH_API_V3: "https://api.smartreach.io/api/v3",
}

# Kept for the several call sites and tests that reference the v1 origin directly.
SMARTREACH_BASE_URL = SMARTREACH_BASE_URLS[SMARTREACH_API_V1]

# Cheap endpoint used to confirm an API key is genuine. The user key is account-wide, so one probe
# validates access to every list endpoint.
DEFAULT_PROBE_ENDPOINT = "campaigns"


def _base_url(api_version: str) -> str:
    try:
        return SMARTREACH_BASE_URLS[api_version]
    except KeyError:
        # Never fall through to a default: silently syncing under an unmapped version is the drift
        # the version framework exists to prevent.
        raise ValueError(f"Unsupported SmartReach API version {api_version!r}")


def _data_selector(data_key: Optional[str], api_version: str) -> Optional[str]:
    # v3 returns the row list at the envelope root (e.g. `prospects`); v1 nests it under `data`.
    if data_key is None:
        return None
    if api_version == SMARTREACH_API_V3:
        return data_key
    return f"data.{data_key}"


@dataclasses.dataclass(frozen=False)
class SmartreachResumeConfig:
    # Full URL of the next page, taken verbatim from `links.next`. None means "start at the
    # endpoint's first page". The next URL already carries every pagination param, so the original
    # query params must NOT be re-sent alongside it (the paginator drops them).
    next_url: str | None = None
    # Fan-out endpoints store the `build_dependent_resource` checkpoint instead: which campaigns
    # finished and where the current one stopped.
    fanout_state: dict[str, Any] | None = None


def _headers() -> dict[str, str]:
    # Auth (the X-API-KEY header) is supplied via the framework auth config so its value is redacted
    # from logs and raised errors; only the non-secret Accept header is set here.
    return {"Accept": "application/json"}


def _api_key_auth(api_key: str) -> ApiKeyAuthConfig:
    return {"type": "api_key", "api_key": api_key, "name": "X-API-KEY", "location": "header"}


def _add_prospect_id(row: dict[str, Any]) -> dict[str, Any]:
    # The membership row nests the prospect object; its id is lifted out so it can be a primary key.
    row["prospect_id"] = (row.get("prospect") or {}).get("id")
    return row


_ROW_MAPS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "campaign_prospects": _add_prospect_id,
}


def _source_response(endpoint: str, config: SmartreachEndpointConfig, resource: Any) -> SourceResponse:
    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def smartreach_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SmartreachResumeConfig],
    api_version: str,
    smartreach_team_id: str | None = None,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = SMARTREACH_ENDPOINTS[endpoint]
    if api_version not in config.api_versions:
        raise ValueError(f"SmartReach table '{endpoint}' is not available on API version {api_version!r}")

    # v3 requires the SmartReach team id on every team-level request; v1 has no such param. Set it
    # only on the first request — the paginator then follows links.next verbatim, which already
    # carries it.
    team_params: dict[str, Any] = {}
    if api_version == SMARTREACH_API_V3 and smartreach_team_id and config.team_scoped:
        team_params = {"team_id": smartreach_team_id}

    client_config: ClientConfig = {
        "base_url": _base_url(api_version),
        "headers": _headers(),
        "auth": _api_key_auth(api_key),
        # SmartReach echoes the next page as a full URL in `links.next`, so it can't be trusted
        # blindly: a tampered response could point it at an arbitrary host and leak the API key.
        "paginator": JSONResponsePaginator(next_url_path="links.next"),
        # Pin every request — including paginator next-page and seeded resume URLs — to
        # SmartReach's own https origin. `allowed_hosts=[]` means "same host as base_url only",
        # and the base scheme/port are pinned too, so an off-origin or scheme-downgraded
        # (http://) `links.next` is rejected before the key goes out. `allow_redirects=False`
        # stops a redirect from bouncing the key off-origin.
        "allowed_hosts": [],
        "allow_redirects": False,
    }

    resume: Optional[SmartreachResumeConfig] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()

    if config.fanout is not None:
        parent_config = SMARTREACH_ENDPOINTS[config.fanout.parent_name]
        parent_endpoint_extra: Endpoint = {"data_selector": _data_selector(parent_config.data_key, api_version)}
        child_selector = _data_selector(config.data_key, api_version)
        # A child without a row list returns one object per parent and carries no `links`.
        child_endpoint_extra: Endpoint = (
            {"data_selector": child_selector} if child_selector else {"paginator": SinglePagePaginator()}
        )

        def save_fanout_checkpoint(state: Optional[dict[str, Any]]) -> None:
            if state:
                resumable_source_manager.save_state(SmartreachResumeConfig(fanout_state=state))

        child = cast(
            Resource,
            build_dependent_resource(
                endpoint_configs=SMARTREACH_ENDPOINTS,
                child_endpoint=endpoint,
                fanout=dataclasses.replace(config.fanout, parent_params=team_params, child_params=team_params),
                client_config=client_config,
                parent_endpoint_extra=parent_endpoint_extra,
                child_endpoint_extra=child_endpoint_extra,
                path_format_values={},
                page_size_param=None,
                team_id=team_id,
                job_id=job_id,
                db_incremental_field_last_value=db_incremental_field_last_value,
                resume_hook=save_fanout_checkpoint,
                initial_paginator_state=resume.fanout_state if resume else None,
            ),
        )
        row_map = _ROW_MAPS.get(endpoint)
        if row_map is not None:
            child.add_map(row_map)
        return _source_response(endpoint, config, child)

    endpoint_config: Endpoint = {
        "path": config.path,
        # A missing key yields an empty page (matching the previous behavior) rather than failing
        # loud, so data_selector_required is left off.
        "data_selector": _data_selector(config.data_key, api_version),
    }
    if team_params:
        endpoint_config["params"] = team_params

    rest_config: RESTAPIConfig = {
        "client": client_config,
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": endpoint_config,
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resume is not None and resume.next_url:
        initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes) rather than skipping it. No state is saved for the final page.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(SmartreachResumeConfig(next_url=state["next_url"]))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return _source_response(endpoint, config, resource)


def check_access(
    api_key: str,
    api_version: str,
    smartreach_team_id: str | None = None,
    endpoint: str = DEFAULT_PROBE_ENDPOINT,
) -> tuple[int, Optional[str]]:
    """Probe a single list endpoint to validate the user key.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    config = SMARTREACH_ENDPOINTS[endpoint]
    url = f"{_base_url(api_version)}{config.path}"
    # v3 list endpoints reject a request without team_id, so the probe must carry it too.
    if api_version == SMARTREACH_API_V3 and smartreach_team_id:
        url = f"{url}?{urlencode({'team_id': smartreach_team_id})}"
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,), allow_redirects=False),
        url,
        headers={"X-API-KEY": api_key, **_headers()},
    )
    if status is None:
        return 0, "Could not connect to SmartReach"
    if status in (401, 403):
        return status, None
    if ok:
        return status, None
    return status, f"SmartReach returned HTTP {status}"
