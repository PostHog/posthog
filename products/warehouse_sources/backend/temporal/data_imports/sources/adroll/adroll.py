import dataclasses
from typing import Any, Optional
from urllib.parse import urlencode

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.adroll.settings import ADROLL_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe

ADROLL_BASE_URL = "https://services.adroll.com"
# Quota is requests/day (default 100), so retry sparingly.
MAX_RETRY_ATTEMPTS = 3

# Parent resource name in the fan-out config. With include_from_parent=["eid"] the framework
# injects the parent advertisable EID into child rows as `_advertisable_eid` — the same key the
# rows carried before the rest_source migration.
_ADVERTISABLE_PARENT = "advertisable"


@dataclasses.dataclass
class AdRollResumeConfig:
    # Framework fan-out checkpoint ({"completed": [...], "current": ..., "child_state": ...}).
    # The plain advertisables list is a single request, so only fan-out endpoints checkpoint.
    fanout_state: Optional[dict[str, Any]] = None


def _client_config(client_id: str, personal_access_token: str) -> ClientConfig:
    return {
        "base_url": ADROLL_BASE_URL,
        # The PAT travels on the Authorization header via framework auth so its value is
        # redacted from logs. The app's Client ID is not a secret; it rides along as the
        # `apikey` query param on every endpoint (see per-endpoint params).
        "auth": {
            "type": "api_key",
            "api_key": f"Token {personal_access_token}",
            "name": "Authorization",
            "location": "header",
        },
        # AdRoll's get/get_all endpoints return everything in one response — no pagination.
        "paginator": SinglePagePaginator(),
        "max_retries": MAX_RETRY_ATTEMPTS,
    }


def adroll_source(
    client_id: str,
    personal_access_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[AdRollResumeConfig],
) -> SourceResponse:
    config = ADROLL_ENDPOINTS[endpoint]

    if not config.advertisable_scoped:
        rest_config: RESTAPIConfig = {
            "client": _client_config(client_id, personal_access_token),
            "resources": [
                {
                    "name": endpoint,
                    "endpoint": {
                        "path": config.path,
                        "params": {"apikey": client_id},
                        "data_selector": "results",
                    },
                }
            ],
        }
        # A single request — nothing to checkpoint.
        resource = rest_api_resource(rest_config, team_id, job_id, None)
    else:
        initial_state: Optional[dict[str, Any]] = None
        if resumable_source_manager.can_resume():
            resume = resumable_source_manager.load_state()
            if resume is not None and resume.fanout_state is not None:
                initial_state = resume.fanout_state

        def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
            if state is not None:
                resumable_source_manager.save_state(AdRollResumeConfig(fanout_state=state))

        rest_config = {
            "client": _client_config(client_id, personal_access_token),
            "resources": [
                {
                    "name": _ADVERTISABLE_PARENT,
                    "endpoint": {
                        "path": ADROLL_ENDPOINTS["advertisables"].path,
                        "params": {"apikey": client_id},
                        "data_selector": "results",
                    },
                },
                {
                    "name": endpoint,
                    "endpoint": {
                        # AdRoll scopes campaign/ad lists with an `advertisable` query param,
                        # not a path segment; bind the resolve param inside the query string.
                        "path": f"{config.path}?advertisable={{advertisable}}",
                        "params": {
                            "advertisable": {
                                "type": "resolve",
                                "resource": _ADVERTISABLE_PARENT,
                                "field": "eid",
                            },
                            "apikey": client_id,
                        },
                        "data_selector": "results",
                    },
                    "include_from_parent": ["eid"],
                },
            ],
        }
        resources = {
            resource.name: resource
            for resource in rest_api_resources(
                rest_config,
                team_id,
                job_id,
                None,
                resume_hook=save_checkpoint,
                initial_paginator_state=initial_state,
            )
        }
        # An advertisable without an EID can't scope a child request — skip it, as before.
        resources[_ADVERTISABLE_PARENT].add_filter(lambda item: bool(item.get("eid")))
        resource = resources[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        sort_mode="asc",
    )


def validate_credentials(client_id: str, personal_access_token: str) -> bool:
    """Confirm the PAT + apikey pair is valid with a cheap organization probe."""
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(personal_access_token,)),
        f"{ADROLL_BASE_URL}/api/v1/organization/get?{urlencode({'apikey': client_id})}",
        headers={"Authorization": f"Token {personal_access_token}"},
    )
    return ok
