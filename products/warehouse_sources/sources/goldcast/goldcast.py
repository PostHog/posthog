from collections.abc import Callable
from typing import Any

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    rename_parent_fields,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ApiKeyAuthConfig,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.goldcast.settings import (
    GOLDCAST_ENDPOINTS,
    GoldcastEndpointConfig,
)

GOLDCAST_BASE_URL = "https://customapi.goldcast.io"

# Broadcast rows carry live-stream and translation-session credentials. They have no analytics
# value and would otherwise land in the warehouse in plain text.
_BROADCAST_SECRET_FIELDS = (
    "medialive_rtmp_input_details",
    "youtube_stream_key",
    "facebook_stream_key",
    "custom_stream_key",
    "external_rtmp_push_stream",
    "wordly_session_key",
)


def _headers() -> dict[str, str]:
    # Auth (the non-standard `Token` scheme) is supplied via the framework auth config so its value
    # is redacted from logs and errors; only the non-secret Accept header is set here.
    return {"Accept": "application/json"}


def _auth(access_key: str) -> ApiKeyAuthConfig:
    # Goldcast uses a static personal access token with the non-standard `Token` scheme (not
    # `Bearer`), created by an org admin in Studio Settings > Tokens. The whole `Token <key>` value
    # is the credential the framework redacts wherever it surfaces.
    return {"type": "api_key", "api_key": f"Token {access_key}", "name": "Authorization", "location": "header"}


def _require_id(parent_name: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    # `id` is the required fan-out key: a missing or falsy value must raise loudly rather than
    # silently under-syncing that parent's children with no signal in the logs.
    def _check(row: dict[str, Any]) -> dict[str, Any]:
        parent_id = row["id"]
        if not parent_id:
            raise ValueError(f"Goldcast {parent_name} row is missing a valid id")
        return row

    return _check


def _strip_broadcast_secrets(row: dict[str, Any]) -> dict[str, Any]:
    for key in _BROADCAST_SECRET_FIELDS:
        row.pop(key, None)
    return row


def _parent_resource(parent_name: str) -> EndpointResource:
    # The parent rows only drive the per-parent child requests; the parent schema itself is synced
    # by its own top-level resource.
    return {
        "name": parent_name,
        "endpoint": {
            "path": GOLDCAST_ENDPOINTS[parent_name].path,
            "paginator": SinglePagePaginator(),
        },
        "data_map": _require_id(parent_name),
    }


def _top_level_resource(config: GoldcastEndpointConfig) -> EndpointResource:
    # Collection endpoints return a bare JSON array; the organization endpoint returns a single
    # object, which the framework wraps as a one-row page. No data_selector, so a dict body is kept
    # as a single row exactly as the old normalization did.
    resource: EndpointResource = {
        "name": config.name,
        "endpoint": {
            "path": config.path,
            "paginator": SinglePagePaginator(),
        },
    }
    if config.name == "broadcasts":
        resource["data_map"] = _strip_broadcast_secrets
    return resource


def _fan_out_resource(config: GoldcastEndpointConfig, parent_name: str) -> EndpointResource:
    # One request per parent id. `{<parent_field>}` is bound from the parent's `id` — in the URL path
    # for most children, in a query string carried on the path template for `event_members`. The
    # parent id is injected into each child row under `parent_field` to form the composite primary
    # key (child ids are only unique per parent); for `event_members`, which already carries a
    # possibly stale `event`, this re-stamps it to the parent id.
    return {
        "name": config.name,
        "include_from_parent": ["id"],
        "endpoint": {
            "path": config.path,
            "params": {config.parent_field: {"type": "resolve", "resource": parent_name, "field": "id"}},
            "paginator": SinglePagePaginator(),
            # A parent with no child resources (or one deleted between enumeration and this fetch)
            # can 404. Skip it rather than failing the whole sync; any other error still raises.
            "response_actions": [{"status_code": 404, "action": "ignore"}],
        },
        "data_map": rename_parent_fields(parent_name, {"id": config.parent_field}),
    }


def _resources_for(endpoint: str) -> list[str | EndpointResource]:
    config = GOLDCAST_ENDPOINTS[endpoint]
    if config.fan_out_parent:
        return [_parent_resource(config.fan_out_parent), _fan_out_resource(config, config.fan_out_parent)]
    return [_top_level_resource(config)]


def goldcast_source(
    access_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
) -> SourceResponse:
    endpoint_config = GOLDCAST_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": GOLDCAST_BASE_URL,
            "headers": _headers(),
            "auth": _auth(access_key),
            "paginator": SinglePagePaginator(),
            # Broadcast and webinar bodies carry stream keys under field names the name-based sample
            # scrubber doesn't recognise, so keep all Goldcast bodies out of HTTP sample capture.
            "capture": False,
        },
        "resource_defaults": {},
        "resources": _resources_for(endpoint),
    }

    resources = rest_api_resources(rest_config, team_id, job_id, None)
    resource: Resource = next(r for r in resources if r.name == endpoint)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=endpoint_config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )


def validate_credentials(access_key: str) -> bool:
    # `/core/organization/` is the cheapest authenticated probe (a single org object). A 200 means
    # the token is genuine and API access is enabled for the account. `redact_values` masks the token
    # from any captured HTTP sample — it rides in the non-standard `Token` header name-based scrubbers
    # can't recognise.
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(access_key,)),
        f"{GOLDCAST_BASE_URL}/core/organization/",
        headers={"Authorization": f"Token {access_key}", **_headers()},
    )
    return ok
