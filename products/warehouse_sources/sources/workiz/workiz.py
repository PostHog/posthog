import datetime
from typing import Any, Optional

from requests import PreparedRequest

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import AuthConfigBase
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.workiz.settings import (
    DATE_WINDOWED_ENDPOINTS,
    DEFAULT_INCREMENTAL_FIELD,
    ENDPOINT_PATHS,
    PAGE_SIZE,
    TABLE_NAMES,
    UNPAGINATED_ENDPOINTS,
)

API_BASE_URL = "https://api.workiz.com/api/v1"

# Anchor for a full historical backfill. Omitting `start_date` entirely makes the API default to
# the last 14 days (see only_open/start_date docs), so a from-scratch sync needs an explicit,
# far-past date instead -- this predates Workiz itself.
_EARLIEST_START_DATE = datetime.date(2010, 1, 1)


class _PathTokenAuth(AuthConfigBase):
    """No-op auth: the token already lives in the base URL, not a header.

    Declaring it as an auth (rather than baking it into `base_url` alone) lets the shared client
    redact it from raised exception messages and HTTP log samples, the same way every other
    source's real auth class does.
    """

    def __init__(self, token: str) -> None:
        self._token = token

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        return request

    def secret_values(self) -> tuple[str, ...]:
        return (self._token,)


@frozen
class WorkizResumeConfig:
    offset: int


def _to_workiz_date(value: Any) -> str:
    """Format an incremental cursor value as the `yyyy-MM-dd` date Workiz's `start_date` expects."""
    if isinstance(value, datetime.datetime):
        return value.date().strftime("%Y-%m-%d")
    if isinstance(value, datetime.date):
        return value.strftime("%Y-%m-%d")
    if value is None:
        return _EARLIEST_START_DATE.strftime("%Y-%m-%d")
    return str(value)


def get_resource(name: str, should_use_incremental_field: bool, incremental_field: Optional[str]) -> EndpointResource:
    write_disposition = {"disposition": "merge", "strategy": "upsert"} if should_use_incremental_field else "replace"

    if name in DATE_WINDOWED_ENDPOINTS:
        cursor_field = incremental_field or DEFAULT_INCREMENTAL_FIELD[name]
        endpoint: Endpoint = {
            "path": ENDPOINT_PATHS[name],
            "params": {
                "start_date": {
                    "type": "incremental",
                    "cursor_path": cursor_field,
                    "initial_value": _EARLIEST_START_DATE,
                    "convert": _to_workiz_date,
                },
                "records": PAGE_SIZE,
                # Historical syncs need Done/Canceled records too; the API excludes them by default.
                "only_open": "false",
            },
            "paginator": OffsetPaginator(
                limit=PAGE_SIZE, offset_param="offset", limit_param="records", total_path=None
            ),
        }
        if name == "Jobs":
            # Workiz's published OpenAPI spec (developer.workiz.com/api.json) wraps each job/all
            # item as {"flag": bool, "data": Job} -- unlike lead/all, which returns Lead objects
            # directly. Not verified against a live account.
            endpoint["data_selector"] = "[*].data"
    else:
        endpoint = {
            "path": ENDPOINT_PATHS[name],
            "paginator": "single_page",
        }

    resource: EndpointResource = {
        "name": name,
        "table_name": TABLE_NAMES[name],
        "write_disposition": write_disposition,
        "endpoint": endpoint,
        "table_format": "delta",
    }
    return resource


def workiz_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[WorkizResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
    incremental_field: Optional[str],
) -> Resource:
    config: RESTAPIConfig = {
        "client": {
            "base_url": f"{API_BASE_URL}/{api_token}",
            "auth": _PathTokenAuth(api_token),
            # `capture=False`: Jobs/Leads rows carry customer PII (contact details, addresses,
            # job comments, internal notes) the name-based sample scrubbers aren't built to
            # catch, so keep them out of HTTP diagnostic sample storage entirely, same as the
            # other PII/free-text field-service sources (e.g. ServiceM8).
            "capture": False,
        },
        "resources": [get_resource(endpoint, should_use_incremental_field, incremental_field)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if endpoint not in UNPAGINATED_ENDPOINTS and resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"offset": resume_config.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        offset = state.get("offset") if state else None
        if offset is not None:
            resumable_source_manager.save_state(WorkizResumeConfig(offset=int(offset)))

    return rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def validate_credentials(api_token: str) -> tuple[bool, str | None]:
    # The token unlocks every read endpoint at once (no per-endpoint scopes), so one cheap probe
    # against the smallest list endpoint validates it. `capture=False`: the probe response is a
    # team-member list, same PII concern as the sync client above.
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,), capture=False),
        f"{API_BASE_URL}/{api_token}/team/all/",
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid API token. Check Settings > Integrations > Developer in Workiz and try again."
    if status is None:
        return False, "Could not reach Workiz to validate the API token."
    return False, f"Workiz returned HTTP {status}."
