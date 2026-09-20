import re
import base64
import dataclasses
from collections.abc import Iterable
from typing import Any, Optional

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    JSONResponsePaginator,
    OffsetPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.confluence.settings import (
    CONFLUENCE_ENDPOINTS,
    ConfluenceEndpointConfig,
)

# Confluence Cloud sites always live under <subdomain>.atlassian.net. Building
# the host ourselves from a validated subdomain (rather than accepting an
# arbitrary host) keeps the API token from being sent anywhere off-Atlassian.
_SUBDOMAIN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,62}$")


@dataclasses.dataclass
class ConfluenceResumeConfig:
    # Flat listings resume from the next page URL (v2) or the next offset (v1).
    next_url: Optional[str] = None
    offset: Optional[int] = None
    # Fan-out endpoints resume from the shape `build_dependent_resource` checkpoints: which
    # parents finished and where the current one stopped.
    fanout_state: Optional[dict[str, Any]] = None


def _site_origin(subdomain: str) -> str:
    return f"https://{subdomain}.atlassian.net"


def is_valid_subdomain(subdomain: str) -> bool:
    return bool(subdomain) and _SUBDOMAIN_RE.match(subdomain) is not None


def _get_headers(email: str, api_token: str) -> dict[str, str]:
    token = base64.b64encode(f"{email}:{api_token}".encode()).decode()
    return {
        "Authorization": f"Basic {token}",
        "Accept": "application/json",
    }


class ConfluenceLinkPaginator(JSONResponsePaginator):
    """Confluence v2 returns the next page as a site-relative path in ``_links.next``
    (e.g. ``/wiki/api/v2/pages?cursor=...``); resolve it against the site origin so the
    client requests an absolute URL. Absence of the key signals the last page."""

    def __init__(self, site_origin: str) -> None:
        super().__init__(next_url_path="_links.next")
        self._site_origin = site_origin

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if self._has_next_page and self._next_url and not self._next_url.startswith(("http://", "https://")):
            self._next_url = f"{self._site_origin}{self._next_url}"


class ConfluenceOffsetPaginator(OffsetPaginator):
    """Confluence v1 collections page with ``start``/``limit``.

    The site can cap ``limit`` below what we ask for, so advance by — and stop on — the window
    the response echoes back rather than the one we requested. Comparing against our own limit
    would make the first capped page look like the last one and silently truncate the table.
    """

    def __init__(self, limit: int) -> None:
        super().__init__(limit=limit, offset_param="start", total_path=None)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            body = response.json()
        except Exception:
            body = None

        if isinstance(body, dict):
            size, echoed_limit = body.get("size"), body.get("limit")
            if isinstance(size, int) and isinstance(echoed_limit, int) and echoed_limit > 0:
                self.offset += size
                self._has_next_page = size >= echoed_limit
                return

        super().update_state(response, data)


def _paginator(config: ConfluenceEndpointConfig, site_origin: str) -> BasePaginator:
    if config.single_object:
        return SinglePagePaginator()
    if config.api == "v1":
        return ConfluenceOffsetPaginator(config.page_size)
    return ConfluenceLinkPaginator(site_origin)


def _client_config(subdomain: str, email: str, api_token: str, config: ConfluenceEndpointConfig) -> ClientConfig:
    # A fan-out's client paginates the parent listing; a child that pages differently gets its
    # own paginator on the child endpoint below.
    paginated_by = CONFLUENCE_ENDPOINTS[config.fanout.parent_name] if config.fanout else config
    return {
        "base_url": _site_origin(subdomain),
        # Auth (HTTP Basic) is supplied via the framework auth config so the token is
        # redacted from logs; only the non-secret Accept header is set here.
        "headers": {"Accept": "application/json"},
        "auth": {"type": "http_basic", "username": email, "password": api_token},
        "paginator": _paginator(paginated_by, _site_origin(subdomain)),
    }


def _endpoint_params(config: ConfluenceEndpointConfig) -> dict[str, Any]:
    params: dict[str, Any] = dict(config.params)
    # v1 endpoints take their page size from the paginator, which injects `start` and `limit`.
    if config.api == "v2":
        params["limit"] = config.page_size
    return params


def _initial_paginator_state(
    config: ConfluenceEndpointConfig, resume: Optional[ConfluenceResumeConfig]
) -> Optional[dict[str, Any]]:
    if resume is None:
        return None
    if config.fanout is not None:
        return resume.fanout_state
    if config.api == "v1":
        return {"offset": resume.offset} if resume.offset is not None else None
    return {"next_url": resume.next_url} if resume.next_url else None


def _save_checkpoint(
    config: ConfluenceEndpointConfig,
    manager: ResumableSourceManager[ConfluenceResumeConfig],
    state: Optional[dict[str, Any]],
) -> None:
    # Persist only when a next page remains; save AFTER a page is yielded so a crash re-fetches
    # the page we just emitted (merge dedupes on primary key) rather than skipping it.
    if not state:
        return
    if config.fanout is not None:
        manager.save_state(ConfluenceResumeConfig(fanout_state=state))
    elif config.api == "v1":
        if state.get("offset") is not None:
            manager.save_state(ConfluenceResumeConfig(offset=int(state["offset"])))
    elif state.get("next_url"):
        manager.save_state(ConfluenceResumeConfig(next_url=str(state["next_url"])))


def confluence_source(
    subdomain: str,
    email: str,
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ConfluenceResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = CONFLUENCE_ENDPOINTS[endpoint]
    client_config = _client_config(subdomain, email, api_token, config)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    initial_paginator_state = _initial_paginator_state(config, resume)

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        _save_checkpoint(config, resumable_source_manager, state)

    column_hints: Optional[dict[str, Any]] = None
    items: Iterable[Any]

    if config.fanout is not None:
        parent_config = CONFLUENCE_ENDPOINTS[config.fanout.parent_name]
        child_endpoint_extra: Endpoint = {}
        if config.single_object:
            child_endpoint_extra["paginator"] = SinglePagePaginator()
        if config.data_selector is not None:
            child_endpoint_extra["data_selector"] = config.data_selector

        items = build_dependent_resource(
            endpoint_configs=CONFLUENCE_ENDPOINTS,
            child_endpoint=endpoint,
            fanout=config.fanout,
            client_config=client_config,
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=db_incremental_field_last_value,
            parent_endpoint_extra={"data_selector": parent_config.data_selector},
            child_endpoint_extra=child_endpoint_extra or None,
            # The v1 analytics children take no page-size param, and the v1 paginator injects
            # its own `limit`, so only a v2 fan-out sizes its pages through this.
            page_size_param="limit" if config.api == "v2" else None,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        )
    else:
        endpoint_config: Endpoint = {
            "path": config.path,
            "params": _endpoint_params(config),
        }
        if config.data_selector is not None:
            # List endpoints wrap rows in `results`; a missing key means an empty page.
            endpoint_config["data_selector"] = config.data_selector

        rest_config: RESTAPIConfig = {
            "client": client_config,
            "resources": [
                {
                    "name": endpoint,
                    "endpoint": endpoint_config,
                }
            ],
        }

        resource = rest_api_resource(
            rest_config,
            team_id,
            job_id,
            db_incremental_field_last_value,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        )
        items = resource
        column_hints = resource.column_hints

    return SourceResponse(
        name=endpoint,
        items=lambda: items,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=column_hints,
    )


def validate_credentials(
    subdomain: str, email: str, api_token: str, schema_name: str | None = None
) -> tuple[bool, str | None]:
    """Probe the Confluence API to confirm the credentials are genuine.

    A 403 at source-create (``schema_name is None``) is accepted: the token may
    be valid but lack access to the probed resource. Once a specific schema is
    being validated we surface the 403.
    """
    if not is_valid_subdomain(subdomain):
        return (
            False,
            "Invalid Confluence subdomain. Use just the site name, e.g. 'your-domain' for your-domain.atlassian.net.",
        )

    url = f"{_site_origin(subdomain)}{CONFLUENCE_ENDPOINTS['spaces'].path}?limit=1"
    _ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        url,
        headers=_get_headers(email, api_token),
    )

    if status == 200:
        return True, None
    if status == 401:
        return False, "Invalid Confluence credentials. Check your email and API token."
    if status == 403:
        if schema_name is None:
            return True, None
        return False, "Your Confluence account does not have permission to access this resource."
    if status is None:
        return False, None

    return False, f"Confluence API returned status {status}."
