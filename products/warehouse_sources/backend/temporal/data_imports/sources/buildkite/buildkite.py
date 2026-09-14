import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.buildkite.settings import (
    BUILDKITE_ENDPOINTS,
    BuildkiteEndpointConfig,
)
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
    HeaderLinkPaginator,
    JSONResponsePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

BUILDKITE_BASE_URL = "https://api.buildkite.com"
# Buildkite caps per_page at 100 (default 30).
PAGE_SIZE = 100

# Test Engine suites are the fan-out parent for both Test Engine child tables.
SUITE_CHILD_ENDPOINTS = ("test_suite_runs", "test_suite_tests")


@dataclasses.dataclass
class BuildkiteResumeConfig:
    # Next-page link for a flat list endpoint. None means "start at the first page".
    next_url: str | None = None
    # Framework fan-out snapshot ({"completed": [...], "current": ..., "child_state": ...}) for the
    # single-hop suites -> child fan-out.
    fanout_state: dict[str, Any] | None = None


def _format_incremental_value(value: Any) -> str:
    """Format an incremental cursor as ISO 8601, which Buildkite's *_from filters expect."""
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).isoformat()
    return str(value)


def _resolve_incremental_param(
    config: BuildkiteEndpointConfig,
    incremental_field: str | None,
) -> str | None:
    """Map the user-chosen incremental field to its server-side filter param, if supported."""
    if not config.incremental_param_map:
        return None
    field_name = incremental_field
    if field_name is None and config.incremental_fields:
        field_name = config.incremental_fields[0]["field"]
    if field_name is None:
        return None
    return config.incremental_param_map.get(field_name)


def _build_initial_params(
    config: BuildkiteEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"per_page": PAGE_SIZE}

    if should_use_incremental_field and db_incremental_field_last_value:
        param = _resolve_incremental_param(config, incremental_field)
        if param:
            params[param] = _format_incremental_value(db_incremental_field_last_value)

    return params


def _build_created_from(should_use_incremental_field: bool, db_incremental_field_last_value: Any) -> str | None:
    """Window the parent build walk that drives the jobs fan-out.

    Jobs have no time filter of their own, so the cursor a job row carries is its build's
    creation time and the window is applied to the builds listing that produced it.
    """
    if not should_use_incremental_field or not db_incremental_field_last_value:
        return None
    return _format_incremental_value(db_incremental_field_last_value)


def _client_config(api_access_token: str) -> ClientConfig:
    return {
        "base_url": BUILDKITE_BASE_URL,
        # Auth (Bearer) is supplied via the framework auth config so its value is redacted
        # from logs; only the non-secret Accept header is set here.
        "headers": {"Accept": "application/json"},
        "auth": {"type": "bearer", "token": api_access_token},
        # Buildkite paginates via an RFC 5988 Link header with rel="next".
        "paginator": HeaderLinkPaginator(),
    }


def _bind_organization(path: str, organization: str) -> str:
    # `str.format` would raise on the parent placeholders a fan-out child path still carries.
    return path.replace("{organization}", organization)


def _list_endpoint_resource(endpoint: str, organization: str, params: dict[str, Any]) -> EndpointResource:
    return {
        "name": endpoint,
        "endpoint": {
            "path": _bind_organization(BUILDKITE_ENDPOINTS[endpoint].path, organization),
            "params": params,
            # Buildkite list endpoints return a top-level JSON array; a non-list 200 body
            # means the response shape changed — fail loud instead of syncing garbage.
            "data_selector_required": True,
        },
    }


def _test_suites_resource(organization: str) -> EndpointResource:
    # The suites listing takes no page-size param — it returns the organization's whole suite list.
    return _list_endpoint_resource("test_suites", organization, {})


def _suite_child_resource(endpoint: str, organization: str) -> EndpointResource:
    return {
        "name": endpoint,
        # Runs and tests are only identified within their suite, so carry the suite into the key.
        "include_from_parent": ["id", "slug"],
        "endpoint": {
            "path": _bind_organization(BUILDKITE_ENDPOINTS[endpoint].path, organization),
            "params": {
                "suite_slug": {"type": "resolve", "resource": "test_suites", "field": "slug"},
                "per_page": PAGE_SIZE,
            },
            "data_selector_required": True,
            # A suite deleted between the listing and this fetch 404s; treat it as an empty page
            # and move to the next suite rather than failing the whole sync.
            "response_actions": [{"status_code": 404, "action": "ignore"}],
        },
        "data_map": rename_parent_fields("test_suites", {"id": "suite_id", "slug": "suite_slug"}),
    }


def _flatten_pipeline_slug(row: dict[str, Any]) -> dict[str, Any]:
    # The jobs path needs the pipeline slug, which a build nests under `pipeline`; flatten it so
    # both the path binding and include_from_parent can read it off the parent row.
    pipeline = row.get("pipeline")
    row["pipeline_slug"] = pipeline.get("slug") if isinstance(pipeline, dict) else None
    return row


def _builds_parent_resource(organization: str, created_from: str | None) -> EndpointResource:
    params: dict[str, Any] = {"per_page": PAGE_SIZE}
    if created_from is not None:
        params["created_from"] = created_from
    resource = _list_endpoint_resource("builds", organization, params)
    resource["data_map"] = _flatten_pipeline_slug
    return resource


def _jobs_child_resource(organization: str) -> EndpointResource:
    return {
        "name": "jobs",
        "include_from_parent": ["id", "number", "pipeline_slug", "created_at"],
        "endpoint": {
            "path": _bind_organization(BUILDKITE_ENDPOINTS["jobs"].path, organization),
            "params": {
                # Both path params bind fields of the same parent build row.
                "pipeline_slug": {"type": "resolve", "resource": "builds", "field": "pipeline_slug"},
                "build_number": {"type": "resolve", "resource": "builds", "field": "number"},
                "per_page": PAGE_SIZE,
            },
            # Unlike the other list endpoints, jobs answers with an envelope and paginates on a
            # cursor URL in the body rather than a Link header.
            "data_selector": "items",
            "data_selector_required": True,
            "paginator": JSONResponsePaginator(next_url_path="links.next"),
            "response_actions": [{"status_code": 404, "action": "ignore"}],
        },
        "data_map": rename_parent_fields(
            "builds",
            {
                "id": "build_id",
                "number": "build_number",
                "pipeline_slug": "pipeline_slug",
                "created_at": "build_created_at",
            },
        ),
    }


def _top_level_source(
    api_access_token: str,
    endpoint: str,
    organization: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BuildkiteResumeConfig],
    params: dict[str, Any],
    db_incremental_field_last_value: Optional[Any],
) -> Resource:
    rest_config: RESTAPIConfig = {
        "client": _client_config(api_access_token),
        "resources": [_list_endpoint_resource(endpoint, organization, params)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_url:
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; the hook fires AFTER a page is yielded so a crash
        # re-yields the last page (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(BuildkiteResumeConfig(next_url=state["next_url"]))

    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def _suite_fanout_source(
    api_access_token: str,
    endpoint: str,
    organization: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BuildkiteResumeConfig],
) -> Resource:
    """Drive a suites -> child single-hop fan-out with framework resume.

    The suite list is re-fetched each run; suites already fully synced are skipped by path and the
    one in progress resumes from its saved page anchor. A suite deleted between runs simply isn't
    in the re-fetched list.
    """
    rest_config: RESTAPIConfig = {
        "client": _client_config(api_access_token),
        "resources": [_test_suites_resource(organization), _suite_child_resource(endpoint, organization)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.fanout_state:
            initial_paginator_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state is not None:
            resumable_source_manager.save_state(BuildkiteResumeConfig(fanout_state=state))

    resources = rest_api_resources(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    return next(resource for resource in resources if getattr(resource, "name", None) == endpoint)


def _jobs_source(
    api_access_token: str,
    organization: str,
    team_id: int,
    job_id: str,
    created_from: str | None,
) -> Resource:
    """Fan out builds -> the jobs of each build.

    Resume is deliberately off here: the framework checkpoints a fan-out by writing the full set of
    completed child paths on every parent, which an organization's build list makes quadratic. A
    retry re-walks the window and merge dedupes on the job id.
    """
    rest_config: RESTAPIConfig = {
        "client": _client_config(api_access_token),
        "resources": [_builds_parent_resource(organization, created_from), _jobs_child_resource(organization)],
    }
    resources = rest_api_resources(rest_config, team_id, job_id, None)
    return next(resource for resource in resources if getattr(resource, "name", None) == "jobs")


def validate_credentials(
    api_access_token: str, organization: str, schema_name: str | None = None
) -> tuple[bool, str | None]:
    """Probe the Buildkite API to confirm the token is genuine and the org is reachable.

    At source-create (``schema_name`` is None) a 403 is accepted: the token is valid but may simply
    lack ``read_organizations`` while still holding the scopes for the endpoints the user wants to
    sync. When checking a specific schema, a 403 means the token can't read that resource, so it
    fails.
    """
    if schema_name and schema_name in BUILDKITE_ENDPOINTS:
        config = BUILDKITE_ENDPOINTS[schema_name]
        path = (config.probe_path or config.path).format(organization=organization)
        url = f"{BUILDKITE_BASE_URL}{path}?per_page=1"
    else:
        url = f"{BUILDKITE_BASE_URL}/v2/organizations/{organization}"

    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_access_token,)),
        url,
        headers={"Authorization": f"Bearer {api_access_token}", "Accept": "application/json"},
    )

    if ok:
        return True, None
    if status == 401:
        return False, "Invalid Buildkite API access token"
    if status == 403:
        if schema_name:
            return False, f"Your Buildkite API access token lacks the scope needed to read '{schema_name}'"
        return True, None
    if status == 404:
        return False, f"Organization '{organization}' not found or not accessible"
    if status is None:
        return False, "Could not connect to the Buildkite API"
    return False, f"Buildkite API returned an unexpected status: {status}"


def buildkite_source(
    api_access_token: str,
    organization: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BuildkiteResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = BUILDKITE_ENDPOINTS[endpoint]

    if endpoint in SUITE_CHILD_ENDPOINTS:
        resource = _suite_fanout_source(
            api_access_token, endpoint, organization, team_id, job_id, resumable_source_manager
        )
    elif endpoint == "jobs":
        resource = _jobs_source(
            api_access_token,
            organization,
            team_id,
            job_id,
            _build_created_from(should_use_incremental_field, db_incremental_field_last_value),
        )
    else:
        params = _build_initial_params(
            config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
        )
        resource = _top_level_source(
            api_access_token,
            endpoint,
            organization,
            team_id,
            job_id,
            resumable_source_manager,
            params,
            db_incremental_field_last_value,
        )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        sort_mode=config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
