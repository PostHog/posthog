from typing import Any, Optional, cast
from urllib.parse import quote, urlparse

from requests import Response

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponsePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.vantage.settings import (
    VANTAGE_ENDPOINTS,
    VantageEndpointConfig,
)

VANTAGE_HOST = "api.vantage.sh"
VANTAGE_BASE_URL = f"https://{VANTAGE_HOST}/v2"


class VantageUntrustedURLError(Exception):
    pass


def _is_trusted_vantage_url(url: str) -> bool:
    # `links.next` (and any resumed cursor derived from it) is server-controlled data. Before we
    # attach the bearer token and fetch it, pin the URL to Vantage's own HTTPS host and `/v2/` API
    # path so a spoofed or compromised response can't redirect the credential to an
    # attacker-controlled origin.
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme == "https" and parsed.hostname == VANTAGE_HOST and parsed.path.startswith("/v2/")


class VantageTrustedJSONPaginator(JSONResponsePaginator):
    """Follows `links.next` in the response body, but refuses any next/resume URL that isn't on
    Vantage's own HTTPS host under the `/v2/` API path — the URL is server-controlled and must never
    be able to carry the bearer token off-origin. Rejection happens before the request is issued."""

    def __init__(self) -> None:
        super().__init__(next_url_path="links.next")

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if self._has_next_page:
            self._reject_if_untrusted(self._next_url)

    def set_resume_state(self, state: dict[str, Any]) -> None:
        self._reject_if_untrusted(state.get("next_url"))
        super().set_resume_state(state)

    @staticmethod
    def _reject_if_untrusted(url: Optional[str]) -> None:
        if url is not None and not _is_trusted_vantage_url(url):
            raise VantageUntrustedURLError(
                f"Refusing to fetch untrusted Vantage URL: host must be {VANTAGE_HOST} over HTTPS"
            )


@frozen
class VantageResumeConfig:
    # Full URL of the next page to fetch, taken verbatim from the response `links.next`. Vantage
    # encodes `page`/`limit` into it, so following it is enough to resume where we left off.
    next_url: str = ""
    # Fan-out endpoints: the framework's dependent-resource resume state
    # (`{"completed": [...], "current": ..., "child_state": ...}`).
    fanout_state: Optional[dict[str, Any]] = None


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def validate_credentials(api_key: str) -> bool:
    # `/ping` is the cheapest authenticated endpoint - it requires a valid read token and returns
    # 401 for a bad/expired one, without touching any cost data (so it can't trip the stricter
    # Cost Report rate limits).
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{VANTAGE_BASE_URL}/ping",
        headers=_get_headers(api_key),
    )
    return ok


def _add_tag_key_path(row: dict[str, Any]) -> dict[str, Any]:
    # The fan-out binds the path with `str.format`, which applies no escaping.
    row["tag_key_path"] = quote(row["tag_key"], safe="")
    return row


_PARENT_DATA_MAPS = {"tag_values": _add_tag_key_path}


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": VANTAGE_BASE_URL,
        # Auth (Bearer) goes through the framework auth config so the token is redacted from
        # logs and raised errors; only the non-secret Accept header is set here.
        "headers": {"Accept": "application/json"},
        "auth": {"type": "bearer", "token": api_key},
        "paginator": VantageTrustedJSONPaginator(),
        # `links.next` is server-controlled: pin every request to Vantage's own host and never
        # follow a redirect that could forward the bearer token off-host.
        "allowed_hosts": [],
        "allow_redirects": False,
    }


def _top_level_resource(
    config: VantageEndpointConfig,
    api_key: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[VantageResumeConfig],
) -> Resource:
    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resource_defaults": {},
        "resources": [
            {
                "name": config.name,
                "endpoint": {
                    "path": config.path,
                    # Cap page size on the first request; `links.next` carries limit/page thereafter.
                    "params": {"limit": config.page_size, **config.params},
                    # Rows nest under the endpoint's own key (e.g. "cost_reports"). A missing key on a
                    # 200 yields zero rows (matching the prior `data.get(key, [])`), not a hard error.
                    "data_selector": config.data_key,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_url:
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes) rather than skipping it.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(VantageResumeConfig(next_url=state["next_url"]))

    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value=None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def _fanout_resource(
    config: VantageEndpointConfig,
    api_key: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[VantageResumeConfig],
) -> Resource:
    assert config.fanout is not None
    parent_config = VANTAGE_ENDPOINTS[config.fanout.parent_name]

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.fanout_state:
            initial_paginator_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state is not None:
            resumable_source_manager.save_state(VantageResumeConfig(fanout_state=state))

    return cast(
        Resource,
        build_dependent_resource(
            endpoint_configs=VANTAGE_ENDPOINTS,
            child_endpoint=config.name,
            fanout=config.fanout,
            client_config=_client_config(api_key),
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            child_params_extra=config.params or None,
            parent_endpoint_extra={"data_selector": parent_config.data_key},
            child_endpoint_extra={
                "data_selector": config.data_key,
                # A path that ends in a placeholder (`/costs?cost_report_token={...}`) reads as a
                # single-entity path to the framework, which then fetches only one page.
                "paginator": VantageTrustedJSONPaginator(),
            },
            parent_data_map=_PARENT_DATA_MAPS.get(config.name),
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        ),
    )


def vantage_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[VantageResumeConfig],
) -> SourceResponse:
    config = VANTAGE_ENDPOINTS[endpoint]
    build_resource = _fanout_resource if config.fanout else _top_level_resource
    resource = build_resource(config, api_key, team_id, job_id, resumable_source_manager)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
