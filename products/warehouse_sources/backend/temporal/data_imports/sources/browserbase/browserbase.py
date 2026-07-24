import requests

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.browserbase.settings import BROWSERBASE_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe

BROWSERBASE_BASE_URL = "https://api.browserbase.com/v1"


def _make_session(api_key: str) -> requests.Session:
    # `redact_values` masks the key in tracked logs/samples. `capture=False` keeps response bodies out
    # of HTTP sample storage — session objects carry arbitrary `userMetadata` (and projects can carry
    # other customer-defined fields) that the name-based sample scrubbers can't recognise. Requests
    # are still metered and logged (status + url).
    return make_tracked_session(redact_values=(api_key,), capture=False)


def validate_credentials(api_key: str) -> bool:
    # `/projects` is the cheapest authenticated probe: a project-scoped key can always list at least
    # its own project, so a 200 confirms the key is genuine without needing any session data.
    ok, _status = validate_via_probe(
        lambda: _make_session(api_key),
        f"{BROWSERBASE_BASE_URL}/projects",
        headers={"X-BB-API-Key": api_key, "Accept": "application/json"},
    )
    return ok


def browserbase_source(api_key: str, endpoint: str, team_id: int, job_id: str) -> SourceResponse:
    endpoint_config = BROWSERBASE_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": BROWSERBASE_BASE_URL,
            "headers": {"Accept": "application/json"},
            # Framework auth (not a hand-built header) so the key is redacted wherever it surfaces.
            "auth": {"type": "api_key", "name": "X-BB-API-Key", "api_key": api_key, "location": "header"},
            # Browserbase list endpoints return a plain JSON array with no pagination, page, or cursor
            # params, so a single request yields the whole collection.
            "paginator": "single_page",
            "session": _make_session(api_key),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": endpoint_config.path,
                    # The whole body is the row list; a non-list success body is an unexpected/error
                    # shape. Fail loud instead of finishing "successfully" with zero rows.
                    "data_selector_required": True,
                },
            }
        ],
    }

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
    )
