import re
from typing import Any

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.campayn.settings import CAMPAYN_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ApiKeyAuthConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe

CAMPAYN_API_PATH = "/api/v1"
# Per-account host: requests go to {subdomain}.campayn.com. The label is validated against this
# pattern at source-create so a pasted URL or injection can't retarget the credential elsewhere.
_SUBDOMAIN_PATTERN = re.compile(r"^[a-zA-Z0-9-]+$")


def normalize_subdomain(subdomain: str) -> str:
    """Reduce whatever the user entered to the bare Campayn subdomain label.

    Users frequently paste the full host ("acme.campayn.com") or a URL
    ("https://acme.campayn.com/") into the subdomain field. Collapse those to the
    bare label so the base URL doesn't become "https://acme.campayn.com.campayn.com/".
    """
    subdomain = subdomain.strip()
    if "://" in subdomain:
        subdomain = subdomain.split("://", 1)[1]
    # Drop any path/query left over from a pasted URL.
    subdomain = subdomain.split("/", 1)[0]
    # Strip a trailing ".campayn.com" so a full host collapses to the subdomain label.
    return re.sub(r"\.campayn\.com$", "", subdomain, flags=re.IGNORECASE)


def is_subdomain_valid(subdomain: str) -> bool:
    return bool(_SUBDOMAIN_PATTERN.match(normalize_subdomain(subdomain)))


def base_url(subdomain: str) -> str:
    return f"https://{normalize_subdomain(subdomain)}.campayn.com{CAMPAYN_API_PATH}"


def _auth_config(api_key: str) -> ApiKeyAuthConfig:
    # Campayn's custom auth scheme: "Authorization: TRUEREST apikey={key}". Sent through the
    # framework's api_key auth so the whole credential-bearing value is registered for value-based
    # redaction in tracked HTTP logs — the custom scheme isn't recognised by name-based scrubbers.
    return {
        "type": "api_key",
        "name": "Authorization",
        "api_key": f"TRUEREST apikey={api_key}",
        "location": "header",
    }


def _stamp_list_id(row: dict[str, Any]) -> dict[str, Any]:
    # Keep the legacy row shape: the parent list id is exposed as a string `list_id` column (part
    # of the composite primary key, so the same contact under multiple lists stays a distinct row)
    # rather than the framework's `_lists_id` parent-key name.
    row["list_id"] = str(row.pop("_lists_id"))
    return row


def campayn_source(
    subdomain: str,
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
) -> SourceResponse:
    config = CAMPAYN_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": base_url(subdomain),
            "headers": {"Accept": "application/json"},
            "auth": _auth_config(api_key),
            # Campayn's public API exposes no pagination on any list endpoint — every table is a
            # single bare-array page, full refresh only.
            "paginator": "single_page",
        },
        "resource_defaults": None,
        "resources": [],
    }

    if config.fan_out_over_lists:
        # Contacts/forms are nested under a list: enumerate /lists.json, then fetch the child
        # resource per list, stamping each row with its parent list_id. Full refresh only —
        # these endpoints expose no incremental filter.
        rest_config["resources"] = [
            {"name": "lists", "endpoint": {"path": CAMPAYN_ENDPOINTS["lists"].path}},
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": {"list_id": {"type": "resolve", "resource": "lists", "field": "id"}},
                    # A list deleted between enumeration and this fetch 404s. Skip it rather than
                    # failing the whole sync; any other HTTP error still raises.
                    "response_actions": [{"status_code": 404, "action": "ignore"}],
                },
                "include_from_parent": ["id"],
                "data_map": _stamp_list_id,
            },
        ]
        resources = rest_api_resources(rest_config, team_id, job_id, None)
        resource = next(r for r in resources if r.name == endpoint)
    else:
        rest_config["resources"] = [{"name": endpoint, "endpoint": {"path": config.path}}]
        resource = rest_api_resource(rest_config, team_id, job_id, None)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        # No stable creation-time field is exposed on any Campayn resource, so partitioning is disabled.
        partition_mode=None,
    )


def validate_credentials(subdomain: str, api_key: str) -> bool:
    # /lists.json is the cheapest read and the entry point every fan-out depends on. The probe runs
    # before the source is saved, so `redact_values` masks the API key in tracked telemetry here too.
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{base_url(subdomain)}{CAMPAYN_ENDPOINTS['lists'].path}",
        headers={"Authorization": f"TRUEREST apikey={api_key}", "Accept": "application/json"},
        timeout=15,
    )
    return ok
