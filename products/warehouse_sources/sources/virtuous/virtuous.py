from datetime import date, datetime, timedelta
from typing import Any, Optional

from dateutil import parser

from products.warehouse_sources.sources.sdk import (
    Endpoint,
    EndpointResource,
    OffsetPaginator,
    RESTAPIConfig,
    ResumableSourceManager,
    SourceResponse,
    frozen,
    make_tracked_session,
    rest_api_resource,
    validate_via_probe,
)
from products.warehouse_sources.sources.virtuous.settings import (
    ENDPOINTS,
    LAST_MODIFIED_PARAMETER,
    ON_OR_AFTER_OPERATOR,
    REQUEST_TIMEOUT_SECONDS,
    VIRTUOUS_BASE_URL,
    VirtuousEndpointConfig,
)


@frozen
class VirtuousResumeConfig:
    skip: int


def modified_since(last_value: Any) -> str:
    """The date to send in the "Last Modified Date" condition for a watermark.

    The condition compares dates in the organization's time zone, while the watermark is a UTC
    timestamp, so the filter starts one day earlier. Merge on the primary key removes the overlap.
    """
    if isinstance(last_value, datetime):
        day = last_value.date()
    elif isinstance(last_value, date):
        day = last_value
    else:
        day = parser.isoparse(str(last_value)).date()
    return (day - timedelta(days=1)).isoformat()


def build_request_body(
    endpoint_config: VirtuousEndpointConfig, db_incremental_field_last_value: Optional[Any]
) -> dict[str, Any]:
    body = dict(endpoint_config.request_body)
    if not endpoint_config.is_query:
        return body

    groups: list[dict[str, Any]] = []
    if endpoint_config.supports_incremental and db_incremental_field_last_value is not None:
        groups.append(
            {
                "conditions": [
                    {
                        "parameter": LAST_MODIFIED_PARAMETER,
                        "operator": ON_OR_AFTER_OPERATOR,
                        "value": modified_since(db_incremental_field_last_value),
                    }
                ]
            }
        )
    # A stable sort on the id keeps `skip` paging consistent while new records are added.
    return {**body, "groups": groups, "sortBy": "Id", "descending": False}


def _resource(
    endpoint_config: VirtuousEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> EndpointResource:
    endpoint: Endpoint = {
        "method": endpoint_config.method,
        "path": endpoint_config.path,
        "data_selector": "list",
        "paginator": OffsetPaginator(
            limit=endpoint_config.page_size,
            offset_param="skip",
            limit_param="take",
            total_path="total",
        ),
    }
    if endpoint_config.method == "POST":
        endpoint["json"] = build_request_body(endpoint_config, db_incremental_field_last_value)

    return {
        "name": endpoint_config.name,
        "table_name": endpoint_config.name,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"}
        if should_use_incremental_field
        else "replace",
        "endpoint": endpoint,
        "table_format": "delta",
    }


def virtuous_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[VirtuousResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    endpoint_config = ENDPOINTS.get(endpoint)
    if endpoint_config is None:
        raise ValueError(f"Virtuous endpoint does not exist: {endpoint}")

    use_incremental = should_use_incremental_field and endpoint_config.supports_incremental
    last_value = db_incremental_field_last_value if use_incremental else None

    config: RESTAPIConfig = {
        "client": {
            "base_url": VIRTUOUS_BASE_URL,
            "auth": {"type": "bearer", "token": api_key},
            "request_timeout": REQUEST_TIMEOUT_SECONDS,
            "allowed_hosts": [],
            "allow_redirects": False,
            # Rows hold donor names, addresses, notes and giving history, which the generic sample
            # scrubbers can't reliably redact. Requests are still metered and logged.
            "capture": False,
        },
        "resource_defaults": {},
        "resources": [_resource(endpoint_config, use_incremental, last_value)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"offset": resume_config.skip}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state and state.get("offset"):
            resumable_source_manager.save_state(VirtuousResumeConfig(skip=int(state["offset"])))

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    partition_key = endpoint_config.partition_key
    return SourceResponse(
        name=endpoint_config.name,
        items=lambda: resource,
        primary_keys=list(endpoint_config.primary_keys),
        partition_mode="datetime" if partition_key else None,
        partition_format="month" if partition_key else None,
        partition_keys=[partition_key] if partition_key else None,
    )


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    if not api_key.isascii():
        return (
            False,
            "Your Virtuous API key contains an unsupported character, for example an invisible one "
            "pasted from another app. Retype it and try again.",
        )

    is_valid, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{VIRTUOUS_BASE_URL}/api/Organization/Current",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=REQUEST_TIMEOUT_SECONDS,
        allow_redirects=False,
    )

    if is_valid:
        return True, None
    if status == 401:
        return (
            False,
            "Virtuous rejected the API key. Create a key in Virtuous under Settings > Connectivity > "
            "API keys and try again.",
        )
    if status == 403:
        return (
            False,
            "Your Virtuous API key can't read your organization. Give the key's permission group "
            "read access in Virtuous, then try again.",
        )
    if status is None:
        return False, "Couldn't reach Virtuous to check the API key. Try again in a few minutes."
    return (
        False,
        f"Virtuous returned an unexpected status ({status}) while checking the API key. Try again in a few minutes.",
    )
