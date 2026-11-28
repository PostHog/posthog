from datetime import date, datetime, timedelta
from typing import Any, Optional

from dateutil import parser

from products.warehouse_sources.sources.sdk import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    OffsetPaginator,
    RESTAPIConfig,
    ResumableSourceManager,
    SourceResponse,
    build_dependent_resource,
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
    skip: int = 0
    fanout_state: dict[str, Any] | None = None


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


def _endpoint(endpoint_config: VirtuousEndpointConfig, last_value: Optional[Any] = None) -> Endpoint:
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
        endpoint["json"] = build_request_body(endpoint_config, last_value)
    return endpoint


def _resource(
    endpoint_config: VirtuousEndpointConfig, should_use_incremental_field: bool, last_value: Optional[Any]
) -> EndpointResource:
    return {
        "name": endpoint_config.name,
        "table_name": endpoint_config.name,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"}
        if should_use_incremental_field
        else "replace",
        "endpoint": _endpoint(endpoint_config, last_value),
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

    client_config: ClientConfig = {
        "base_url": VIRTUOUS_BASE_URL,
        "auth": {"type": "bearer", "token": api_key},
        "request_timeout": REQUEST_TIMEOUT_SECONDS,
        "allowed_hosts": [],
        "allow_redirects": False,
        # Rows hold donor names, addresses, notes and giving history, which the generic sample
        # scrubbers can't reliably redact. Requests are still metered and logged.
        "capture": False,
    }

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state and state.get("offset"):
            resumable_source_manager.save_state(VirtuousResumeConfig(skip=int(state["offset"])))

    def save_fanout_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state is not None:
            resumable_source_manager.save_state(VirtuousResumeConfig(fanout_state=state))

    if fanout := endpoint_config.fanout:
        resource = build_dependent_resource(
            endpoint_configs=ENDPOINTS,
            child_endpoint=endpoint,
            fanout=fanout,
            client_config=client_config,
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            page_size_param=None,
            parent_endpoint_extra=_endpoint(ENDPOINTS[fanout.parent_name]),
            child_endpoint_extra=_endpoint(endpoint_config),
            resume_hook=save_fanout_checkpoint,
            initial_paginator_state=resume_config.fanout_state if resume_config is not None else None,
            resume_parent_pagination=True,
        )
    else:
        config: RESTAPIConfig = {
            "client": client_config,
            "resource_defaults": {},
            "resources": [_resource(endpoint_config, use_incremental, last_value)],
        }
        resource = rest_api_resource(
            config,
            team_id,
            job_id,
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state={"offset": resume_config.skip} if resume_config is not None else None,
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
