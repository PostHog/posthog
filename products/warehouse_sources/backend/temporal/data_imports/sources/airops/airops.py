from typing import Any, Optional

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.airops.settings import AIROPS_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe

AIROPS_BASE_URL = "https://api.airops.com"
APPS_PATH = "public_api/airops_apps"
# The executions endpoint caps `items` at 100.
EXECUTIONS_PAGE_SIZE = 100


class AirOpsCursorPaginator(JSONResponseCursorPaginator):
    """Cursor pagination over `meta.cursor`, honoring an explicit `has_more: false`.

    Pages while a cursor is present (a response with a cursor but no `has_more` flag must still
    page), but stops when `meta.has_more` is explicitly false even if a cursor is returned, so the
    final page isn't re-fetched.
    """

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if not self._has_next_page:
            return
        try:
            body = response.json()
        except Exception:
            return
        meta = body.get("meta") if isinstance(body, dict) else None
        if isinstance(meta, dict) and meta.get("has_more") is False:
            self._has_next_page = False


def _make_session(api_key: str) -> requests.Session:
    """Session for all AirOps traffic. The bearer token is registered for value-based redaction (so
    it can't leak into logged URLs or samples) and redirects are pinned off so a credentialed
    request can't be replayed against another host. Response capture is disabled because executions
    carry free-form `inputs`/`output` under arbitrary keys — a user can place credentials or other
    secrets there, and the name-based sample scrubbers can't reliably recognise them."""
    return make_tracked_session(
        headers={"Accept": "application/json"},
        redact_values=(api_key,),
        allow_redirects=False,
        capture=False,
    )


def _stamp_app_id(row: dict[str, Any]) -> dict[str, Any]:
    # Keep the legacy row shape: the parent app id is exposed as `airops_app_id` (part of the
    # composite primary key, so two apps' executions that share an id stay distinct rows) rather
    # than the framework's `_apps_id` parent-key name.
    row["airops_app_id"] = row.pop("_apps_id")
    return row


def airops_source(api_key: str, endpoint: str, team_id: int, job_id: str) -> SourceResponse:
    if endpoint not in AIROPS_ENDPOINTS:
        raise ValueError(f"Unknown AirOps endpoint: {endpoint}")
    endpoint_config = AIROPS_ENDPOINTS[endpoint]

    # The apps endpoint returns a plain (unwrapped) JSON array with no pagination. A non-list 200
    # body means the response shape changed — fail loud instead of silently syncing 0 rows.
    apps_resource: EndpointResource = {
        "name": "apps",
        "endpoint": {
            "path": APPS_PATH,
            "paginator": SinglePagePaginator(),
            "data_selector_required": True,
        },
    }

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": AIROPS_BASE_URL,
            # Auth goes through the framework so the Authorization header is built per request and
            # the token is redacted from tracked telemetry.
            "auth": {"type": "bearer", "token": api_key},
            "session": _make_session(api_key),
        },
        "resource_defaults": None,
        "resources": [],
    }

    if endpoint == "executions":
        # Executions can only be listed per app, so enumerate apps first and follow each app's
        # cursor-paginated executions endpoint, stamping every row with its parent app id.
        rest_config["resources"] = [
            apps_resource,
            {
                "name": "executions",
                "endpoint": {
                    "path": f"{APPS_PATH}/{{airops_app_id}}/executions",
                    # A parent app without an `id` fails loudly (in the framework's parent-field
                    # resolution) rather than silently dropping that app's executions.
                    "params": {
                        "airops_app_id": {"type": "resolve", "resource": "apps", "field": "id"},
                        "items": EXECUTIONS_PAGE_SIZE,
                    },
                    # A page without `data` is tolerated as a 0-row page; the cursor still advances.
                    "data_selector": "data",
                    "paginator": AirOpsCursorPaginator(cursor_path="meta.cursor", cursor_param="cursor"),
                },
                "include_from_parent": ["id"],
                "data_map": _stamp_app_id,
            },
        ]
        resources = rest_api_resources(rest_config, team_id, job_id, None)
        resource = next(r for r in resources if r.name == "executions")
    else:
        rest_config["resources"] = [apps_resource]
        resource = rest_api_resource(rest_config, team_id, job_id, None)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=endpoint_config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str) -> bool:
    """Cheapest probe that confirms the workspace API key is genuine: list apps and check for a 200."""
    ok, _status = validate_via_probe(
        lambda: _make_session(api_key),
        f"{AIROPS_BASE_URL}/{APPS_PATH}",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    return ok
