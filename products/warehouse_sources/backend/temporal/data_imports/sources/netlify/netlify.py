"""Netlify transport layer, built on the shared rest_source framework.

Netlify's REST API (https://open-api.netlify.com/) is a clean JSON surface behind a personal
access token sent as a Bearer header. Lists use 1-based `page`/`per_page` (max 100) pagination with
RFC-5988 `Link` headers (rel="next") for traversal — driven here by the framework's
`HeaderLinkPaginator`, subclassed to pin every next-page/resume URL to the Netlify host and scheme
(we attach the account token to every request, so following an off-host or scheme-downgraded link
would leak it; refuse instead).

No list endpoint accepts a server-side timestamp filter, so every table is full refresh — there is
no reliable server-side cursor to sync incrementally on. The source is still resumable: top-level
lists checkpoint the next page URL, and fan-out tables checkpoint the framework's per-parent fan-out
state so a resumed run skips already-completed parents and re-fans the in-progress one (merge dedupes
on the primary key).

Site-scoped tables (deploys, builds, forms, submissions) and account-scoped tables (members) are
fan-outs via the framework's dependent resources: the parent list seeds a child endpoint per parent,
injecting the parent identifier onto each child row so the composite primary key stays unique
table-wide.
"""

import dataclasses
from typing import Any, Optional
from urllib.parse import urlparse

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    rename_parent_fields,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    HeaderLinkPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.netlify.settings import (
    NETLIFY_ENDPOINTS,
    NetlifyEndpointConfig,
)

NETLIFY_BASE_URL = "https://api.netlify.com/api/v1"
_NETLIFY_PARSED_BASE = urlparse(NETLIFY_BASE_URL)


@dataclasses.dataclass
class NetlifyResumeConfig:
    # Next URL to fetch for a top-level list (HeaderLinkPaginator resume state). Kept as the first,
    # defaulted field so previously-persisted `{"next_url": ...}` state still parses.
    next_url: str | None = None
    # Framework fan-out resume state for site/account-scoped tables:
    # {"completed": [child_path, ...], "current": child_path | None, "child_state": {...} | None}.
    # Old saved state carried only `next_url`; on load, a missing `fanout_state` just re-fans fresh.
    fanout_state: dict[str, Any] | None = None


class NetlifyUntrustedURLError(Exception):
    """Raised when a next-page/resume URL points off the Netlify API host (or downgrades the scheme).
    We attach the account token to every request, so following such a URL would leak it; refuse."""


class NetlifyPageCapExceededError(Exception):
    """Raised when a fan-out parent exceeds the per-parent page cap. Failing loudly beats silently
    writing an incomplete full-refresh table that later runs would keep re-truncating."""


def _validate_netlify_url(url: str) -> str:
    """Reject a URL whose scheme or host differs from NETLIFY_BASE_URL.

    The next-page URL comes from a remote `Link` header (and from persisted resume state), and we
    send the account token with it. Pinning the scheme and host stops a tampered link from
    forwarding the token to an attacker-controlled server.
    """
    parsed = urlparse(url)
    if parsed.scheme != _NETLIFY_PARSED_BASE.scheme or parsed.netloc != _NETLIFY_PARSED_BASE.netloc:
        raise NetlifyUntrustedURLError(f"Netlify: refusing to follow off-host URL: {url}")
    return url


class NetlifyHeaderLinkPaginator(HeaderLinkPaginator):
    """`HeaderLinkPaginator` that pins every next-page/resume URL to the Netlify host and scheme, and
    stops on an empty page (a Netlify list signals its end with an empty body / no `next` link)."""

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        # An empty page is the end of a full-refresh list — stop before following any stale next link.
        if not data:
            self._has_next_page = False
            return
        super().update_state(response, data)
        if self._has_next_page and self._next_url is not None:
            _validate_netlify_url(self._next_url)

    def set_resume_state(self, state: dict[str, Any]) -> None:
        next_url = state.get("next_url")
        if next_url is not None:
            _validate_netlify_url(next_url)
        super().set_resume_state(state)


class NetlifyCappedHeaderLinkPaginator(NetlifyHeaderLinkPaginator):
    """Fan-out child paginator: bounds a single parent's pages, failing loudly on overrun rather than
    silently truncating the full-refresh table. Deep-copied per parent by `RESTClient.paginate`, so
    the page count resets for each parent."""

    def __init__(self, max_pages: int, context: Optional[dict[str, Any]] = None) -> None:
        super().__init__()
        self._max_pages = max_pages
        self._context = context or {}
        self._page_count = 0

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        self._page_count += 1
        if self._has_next_page and self._page_count >= self._max_pages:
            raise NetlifyPageCapExceededError(
                f"Netlify: per-parent page cap of {self._max_pages} reached with more pages remaining; "
                f"raise max_pages_per_parent to sync this parent fully. context={self._context}"
            )


def _non_secret_headers() -> dict[str, str]:
    # Auth (Bearer) is supplied via the framework auth config so its value is redacted from logs and
    # raised error messages; only the non-secret headers are set here.
    return {"Accept": "application/json", "User-Agent": "PostHog"}


def _redact_key(row: dict[str, Any], dotted_key: str) -> dict[str, Any]:
    """Return `row` with a possibly-nested field removed. `"password"` drops a top-level field;
    `"default_hooks_data.access_token"` walks into `default_hooks_data` and drops its `access_token`.
    Only the nodes on the path are copied, so the upstream item is left unmodified; a missing or
    non-dict node is a no-op."""
    head, _, rest = dotted_key.partition(".")
    if head not in row:
        return row
    if not rest:
        return {key: value for key, value in row.items() if key != head}
    nested = row[head]
    if not isinstance(nested, dict):
        return row
    return {**row, head: _redact_key(nested, rest)}


def _make_redactor(redact_keys: list[str]):
    """Per-row `data_map` that drops each configured (possibly-nested) credential field before the row
    is persisted, so account secrets in the API response never land in a queryable warehouse table."""

    def redact(row: dict[str, Any]) -> dict[str, Any]:
        for key in redact_keys:
            row = _redact_key(row, key)
        return row

    return redact


def _params_with_page_size(page_size: Optional[int], extra: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    params: dict[str, Any] = dict(extra or {})
    if page_size is not None:
        params["per_page"] = page_size
    return params


def _build_top_level_resource(
    api_token: str,
    config: NetlifyEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[NetlifyResumeConfig],
    db_incremental_field_last_value: Optional[Any],
) -> Resource:
    endpoint: dict[str, Any] = {
        "path": config.path,
        "params": _params_with_page_size(config.page_size),
        "paginator": NetlifyHeaderLinkPaginator(),
    }
    if config.redact_keys:
        endpoint_resource: dict[str, Any] = {"name": config.name, "endpoint": endpoint}
        endpoint_resource["data_map"] = _make_redactor(config.redact_keys)
    else:
        endpoint_resource = {"name": config.name, "endpoint": endpoint}

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": NETLIFY_BASE_URL,
            "headers": _non_secret_headers(),
            "auth": {"type": "bearer", "token": api_token},
        },
        "resources": [endpoint_resource],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_url:
            initial_paginator_state = {"next_url": _validate_netlify_url(resume.next_url)}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Save AFTER a page is yielded, only while a next page remains, so a crash re-yields the last
        # page (merge dedupes) rather than skipping it. The last page has no next link -> no save.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(NetlifyResumeConfig(next_url=state["next_url"]))

    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def _build_fan_out_resource(
    api_token: str,
    config: NetlifyEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[NetlifyResumeConfig],
    db_incremental_field_last_value: Optional[Any],
) -> Resource:
    assert config.fan_out_parent is not None and config.fan_out_path_param is not None
    parent_config = NETLIFY_ENDPOINTS[config.fan_out_parent]

    include_from_parent = list((config.fan_out_include_parent_fields or {}).keys())
    renames = dict(config.fan_out_include_parent_fields or {})

    parent_resource: dict[str, Any] = {
        "name": parent_config.name,
        "endpoint": {
            "path": parent_config.path,
            "params": _params_with_page_size(parent_config.page_size),
            "paginator": NetlifyHeaderLinkPaginator(),
        },
    }
    child_endpoint: dict[str, Any] = {
        "path": config.path,
        "params": _params_with_page_size(
            config.page_size,
            {
                config.fan_out_path_param: {
                    "type": "resolve",
                    "resource": parent_config.name,
                    "field": config.fan_out_parent_field,
                }
            },
        ),
        "paginator": NetlifyCappedHeaderLinkPaginator(config.max_pages_per_parent, context={"table": config.name}),
    }
    child_resource: dict[str, Any] = {
        "name": config.name,
        "endpoint": child_endpoint,
        "include_from_parent": include_from_parent,
        "data_map": rename_parent_fields(parent_config.name, renames),
    }

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": NETLIFY_BASE_URL,
            "headers": _non_secret_headers(),
            "auth": {"type": "bearer", "token": api_token},
        },
        "resources": [parent_resource, child_resource],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.fanout_state:
            initial_paginator_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # The framework's dependent-resource hook checkpoints its fan-out progress dict after each
        # parent's children are drained (and after each fully-completed parent). Persist it so a
        # resumed run skips completed parents and re-fans the in-progress one (merge dedupes).
        if state is not None:
            resumable_source_manager.save_state(NetlifyResumeConfig(fanout_state=state))

    resources = rest_api_resources(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    return next(resource for resource in resources if resource.name == config.name)


def netlify_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[NetlifyResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = NETLIFY_ENDPOINTS[endpoint]

    if config.fan_out_parent is not None:
        resource = _build_fan_out_resource(
            api_token, config, team_id, job_id, resumable_source_manager, db_incremental_field_last_value
        )
    else:
        resource = _build_top_level_resource(
            api_token, config, team_id, job_id, resumable_source_manager, db_incremental_field_last_value
        )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        sort_mode=config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(api_token: str) -> bool:
    """Probe the token with a cheap single-row /sites request. Netlify personal access tokens have
    full account access (no granular scopes), so one authenticated call confirms the whole token."""
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        f"{NETLIFY_BASE_URL}/sites?per_page=1",
        headers={"Authorization": f"Bearer {api_token}", **_non_secret_headers()},
    )
    return ok
