import dataclasses
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode

import requests

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.bitrise.settings import BITRISE_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    ClientConfig,
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    rename_parent_fields,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

BITRISE_BASE_URL = "https://api.bitrise.io/v0.1"
# Bitrise list endpoints cap `limit` at 50.
PAGE_LIMIT = 50
# Safety overlap subtracted from the incremental watermark: builds that were still running (or on
# hold) at the last sync keep mutating (status, finished_at) after their trigger time, so each run
# re-pulls a trailing window and merge dedupes the re-fetched rows on the primary key.
INCREMENTAL_LOOKBACK = timedelta(hours=24)


@dataclasses.dataclass
class BitriseResumeConfig:
    # Fan-out bookmark: retained only so pre-migration saved state still parses via
    # `dataclass(**saved)`. New runs never populate it; fan-out resume now lives in `fanout_state`.
    app_slug: str | None = None
    # `next` paging anchor for the flat apps listing. None means "start at the first page".
    next: str | None = None
    # Framework fan-out resume snapshot ({"completed": [...], "current": ..., "child_state": ...})
    # for the single-hop parent-app -> child-endpoint dependent resources (builds, workflows).
    fanout_state: dict[str, Any] | None = None


def _get_session(api_token: str) -> requests.Session:
    # Bitrise expects the raw token in the Authorization header (no Bearer prefix).
    return make_tracked_session(headers={"Authorization": api_token}, redact_values=(api_token,))


def _to_unix_timestamp(value: Any) -> int | None:
    """Convert an incremental cursor to the Unix timestamp Bitrise's `after` filter expects."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return int(dt.timestamp())
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp())
    if isinstance(value, int | float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
        except ValueError:
            return None
    return None


def _build_after_param(should_use_incremental_field: bool, db_incremental_field_last_value: Any) -> int | None:
    if not should_use_incremental_field or db_incremental_field_last_value is None:
        return None
    timestamp = _to_unix_timestamp(db_incremental_field_last_value)
    if timestamp is None:
        return None
    return max(0, timestamp - int(INCREMENTAL_LOOKBACK.total_seconds()))


def validate_credentials(api_token: str) -> bool:
    """Confirm the token is genuine with a cheap probe.

    Personal access tokens can call /me; workspace API tokens are workspace-scoped and may not,
    so fall back to a one-app listing before declaring the token invalid.
    """
    session = _get_session(api_token)
    try:
        response = session.get(f"{BITRISE_BASE_URL}/me", timeout=10)
        if response.status_code == 200:
            return True
        response = session.get(f"{BITRISE_BASE_URL}/apps?{urlencode({'limit': 1})}", timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def _client_config(api_token: str) -> ClientConfig:
    # Framework auth carries the raw token on the Authorization header (api_key, header, no prefix)
    # and redacts its value out of any raised error message and captured sample.
    return {
        "base_url": BITRISE_BASE_URL,
        "auth": {"type": "api_key", "api_key": api_token, "name": "Authorization", "location": "header"},
    }


def _cursor_paginator() -> JSONResponseCursorPaginator:
    # Bitrise signals more pages with a `paging.next` anchor passed back as `?next=`; absent on the
    # final page.
    return JSONResponseCursorPaginator(cursor_path="paging.next", cursor_param="next")


def _apps_resource() -> EndpointResource:
    return {
        "name": "apps",
        "endpoint": {
            "path": "/apps",
            "params": {"limit": PAGE_LIMIT},
            "data_selector": "data",
            "paginator": _cursor_paginator(),
        },
    }


def _builds_child_params(after: int | None) -> dict[str, Any]:
    params: dict[str, Any] = {
        "app_slug": {"type": "resolve", "resource": "apps", "field": "slug"},
        "limit": PAGE_LIMIT,
        "sort_by": "created_at",
    }
    if after is not None:
        params["after"] = after
    return params


def _apps_source(
    api_token: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BitriseResumeConfig],
) -> Resource:
    rest_config: RESTAPIConfig = {
        "client": _client_config(api_token),
        "resources": [_apps_resource()],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next:
            initial_paginator_state = {"cursor": resume.next}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes) rather than skipping it.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(BitriseResumeConfig(next=state["cursor"]))

    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def _single_hop_fanout_source(
    api_token: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BitriseResumeConfig],
    child_resource: EndpointResource,
) -> Resource:
    """Drive an apps -> child single-hop fan-out with framework resume.

    The parent app list is re-fetched each run; already-completed apps are skipped and the app in
    progress resumes from its saved page anchor. A stale bookmark (app deleted between runs) simply
    isn't in the re-fetched list, so the fan-out restarts from the remaining apps and merge dedupes.
    """
    rest_config: RESTAPIConfig = {
        "client": _client_config(api_token),
        "resources": [_apps_resource(), child_resource],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        # Only a framework-shaped fan-out snapshot can be resumed; a pre-migration app bookmark can't
        # be reconstructed here, so restart the fan-out.
        if resume is not None and resume.fanout_state:
            initial_paginator_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state is not None:
            resumable_source_manager.save_state(BitriseResumeConfig(fanout_state=state))

    resources = rest_api_resources(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    child_name = child_resource["name"]
    return next(resource for resource in resources if getattr(resource, "name", None) == child_name)


def _builds_source(
    api_token: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BitriseResumeConfig],
    after: int | None,
) -> Resource:
    child_resource: EndpointResource = {
        "name": "builds",
        # Inject the parent app slug into each build row under its historical `app_slug` column.
        "include_from_parent": ["slug"],
        "endpoint": {
            "path": "/apps/{app_slug}/builds",
            "params": _builds_child_params(after),
            "data_selector": "data",
            "paginator": _cursor_paginator(),
            # An app deleted between enumeration and this fetch 404s; treat it as an empty page and
            # stop this app rather than failing the whole sync.
            "response_actions": [{"status_code": 404, "action": "ignore"}],
        },
        "data_map": rename_parent_fields("apps", {"slug": "app_slug"}),
    }
    return _single_hop_fanout_source(api_token, team_id, job_id, resumable_source_manager, child_resource)


def _workflows_explode(row: dict[str, Any]) -> list[dict[str, Any]]:
    # build-workflows returns bare workflow-name strings under `data`; explode them into one row per
    # workflow, carrying the injected parent app slug.
    app_slug = row.get("_apps_slug")
    return [{"app_slug": app_slug, "workflow": name} for name in row.get("data") or []]


def _workflows_source(
    api_token: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BitriseResumeConfig],
) -> Resource:
    child_resource: EndpointResource = {
        "name": "workflows",
        "include_from_parent": ["slug"],
        "endpoint": {
            "path": "/apps/{app_slug}/build-workflows",
            "params": {"app_slug": {"type": "resolve", "resource": "apps", "field": "slug"}},
            # No data_selector: the whole `{"data": [...]}` body is yielded as one row, then the
            # data_map explodes it into one row per bare workflow name.
            "paginator": SinglePagePaginator(),
            "response_actions": [{"status_code": 404, "action": "ignore"}],
        },
        "data_map": _workflows_explode,
    }
    return _single_hop_fanout_source(api_token, team_id, job_id, resumable_source_manager, child_resource)


def _artifacts_source(
    api_token: str,
    team_id: int,
    job_id: str,
    after: int | None,
) -> Resource:
    """Two-level fan-out: apps -> builds -> per-build artifact listings.

    The incremental filter applies at the parent builds level (`after` on trigger time), and each
    artifact row carries `build_triggered_at` (plus `app_slug`/`build_slug`) so the pipeline can
    watermark on it. With two dependent resources the framework disables resume; retries re-fetch and
    merge dedupes on the primary key.
    """
    builds_resource: EndpointResource = {
        "name": "builds",
        "include_from_parent": ["slug"],
        "endpoint": {
            "path": "/apps/{app_slug}/builds",
            "params": _builds_child_params(after),
            "data_selector": "data",
            "paginator": _cursor_paginator(),
            "response_actions": [{"status_code": 404, "action": "ignore"}],
        },
        "data_map": rename_parent_fields("apps", {"slug": "app_slug"}),
    }
    artifacts_resource: EndpointResource = {
        "name": "artifacts",
        "include_from_parent": ["app_slug", "slug", "triggered_at"],
        "endpoint": {
            "path": "/apps/{app_slug}/builds/{build_slug}/artifacts",
            "params": {
                "app_slug": {"type": "resolve", "resource": "builds", "field": "app_slug"},
                "build_slug": {"type": "resolve", "resource": "builds", "field": "slug"},
                "limit": PAGE_LIMIT,
            },
            "data_selector": "data",
            "paginator": _cursor_paginator(),
            "response_actions": [{"status_code": 404, "action": "ignore"}],
        },
        "data_map": rename_parent_fields(
            "builds", {"app_slug": "app_slug", "slug": "build_slug", "triggered_at": "build_triggered_at"}
        ),
    }

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_token),
        "resources": [_apps_resource(), builds_resource, artifacts_resource],
    }
    resources = rest_api_resources(rest_config, team_id, job_id, None)
    return next(resource for resource in resources if getattr(resource, "name", None) == "artifacts")


def bitrise_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BitriseResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    after = _build_after_param(should_use_incremental_field, db_incremental_field_last_value)

    if endpoint == "apps":
        resource = _apps_source(api_token, team_id, job_id, resumable_source_manager)
    elif endpoint == "builds":
        resource = _builds_source(api_token, team_id, job_id, resumable_source_manager, after)
    elif endpoint == "workflows":
        resource = _workflows_source(api_token, team_id, job_id, resumable_source_manager)
    elif endpoint == "artifacts":
        resource = _artifacts_source(api_token, team_id, job_id, after)
    else:
        raise ValueError(f"Unknown Bitrise endpoint: {endpoint}")

    endpoint_config = BITRISE_ENDPOINTS[endpoint]
    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=endpoint_config.primary_keys,
        # Bitrise returns builds newest-first and the fan-out walks app by app, so rows never arrive
        # in ascending timestamp order. desc mode persists the incremental watermark only at
        # successful job end, which is the only safe point for a fan-out stream.
        sort_mode="desc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
