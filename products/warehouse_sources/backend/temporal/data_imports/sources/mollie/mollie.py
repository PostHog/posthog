import dataclasses
from collections.abc import Callable, Iterable
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponsePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.mollie.settings import (
    MOLLIE_ENDPOINTS,
    MollieEndpointConfig,
)

MOLLIE_BASE_URL = "https://api.mollie.com/v2"


@dataclasses.dataclass(frozen=True)
class MollieResumeConfig:
    # Mollie paginates via the HAL `_links.next.href` URL, which is
    # self-contained (ID-anchored `from` cursor), so the URL is all we persist.
    next_url: Optional[str] = None
    # Nested endpoints store the `build_dependent_resource` checkpoint instead: which parents
    # finished and where the current one stopped.
    fanout_state: Optional[dict[str, Any]] = None


def _only_payments_with_captures(payment: dict[str, Any]) -> dict[str, Any] | list[dict[str, Any]]:
    # Mollie sets amountCaptured only on payments whose method supports captures. Dropping the
    # other payments saves one captures request per payment that can never have a capture.
    return payment if payment.get("amountCaptured") is not None else []


# Per-child filters on the fan-out parent rows, keyed by the child endpoint name.
_PARENT_DATA_MAPS: dict[str, Callable[[dict[str, Any]], dict[str, Any] | list[dict[str, Any]]]] = {
    "captures": _only_payments_with_captures,
}


def _source_response(endpoint: str, config: MollieEndpointConfig, items: Callable[[], Iterable[Any]]) -> SourceResponse:
    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[config.partition_key],
        sort_mode="asc",
    )


def mollie_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[MollieResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = MOLLIE_ENDPOINTS[endpoint]
    client_config: ClientConfig = {
        "base_url": MOLLIE_BASE_URL,
        # Bearer is supplied via the framework auth config so its value is redacted from logs
        # and raised error messages.
        "auth": {"type": "bearer", "token": api_key},
        # Mollie paginates via the HAL `_links.next.href` URL, which is self-contained.
        "paginator": JSONResponsePaginator(next_url_path="_links.next.href"),
    }

    resume: Optional[MollieResumeConfig] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()

    if config.fanout is not None:
        parent_config = MOLLIE_ENDPOINTS[config.fanout.parent_name]

        def save_fanout_checkpoint(state: Optional[dict[str, Any]]) -> None:
            if state:
                resumable_source_manager.save_state(MollieResumeConfig(fanout_state=state))

        child = build_dependent_resource(
            endpoint_configs=MOLLIE_ENDPOINTS,
            child_endpoint=endpoint,
            fanout=config.fanout,
            client_config=client_config,
            parent_endpoint_extra={"data_selector": f"_embedded.{parent_config.embedded_key}"},
            parent_data_map=_PARENT_DATA_MAPS.get(endpoint),
            child_endpoint_extra={"data_selector": f"_embedded.{config.embedded_key}"},
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=db_incremental_field_last_value,
            resume_hook=save_fanout_checkpoint,
            initial_paginator_state=resume.fanout_state if resume else None,
        )
        return _source_response(endpoint, config, lambda: child)

    rest_config: RESTAPIConfig = {
        "client": client_config,
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": {"limit": config.page_size},
                    # Rows live under the HAL `_embedded.<key>` object. A missing block is a
                    # legitimate empty page (yield nothing), not an error, so no data_selector_required.
                    "data_selector": f"_embedded.{config.embedded_key}",
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resume is not None and resume.next_url:
        initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Save state AFTER yielding a page so a crash re-yields the last page (merge dedupes on
        # primary key) rather than skipping it; persist only while a next page remains.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(MollieResumeConfig(next_url=state["next_url"]))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return _source_response(endpoint, config, lambda: resource)


def validate_credentials(api_key: str) -> bool:
    """Confirm the API key is valid with a cheap one-payment listing probe.

    Organization access tokens require a profileId on profile-scoped endpoints
    (a 4xx that isn't 401), so only 401 means the credential itself is bad."""
    _ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{MOLLIE_BASE_URL}/payments?limit=1",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    return status is not None and status != 401
