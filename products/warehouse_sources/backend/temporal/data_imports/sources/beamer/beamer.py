import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.beamer.settings import (
    BEAMER_ENDPOINTS,
    BeamerEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    AuthConfig,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe

BEAMER_BASE_URL = "https://api.getbeamer.com/v0"
# Beamer's `page` query param is documented as paginating alongside `maxResults` but the docs don't
# state whether it's 0- or 1-based. We could not curl-verify against the live API without a paid key,
# so we assume the common convention (page 1 = first page). If a real key shows it's 0-based, change
# this constant — pagination termination ("a short page ends the loop") is index-independent.
FIRST_PAGE = 1


@dataclasses.dataclass
class BeamerResumeConfig:
    # Next page to fetch (1-based, see FIRST_PAGE). Used by the top-level (non-fan-out) endpoints.
    page: int = FIRST_PAGE
    # Legacy fan-out bookmark (id of the parent being processed). Kept only so previously saved
    # state still parses (`ResumableSourceManager._load_json` does `dataclass(**saved)`); the
    # framework fan-out now checkpoints into `fanout_state`, and an old-shape bookmark restarts
    # the fan-out from scratch (merge dedupes the re-pulled rows).
    parent_id: str | None = None
    # Framework fan-out checkpoint: {"completed": [child_path, ...], "current": child_path | None,
    # "child_state": {"page": N} | None}.
    fanout_state: dict | None = None


class BeamerPageNumberPaginator(PageNumberPaginator):
    """Page-number paginator that also stops on a short page.

    Beamer list endpoints expose no total count (header or body); a page with fewer than
    `maxResults` rows is the last one, so stopping there saves the extra empty-page request
    the base paginator would otherwise pay.
    """

    def __init__(self, limit: int) -> None:
        super().__init__(base_page=FIRST_PAGE)
        self.limit = limit

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if self._has_next_page and data is not None and len(data) < self.limit:
            self._has_next_page = False


def _auth_config(api_key: str) -> AuthConfig:
    # Framework auth (not a hand-built header) so the key is redacted from logs/captured samples.
    return {"type": "api_key", "api_key": api_key, "name": "Beamer-Api-Key", "location": "header"}


def _format_datetime(value: Any) -> str:
    """Format an incremental cursor value as the ISO-8601 `...Z` string Beamer's `dateFrom` expects."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    # A bad key 401s; a valid-but-unscoped key 403s (the 'Read posts' permission is optional). Both
    # mean the key is genuine, so only a 401 fails source-create — per-endpoint scope is surfaced
    # separately at sync time via `get_non_retryable_errors`. Transport failures and unexpected
    # statuses are inconclusive: reporting them as an invalid key would push users to needlessly
    # rotate a working credential (and re-enter it into a possibly-degraded environment), so they
    # get a generic retry message instead. `redact_values` masks the key from any captured sample.
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{BEAMER_BASE_URL}/posts?maxResults=1",
        headers={"Beamer-Api-Key": api_key, "Accept": "application/json"},
        ok_statuses=(200, 403),
    )
    if ok:
        return True, None
    if status == 401:
        return False, "Invalid Beamer API key"
    if status is None:
        return False, "Could not reach Beamer to validate the API key. Please try again."
    return False, f"Beamer could not validate the API key right now (status {status}). Please try again."


def _top_level_resource(
    config: BeamerEndpointConfig,
    api_key: str,
    team_id: int,
    job_id: str,
    manager: ResumableSourceManager[BeamerResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> Resource:
    params: dict[str, Any] = {"maxResults": config.max_results}
    if config.supports_incremental and should_use_incremental_field and db_incremental_field_last_value is not None:
        params["dateFrom"] = _format_datetime(db_incremental_field_last_value)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": BEAMER_BASE_URL,
            "headers": {"Accept": "application/json"},
            "auth": _auth_config(api_key),
            "paginator": BeamerPageNumberPaginator(limit=config.max_results),
        },
        "resources": [
            {
                "name": config.name,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    # Beamer list endpoints return a bare JSON array; a 200 with a non-list body
                    # means the response shape changed — fail loud instead of syncing 0 rows.
                    "data_selector_required": True,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if manager.can_resume():
        resume = manager.load_state()
        # Only a top-level checkpoint (no fan-out bookmark of either shape) seeds the paginator.
        if resume is not None and resume.parent_id is None and resume.fanout_state is None:
            initial_paginator_state = {"page": resume.page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; the hook fires AFTER a page is yielded, so a crash
        # re-fetches the last checkpointed page (merge dedupes) rather than skipping rows.
        if state and state.get("page") is not None:
            manager.save_state(BeamerResumeConfig(page=int(state["page"])))

    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def _fan_out_resource(
    config: BeamerEndpointConfig,
    parent_config: BeamerEndpointConfig,
    api_key: str,
    team_id: int,
    job_id: str,
    manager: ResumableSourceManager[BeamerResumeConfig],
) -> Resource:
    assert config.parent_key is not None  # set on every fan-out endpoint in settings.py
    parent_key = config.parent_key
    # include_from_parent injects the parent's id under `_{parent}_id`; rename it to the composite
    # primary-key column and str-cast so child rows keep the exact shape the hand-rolled source
    # produced (`{**item, parent_key: str(parent_id)}`).
    prefixed_parent_id = f"_{parent_config.name}_id"

    def _inject_parent_id(row: dict[str, Any]) -> dict[str, Any]:
        row[parent_key] = str(row.pop(prefixed_parent_id))
        return row

    parent_resource: EndpointResource = {
        "name": parent_config.name,
        "endpoint": {
            "path": parent_config.path,
            "params": {"maxResults": parent_config.max_results},
            "paginator": BeamerPageNumberPaginator(limit=parent_config.max_results),
            "data_selector_required": True,
        },
    }
    child_resource: EndpointResource = {
        "name": config.name,
        "include_from_parent": ["id"],
        "data_map": _inject_parent_id,
        "endpoint": {
            "path": config.path,
            "params": {
                "parent_id": {"type": "resolve", "resource": parent_config.name, "field": "id"},
                "maxResults": config.max_results,
            },
            "paginator": BeamerPageNumberPaginator(limit=config.max_results),
            "data_selector_required": True,
            # A parent deleted between enumeration and this fetch 404s. Skip it rather than failing
            # the whole sync — the children are genuinely gone. Any other HTTP error still raises.
            "response_actions": [{"status_code": 404, "action": "ignore"}],
        },
    }

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": BEAMER_BASE_URL,
            "headers": {"Accept": "application/json"},
            "auth": _auth_config(api_key),
        },
        "resources": [parent_resource, child_resource],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if manager.can_resume():
        resume = manager.load_state()
        # An old-shape bookmark (`parent_id`) can't seed the framework fan-out — start that part
        # fresh and let merge dedupe the re-pulled rows.
        if resume is not None and resume.fanout_state is not None:
            initial_paginator_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state is not None:
            manager.save_state(BeamerResumeConfig(fanout_state=state))

    resources = rest_api_resources(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    return next(resource for resource in resources if resource.name == config.name)


def beamer_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BeamerResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = BEAMER_ENDPOINTS[endpoint]

    if config.parent is not None:
        resource = _fan_out_resource(
            config, BEAMER_ENDPOINTS[config.parent], api_key, team_id, job_id, resumable_source_manager
        )
    else:
        resource = _top_level_resource(
            config,
            api_key,
            team_id,
            job_id,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Beamer doesn't document a sort param on these collections and we couldn't verify the default
        # order against the live API. For incremental endpoints we bound the low end with `dateFrom` and
        # use "desc" semantics so the watermark is only persisted at the end of a successful sync — a
        # mid-sync crash re-fetches from the unchanged watermark instead of skipping rows. Full-refresh
        # endpoints ignore sort_mode.
        sort_mode="desc" if config.supports_incremental else "asc",
    )
