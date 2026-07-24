import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

from requests import Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.bigmailer.settings import (
    BIGMAILER_ENDPOINTS,
    BigMailerEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe

BIGMAILER_BASE_URL = "https://api.bigmailer.io/v1"
# The API caps list responses at 100 objects per page; request the max to minimise round trips
# against the 10 req/s account rate limit.
PAGE_SIZE = 100

# Stable substring matched by BigMailerSource.get_non_retryable_errors to permanently fail the sync
# on a credential problem instead of retrying. Kept identical to the raised exception text.
AUTH_ERROR_MESSAGE = "BigMailer API key is invalid or lacks the required permissions"


class BigMailerAuthError(Exception):
    """Raised when the API rejects the key (HTTP 400 'Invalid api key', 401, or 403).

    An invalid or insufficiently-permissioned key can never be fixed by retrying, so this is
    surfaced as a non-retryable error rather than looping the sync.
    """


@dataclasses.dataclass
class BigMailerResumeConfig:
    # Cursor for the next page to fetch on a top-level (account-wide) endpoint. None starts a list
    # at its first page.
    cursor: str | None = None
    # Pre-framework brand bookmark. Kept (with a default) so previously saved state still parses;
    # no longer written — brand-scoped resume now lives in fanout_state.
    brand_id: str | None = None
    # Framework fan-out resume state for brand-scoped endpoints:
    # {"completed": [child_path, ...], "current": child_path | None, "child_state": {...} | None}.
    fanout_state: dict | None = None


class BigMailerCursorPaginator(JSONResponseCursorPaginator):
    """BigMailer always echoes a `cursor` in list bodies, even on the last page; only `has_more`
    signals that another page exists, so advancing is gated on it rather than on cursor presence."""

    def __init__(self) -> None:
        super().__init__(cursor_path="cursor", cursor_param="cursor")

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            body = response.json()
        except Exception:
            body = None
        next_cursor = body.get("cursor") if isinstance(body, dict) and body.get("has_more") else None
        if next_cursor:
            self._cursor_value = next_cursor
            self._has_next_page = True
        else:
            self._has_next_page = False


def _client_config(api_key: str) -> ClientConfig:
    # Framework auth (not a hand-built header) so the key is redacted from logged URLs/headers/samples.
    return {
        "base_url": BIGMAILER_BASE_URL,
        "headers": {"Accept": "application/json"},
        "auth": {"type": "api_key", "name": "X-API-Key", "api_key": api_key, "location": "header"},
        "paginator": BigMailerCursorPaginator(),
    }


def _raise_auth_errors(resource: Resource) -> Iterator[list[dict[str, Any]]]:
    """Convert HTTP credential failures into the stable non-retryable auth error.

    An invalid key returns 400 with `{"type": "invalid_request_error", "message": "Invalid api key"}`;
    insufficient permissions surface as 401/403. None of these are retryable. Any other HTTP error
    (e.g. a non-auth 400 or a 404) propagates unchanged so a transient request bug isn't misreported
    as a credential problem.
    """
    try:
        yield from resource
    except HTTPError as e:
        response = e.response
        if response is not None and (
            response.status_code in (401, 403) or (response.status_code == 400 and "api key" in response.text.lower())
        ):
            raise BigMailerAuthError(AUTH_ERROR_MESSAGE) from e
        raise


def _top_level_resource(
    api_key: str,
    config: BigMailerEndpointConfig,
    team_id: int,
    job_id: str,
    manager: ResumableSourceManager[BigMailerResumeConfig],
) -> Resource:
    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resources": [
            {
                "name": config.name,
                "endpoint": {
                    "path": config.path,
                    "params": {"limit": PAGE_SIZE},
                    "data_selector": "data",
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if manager.can_resume():
        resume = manager.load_state()
        if resume is not None and resume.cursor is not None:
            initial_paginator_state = {"cursor": resume.cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; the checkpoint is saved AFTER a page is yielded so a
        # crash re-fetches the in-flight page (the merge dedupes re-pulled rows) rather than skipping it.
        if state and state.get("cursor"):
            manager.save_state(BigMailerResumeConfig(cursor=str(state["cursor"])))

    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def _inject_brand_id(row: dict[str, Any]) -> dict[str, Any]:
    # include_from_parent lands the parent brand's id as `_brands_id`; rename it to the `brand_id`
    # column the composite ["brand_id", "id"] key expects. Child objects (lists, segments,
    # campaigns, …) don't carry their brand id in the response, so this keeps the key unique
    # across the whole table.
    if "_brands_id" in row:
        row["brand_id"] = row.pop("_brands_id")
    return row


def _brand_scoped_resource(
    api_key: str,
    config: BigMailerEndpointConfig,
    team_id: int,
    job_id: str,
    manager: ResumableSourceManager[BigMailerResumeConfig],
) -> Resource:
    """Fan out a brand-scoped endpoint over every brand via a dependent resource: the framework
    lists /brands and pages each brand's child list, injecting `brand_id` into every row."""
    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resources": [
            {
                "name": "brands",
                "endpoint": {
                    "path": "/brands",
                    "params": {"limit": PAGE_SIZE},
                    "data_selector": "data",
                },
            },
            {
                "name": config.name,
                "endpoint": {
                    "path": config.path,
                    "params": {
                        "limit": PAGE_SIZE,
                        "brand_id": {"type": "resolve", "resource": "brands", "field": "id"},
                    },
                    "data_selector": "data",
                },
                "include_from_parent": ["id"],
                "data_map": _inject_brand_id,
            },
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if manager.can_resume():
        resume = manager.load_state()
        # Only framework-shaped fan-out state is resumable. A pre-migration bookmark (cursor/brand_id)
        # can't be translated into the completed/current path map, so such a sync restarts fresh —
        # safe, because the merge dedupes re-pulled rows on the primary key.
        if resume is not None and resume.fanout_state is not None:
            initial_paginator_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state:
            manager.save_state(BigMailerResumeConfig(fanout_state=state))

    resources = rest_api_resources(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    return next(r for r in resources if r.name == config.name)


def bigmailer_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BigMailerResumeConfig],
) -> SourceResponse:
    config = BIGMAILER_ENDPOINTS[endpoint]

    if config.brand_scoped:
        resource = _brand_scoped_resource(api_key, config, team_id, job_id, resumable_source_manager)
    else:
        resource = _top_level_resource(api_key, config, team_id, job_id, resumable_source_manager)

    return SourceResponse(
        name=endpoint,
        items=lambda: _raise_auth_errors(resource),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[config.partition_key],
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str) -> bool:
    """Cheap probe that the key is genuine. /brands is account-wide and always reachable for a valid
    key, so a 200 confirms the credential without needing any specific brand or scope."""
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{BIGMAILER_BASE_URL}/brands?limit=1",
        headers={"X-API-Key": api_key, "Accept": "application/json"},
    )
    return ok
