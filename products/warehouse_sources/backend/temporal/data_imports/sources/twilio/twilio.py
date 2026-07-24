import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from dateutil import parser as dateutil_parser
from requests import Response
from requests.auth import HTTPBasicAuth

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BaseNextUrlPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.twilio.settings import (
    TWILIO_ENDPOINTS,
    TwilioEndpointConfig,
)

TWILIO_BASE_URL = "https://api.twilio.com"
TWILIO_API_VERSION = "2010-04-01"
DEFAULT_PAGE_SIZE = 1000

TwilioAuth = tuple[str, str]


@dataclasses.dataclass
class TwilioResumeConfig:
    next_url: str


class TwilioNextPageUriPaginator(BaseNextUrlPaginator):
    """Follow Twilio's body-level ``next_page_uri`` link.

    Twilio returns ``next_page_uri`` as a root-relative path (null/absent on the last page). The
    self-contained next link already carries every query param (PageSize, filters, Page token), so
    we resolve it to an absolute URL on the API host and let ``BaseNextUrlPaginator`` retarget the
    request to it — dropping the original params so they aren't re-appended each page.
    """

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            next_page_uri = response.json().get("next_page_uri")
        except Exception:
            next_page_uri = None
        if next_page_uri:
            self._next_url = f"{TWILIO_BASE_URL}{next_page_uri}"
            self._has_next_page = True
        else:
            self._has_next_page = False


def _format_filter_date(value: Any) -> str:
    """Format an incremental watermark as Twilio's day-granular GMT filter value (YYYY-MM-DD).

    Used with an inclusive `>=` filter, so the whole boundary day is re-fetched and de-duplicated
    on `sid` by the pipeline's merge semantics. `bool` is excluded from the numeric branch since it
    subclasses `int`. We raise on anything we can't turn into a real date rather than passing a
    malformed value through, which Twilio would reject mid-sync with the opaque error 20001.
    """
    if isinstance(value, datetime | date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, int | float) and not isinstance(value, bool):
        return datetime.fromtimestamp(value, tz=UTC).strftime("%Y-%m-%d")
    try:
        return dateutil_parser.parse(str(value)).strftime("%Y-%m-%d")
    except (ValueError, TypeError, OverflowError) as e:
        raise ValueError(f"Cannot build a Twilio date filter from incremental value {value!r}") from e


def _build_initial_params(
    config: TwilioEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"PageSize": DEFAULT_PAGE_SIZE}

    if should_use_incremental_field and db_incremental_field_last_value is not None:
        # Honor the user's chosen cursor field; only filter when it maps to a server-side filter.
        chosen = incremental_field if incremental_field in config.incremental_filter_params else None
        if chosen is None and len(config.incremental_filter_params) == 1:
            chosen = next(iter(config.incremental_filter_params))
        if chosen is not None:
            filter_base = config.incremental_filter_params[chosen]
            # The operator lives in the parameter NAME (e.g. `DateSent>`); the query separator `=`
            # then yields Twilio's documented `DateSent>=<date>` (inclusive, on-or-after) form. The
            # date value must stay plain — inlining the operator into the value triggers error 20001.
            params[f"{filter_base}>"] = _format_filter_date(db_incremental_field_last_value)

    return params


def _build_resource_path(config: TwilioEndpointConfig, account_sid: str) -> str:
    return f"/{TWILIO_API_VERSION}/Accounts/{account_sid}/{config.path}"


def validate_credentials(
    auth: TwilioAuth, account_sid: str, schema_name: Optional[str] = None
) -> tuple[bool, str | None]:
    if schema_name is not None and schema_name in TWILIO_ENDPOINTS:
        config = TWILIO_ENDPOINTS[schema_name]
        url = f"{TWILIO_BASE_URL}{_build_resource_path(config, account_sid)}?PageSize=1"
    else:
        url = f"{TWILIO_BASE_URL}/{TWILIO_API_VERSION}/Accounts/{account_sid}.json"

    _ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(auth[1],)),
        url,
        auth=HTTPBasicAuth(*auth),
    )

    if status == 200:
        return True, None

    if status == 401:
        return False, "Invalid Twilio credentials. Check your Account SID and Auth Token (or API key SID and secret)."

    # A valid token without access to a specific resource is acceptable at source-create time
    # (no schema selected yet); only treat it as a failure when validating a specific endpoint.
    if status == 403 and schema_name is None:
        return True, None

    if status is None:
        return False, "Could not reach Twilio to validate credentials."

    return False, f"Twilio returned an unexpected status ({status}) while validating credentials."


def twilio_source(
    auth: TwilioAuth,
    account_sid: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[TwilioResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = TWILIO_ENDPOINTS[endpoint]

    params = _build_initial_params(
        config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": TWILIO_BASE_URL,
            # HTTP basic auth via the framework so the secret is redacted from logs and errors.
            "auth": {"type": "http_basic", "username": auth[0], "password": auth[1]},
            "paginator": TwilioNextPageUriPaginator(),
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": _build_resource_path(config, account_sid),
                    "params": params,
                    "data_selector": config.response_key,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only while a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on `sid`) rather than skipping it.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(TwilioResumeConfig(next_url=str(state["next_url"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=[config.primary_key],
        sort_mode=config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
