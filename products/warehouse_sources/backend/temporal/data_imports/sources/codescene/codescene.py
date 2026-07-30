import re
import dataclasses
from collections.abc import Iterable
from typing import Any, Optional, cast
from urllib.parse import urlparse

from requests.exceptions import RequestException

from posthog.cloud_utils import is_cloud

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.codescene.settings import CODESCENE_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

REQUEST_TIMEOUT_SECONDS = 30

DEFAULT_BASE_URL = "https://api.codescene.io/v2"


@dataclasses.dataclass
class CodesceneResumeConfig:
    # 1-indexed next page to fetch. Only used for the flat (non-fan-out) "Projects"
    # endpoint — dependent (fan-out) resources don't currently support resume.
    next_page: Optional[int] = None


def normalize_base_url(base_url: str | None) -> str:
    """Turn whatever the user typed into a bare CodeScene API v2 base URL.

    Defaults to CodeScene Cloud. Accepts a bare host, a full URL, or a URL that already
    includes the `/api/v2` (on-prem) or `/v2` (cloud) suffix, and normalizes to just the
    scheme + host (+ port) + the versioned API path.
    """
    cleaned = (base_url or "").strip()
    if not cleaned:
        return DEFAULT_BASE_URL
    if "://" not in cleaned:
        cleaned = f"https://{cleaned}"
    cleaned = cleaned.rstrip("/")
    if cleaned.endswith("/api/v2") or cleaned.endswith("/v2"):
        return cleaned
    return f"{cleaned}/api/v2"


def hostname_of(base_url: str | None) -> str:
    return urlparse(normalize_base_url(base_url)).hostname or ""


# urlparse and requests disagree on ambiguous authorities: a backslash (raw or percent-encoded)
# reads as a path separator to requests but not to urlparse, and userinfo lets the visible host
# differ from the one actually dialed. Either lets a URL that looks safe to `_is_host_safe` connect
# somewhere else, so reject them before the host is derived.
_BACKSLASH = re.compile(r"\\|%5c", re.IGNORECASE)


def _validate_base_url(base_url: str | None) -> tuple[bool, str | None]:
    """Structurally validate a user-supplied CodeScene base URL before it derives a host or carries
    the API token. A blank value means CodeScene Cloud and is always allowed."""
    raw = (base_url or "").strip()
    if not raw:
        return True, None

    normalized = normalize_base_url(base_url)
    if _BACKSLASH.search(raw) or _BACKSLASH.search(normalized):
        return False, "The CodeScene API base URL can't contain backslashes."

    parsed = urlparse(normalized)
    if parsed.scheme not in ("http", "https"):
        return False, "The CodeScene API base URL must start with http:// or https://."
    if not parsed.hostname:
        return False, "The CodeScene API base URL must include a host."
    if parsed.username is not None or parsed.password is not None or "@" in parsed.netloc:
        return False, "The CodeScene API base URL can't include a username or password."
    if parsed.query or parsed.fragment:
        return False, "The CodeScene API base URL can't include a query string or fragment."
    # The token rides in the Authorization header, so on cloud it must never cross plaintext HTTP.
    # Self-hosted instances may reach an internal on-prem server over HTTP.
    if is_cloud() and parsed.scheme != "https":
        return False, "The CodeScene API base URL must use HTTPS."

    return True, None


def _check_base_url(base_url: str | None, team_id: int) -> tuple[bool, str | None]:
    """Full pre-request gate: structural validation followed by the SSRF host check. Run immediately
    before any credential-bearing request so an edited config or DNS change can't slip past."""
    structural_ok, structural_err = _validate_base_url(base_url)
    if not structural_ok:
        return False, structural_err
    return _is_host_safe(hostname_of(base_url), team_id)


def _headers(api_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_token}", "Accept": "application/json"}


def _client_config(base_url: str | None, api_token: str) -> ClientConfig:
    return {
        "base_url": normalize_base_url(base_url),
        "auth": {"type": "bearer", "token": api_token},
        "headers": {"Accept": "application/json"},
    }


def _page_paginator() -> PageNumberPaginator:
    # CodeScene's paginated list endpoints default to page 1 and report `max_pages` in the
    # response body so the last page can be detected without an extra empty-page request.
    return PageNumberPaginator(base_page=1, page=1, page_param="page", total_path="max_pages")


def validate_credentials(api_token: str, base_url: str | None, team_id: int) -> tuple[bool, str | None]:
    host_ok, host_err = _check_base_url(base_url, team_id)
    if not host_ok:
        return False, host_err

    url = f"{normalize_base_url(base_url)}/projects"
    try:
        response = make_tracked_session(redact_values=(api_token,)).get(
            url,
            headers=_headers(api_token),
            params={"page": 1, "page_size": 1},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except RequestException as exc:
        return False, str(exc)

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid CodeScene API token"
    if response.status_code == 403:
        return False, "CodeScene API token does not have the Admin, Architect, or RestApi role required by the API"
    return False, f"Could not connect to CodeScene (HTTP {response.status_code})"


def _get_resource(endpoint: str) -> EndpointResource:
    config = CODESCENE_ENDPOINTS[endpoint]
    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": "replace",
        "endpoint": {
            "path": config.path,
            "params": {"page_size": config.page_size},
            "data_selector": config.data_selector,
            # The wrapper key is documented, so a response without it means the API shape
            # changed — fail loud rather than silently syncing 0 rows.
            "data_selector_required": True,
            "paginator": _page_paginator(),
        },
        "table_format": "delta",
    }


def _primary_keys(endpoint: str) -> list[str]:
    primary_key = CODESCENE_ENDPOINTS[endpoint].primary_key
    return primary_key if isinstance(primary_key, list) else [primary_key]


def codescene_source(
    api_token: str,
    base_url: str | None,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CodesceneResumeConfig],
) -> SourceResponse:
    # Re-check right before issuing requests: validate_credentials ran when the source was first
    # configured, but the config can be edited afterwards and DNS can change, so the SSRF/plaintext
    # guard must hold at sync time too.
    base_url_ok, base_url_err = _check_base_url(base_url, team_id)
    if not base_url_ok:
        raise ValueError(base_url_err)

    endpoint_config = CODESCENE_ENDPOINTS[endpoint]
    client_config = _client_config(base_url, api_token)

    if endpoint_config.fanout:
        parent_config = CODESCENE_ENDPOINTS[endpoint_config.fanout.parent_name]
        # Fan-out resources don't currently support resume in the shared framework — the
        # (usually small) list of projects is re-fetched each run and files/components are
        # replaced wholesale, so no resumable_source_manager state is threaded through here.
        resource = cast(
            Iterable[Any],
            build_dependent_resource(
                endpoint_configs=CODESCENE_ENDPOINTS,
                child_endpoint=endpoint,
                fanout=endpoint_config.fanout,
                client_config=client_config,
                path_format_values={},
                team_id=team_id,
                job_id=job_id,
                db_incremental_field_last_value=None,
                page_size_param="page_size",
                parent_endpoint_extra={
                    "data_selector": parent_config.data_selector,
                    "data_selector_required": True,
                    "paginator": _page_paginator(),
                },
                child_endpoint_extra={
                    "data_selector": endpoint_config.data_selector,
                    "data_selector_required": True,
                    "paginator": _page_paginator(),
                },
            ),
        )
        return SourceResponse(
            name=endpoint_config.name,
            items=lambda: resource,
            primary_keys=_primary_keys(endpoint),
        )

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None and resume_config.next_page is not None:
            initial_paginator_state = {"page": resume_config.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(CodesceneResumeConfig(next_page=int(state["page"])))

    config: RESTAPIConfig = {
        "client": client_config,
        "resource_defaults": {},
        "resources": [_get_resource(endpoint)],
    }

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    return SourceResponse(
        name=endpoint_config.name,
        items=lambda: resource,
        primary_keys=_primary_keys(endpoint),
    )
