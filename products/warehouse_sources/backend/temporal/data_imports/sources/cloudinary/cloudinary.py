import dataclasses
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.cloudinary.settings import CLOUDINARY_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

CLOUDINARY_API_HOSTS = {
    "global": "https://api.cloudinary.com",
    "eu": "https://api-eu.cloudinary.com",
    "ap": "https://api-ap.cloudinary.com",
}
REQUEST_TIMEOUT_SECONDS = 30


@dataclasses.dataclass
class CloudinaryResumeConfig:
    cursor: str


def base_url(cloud_name: str, region: str) -> str:
    host = CLOUDINARY_API_HOSTS.get(region, CLOUDINARY_API_HOSTS["global"])
    return f"{host}/v1_1/{cloud_name}"


def get_resource(endpoint: str) -> EndpointResource:
    config = CLOUDINARY_ENDPOINTS[endpoint]
    return {
        "name": config.name,
        "table_name": config.name,
        "primary_key": config.primary_key,
        "write_disposition": "replace",
        "endpoint": {
            "data_selector": f"{config.data_key}[*]",
            "path": config.path,
            "params": dict(config.params),
        },
        "table_format": "delta",
    }


def cloudinary_source(
    cloud_name: str,
    api_key: str,
    api_secret: str,
    region: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CloudinaryResumeConfig],
):
    config: RESTAPIConfig = {
        "client": {
            "base_url": base_url(cloud_name, region),
            "auth": {"type": "http_basic", "username": api_key, "password": api_secret},
            "paginator": JSONResponseCursorPaginator(cursor_path="next_cursor", cursor_param="next_cursor"),
        },
        "resource_defaults": {"write_disposition": "replace"},
        "resources": [get_resource(endpoint)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"cursor": resume_config.cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state and state.get("cursor"):
            resumable_source_manager.save_state(CloudinaryResumeConfig(cursor=str(state["cursor"])))

    return rest_api_resource(
        config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def validate_credentials(cloud_name: str, api_key: str, api_secret: str, region: str) -> tuple[bool, Optional[str]]:
    """Ping is the one Admin API call that costs nothing against the hourly quota."""
    try:
        response = make_tracked_session(redact_values=(api_secret,)).get(
            f"{base_url(cloud_name, region)}/ping",
            auth=(api_key, api_secret),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except Exception:
        return False, "Could not reach the Cloudinary API. Check your connection and try again."

    if response.ok:
        return True, None
    if response.status_code in (401, 403):
        return False, (
            "Cloudinary rejected these credentials. Check the API key and secret in your Cloudinary console, "
            "under Settings then API Keys."
        )
    if response.status_code == 404:
        return False, "Cloudinary does not recognize this cloud name. Copy it from your Cloudinary console."
    if response.status_code == 420 or response.status_code == 429:
        return False, "This Cloudinary account has hit its hourly Admin API limit. Wait for the limit to reset."
    return False, f"Cloudinary returned an unexpected error ({response.status_code}) while checking these credentials."
