from datetime import date, datetime
from typing import Any, Optional

import requests

from products.warehouse_sources.sources.asaas.settings import (
    ENDPOINT_PARAMS,
    ENDPOINT_PATHS,
    FANOUT_PARENT_ID_COLUMNS,
    FANOUT_PARENTS,
    INCREMENTAL_DATE_PARAMS,
    INCREMENTAL_FIELDS,
    TABLE_NAMES,
)
from products.warehouse_sources.sources.sdk import (
    ClientConfig,
    EndpointResource,
    OffsetPaginator,
    RESTAPIConfig,
    ResumableSourceManager,
    capture_exception,
    frozen,
    make_tracked_session,
    rename_parent_fields,
    rest_api_resource,
    rest_api_resources,
)

SANDBOX_BASE_URL = "https://api-sandbox.asaas.com"
PRODUCTION_BASE_URL = "https://api.asaas.com"
API_PATH = "/v3"

PRODUCTION_KEY_PREFIX = "$aact_prod_"
SANDBOX_KEY_PREFIX = "$aact_hmlg_"

INVALID_KEY_ERROR = (
    "Your Asaas API key is invalid, expired or disabled. Create a new key in Asaas under Integrações > API, "
    "then reconnect."
)
KEY_FORMAT_ERROR = (
    "Your Asaas API key isn't in the right format. Copy the full key, including the leading $aact_ and "
    "with no extra spaces, then reconnect."
)
KEY_IN_PRODUCTION_ERROR = (
    "Your Asaas API key is a production key, but you chose Sandbox. Change the environment to Production, "
    "then reconnect."
)
KEY_IN_SANDBOX_ERROR = (
    "Your Asaas API key is a sandbox key, but you chose Production. Change the environment to Sandbox, then reconnect."
)
WRONG_ENVIRONMENT_ERROR = (
    "Your Asaas API key belongs to the other environment. Change the environment to the one you created "
    "the key in, then reconnect."
)
FORBIDDEN_ERROR = (
    "Asaas refused your API key. Check that the key can read your account's data and that any IP allow list "
    "includes PostHog's IP addresses."
)
UNAVAILABLE_ERROR = "PostHog couldn't reach Asaas to check your API key. Wait a few minutes, then try again."

# Asaas caps list endpoints at 100 rows/page (offset/limit + hasMore/totalCount envelope).
PAGE_SIZE = 100


@frozen
class AsaasResumeConfig:
    offset: int


def base_url(environment: str) -> str:
    return PRODUCTION_BASE_URL if environment == "production" else SANDBOX_BASE_URL


def format_date_param(value: Any) -> str:
    """Format an incremental watermark for Asaas's date filters (`YYYY-MM-DD`)."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)[:10]


def get_resource(endpoint: str, should_use_incremental_field: bool) -> EndpointResource:
    table_name = TABLE_NAMES[endpoint]
    is_incremental_endpoint = should_use_incremental_field and endpoint in INCREMENTAL_DATE_PARAMS

    params: dict[str, Any] = dict(ENDPOINT_PARAMS.get(endpoint, {}))
    if is_incremental_endpoint:
        params[INCREMENTAL_DATE_PARAMS[endpoint]] = {
            "type": "incremental",
            "cursor_path": INCREMENTAL_FIELDS[endpoint][0]["field"],
            # Well before Asaas existed, so an unset watermark still fetches full history.
            "initial_value": "2000-01-01",
            "convert": format_date_param,
        }

    return {
        "name": endpoint,
        "table_name": table_name,
        "write_disposition": {
            "disposition": "merge",
            "strategy": "upsert",
        }
        if is_incremental_endpoint
        else "replace",
        "endpoint": {
            "data_selector": "data[*]",
            "path": f"{API_PATH}/{ENDPOINT_PATHS[endpoint]}",
            "params": params,
        },
        "table_format": "delta",
    }


def get_fanout_resource(endpoint: str) -> EndpointResource:
    parent = FANOUT_PARENTS[endpoint]
    return {
        "name": endpoint,
        "table_name": TABLE_NAMES[endpoint],
        "write_disposition": "replace",
        "include_from_parent": ["id"],
        "endpoint": {
            "data_selector": "data[*]",
            "path": f"{API_PATH}/{ENDPOINT_PATHS[endpoint]}",
            "params": {"id": {"type": "resolve", "resource": parent, "field": "id"}},
        },
        "table_format": "delta",
    }


def asaas_source(
    api_key: str,
    environment: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[AsaasResumeConfig],
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
):
    client: ClientConfig = {
        "base_url": base_url(environment),
        "auth": {
            "type": "api_key",
            "name": "access_token",
            "api_key": api_key,
            "location": "header",
        },
        "paginator": OffsetPaginator(limit=PAGE_SIZE, total_path="totalCount"),
        # Reject redirects: the `access_token` header must never be replayed onto
        # a host other than the one it was issued for.
        "allow_redirects": False,
    }

    if endpoint in FANOUT_PARENTS:
        parent = FANOUT_PARENTS[endpoint]
        # The fan-out resume state (completed parents + child page) doesn't fit AsaasResumeConfig,
        # so a resumed run restarts the fan-out from the first dunning.
        resources = rest_api_resources(
            {
                "client": client,
                "resource_defaults": {},
                "resources": [get_resource(parent, False), get_fanout_resource(endpoint)],
            },
            team_id,
            job_id,
            None,
        )
        child = next(resource for resource in resources if resource.name == endpoint)
        return child.add_map(rename_parent_fields(parent, {"id": FANOUT_PARENT_ID_COLUMNS[endpoint]}))

    config: RESTAPIConfig = {
        "client": client,
        "resource_defaults": {
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
        },
        "resources": [get_resource(endpoint, should_use_incremental_field)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"offset": resume_config.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's a next page to resume to; the Redis TTL handles cleanup on completion.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(AsaasResumeConfig(offset=int(state["offset"])))

    return rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def key_environment(api_key: str) -> str | None:
    """The environment an Asaas API key belongs to, from its prefix. Older keys carry no prefix."""
    if api_key.startswith(PRODUCTION_KEY_PREFIX):
        return "production"
    if api_key.startswith(SANDBOX_KEY_PREFIX):
        return "sandbox"
    return None


def _error_code(response: requests.Response) -> str | None:
    try:
        errors = response.json().get("errors")
        return errors[0].get("code") if errors else None
    except (ValueError, AttributeError, IndexError, TypeError):
        return None


def validate_credentials(api_key: str, environment: str) -> tuple[bool, str | None]:
    key_env = key_environment(api_key)
    if key_env is not None and key_env != environment:
        return False, KEY_IN_PRODUCTION_ERROR if key_env == "production" else KEY_IN_SANDBOX_ERROR

    try:
        # allow_redirects=False: a redirect would forward the access_token header off
        # the validated Asaas host.
        res = make_tracked_session(redact_values=(api_key,), allow_redirects=False).get(
            f"{base_url(environment)}{API_PATH}/customers?limit=1",
            headers={"access_token": api_key},
        )
    except requests.RequestException as e:
        capture_exception(e)
        return False, UNAVAILABLE_ERROR

    if res.status_code == 200:
        return True, None
    if res.status_code == 401:
        code = _error_code(res)
        if code == "invalid_environment":
            return False, WRONG_ENVIRONMENT_ERROR
        if code == "invalid_access_token_format":
            return False, KEY_FORMAT_ERROR
        return False, INVALID_KEY_ERROR
    if res.status_code == 403:
        return False, FORBIDDEN_ERROR
    return False, UNAVAILABLE_ERROR
