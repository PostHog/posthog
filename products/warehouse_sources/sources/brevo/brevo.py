import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from products.warehouse_sources.sources.brevo.settings import BREVO_ENDPOINTS, BrevoEndpointConfig
from products.warehouse_sources.sources.sdk import (
    BasePaginator,
    OffsetPaginator,
    RESTAPIConfig,
    ResumableSourceManager,
    SinglePagePaginator,
    SourceResponse,
    capture_exception,
    make_tracked_session,
    rest_api_resource,
    validate_via_probe,
)

BREVO_BASE_URL = "https://api.brevo.com/v3"

BREVO_SMTP_KEY_PREFIX = "xsmtpsib-"

BREVO_INVALID_API_KEY_MESSAGE = (
    "Brevo rejected your API key. Create a new API key in your Brevo account settings, then reconnect."
)
BREVO_SMTP_KEY_MESSAGE = (
    "You entered a Brevo SMTP key. Create a key on the API keys tab of your Brevo SMTP & API settings, then reconnect."
)
BREVO_MISSING_PERMISSIONS_MESSAGE = (
    "Your Brevo API key can't read your account. Check the key in your Brevo account settings, then reconnect."
)
BREVO_UNREACHABLE_MESSAGE = "Couldn't reach Brevo to validate your API key. Try again in a few minutes."


@dataclasses.dataclass(frozen=False)
class BrevoResumeConfig:
    # Offset (record index) of the next page to fetch within the current sync.
    offset: int


def _format_datetime(value: Any) -> str:
    """Format a value as Brevo's expected UTC date-time (YYYY-MM-DDTHH:mm:ss.SSSZ).

    Brevo rejects the +00:00 offset produced by isoformat(), so we emit the Z suffix.
    """
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if isinstance(value, date):
        return _format_datetime(datetime.combine(value, datetime.min.time(), tzinfo=UTC))
    return str(value)


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    """Cheap probe to confirm the API key is genuine."""
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{BREVO_BASE_URL}/account",
        headers={"api-key": api_key, "accept": "application/json"},
        allow_redirects=False,
    )
    if ok:
        return True, None
    if status == 401:
        # Brevo lists SMTP keys next to API keys, and only API keys work against the REST API.
        if api_key.strip().startswith(BREVO_SMTP_KEY_PREFIX):
            return False, BREVO_SMTP_KEY_MESSAGE
        return False, BREVO_INVALID_API_KEY_MESSAGE
    if status == 403:
        return False, BREVO_MISSING_PERMISSIONS_MESSAGE
    # No status means the request never completed. That, a rate limit and a Brevo-side error are
    # all transient, so none of them should point the user at a key that may be fine.
    if status is None or status == 429 or status >= 500:
        return False, BREVO_UNREACHABLE_MESSAGE
    capture_exception(Exception(f"Unexpected Brevo credential validation response ({status})"))
    return False, BREVO_INVALID_API_KEY_MESSAGE


def _build_base_params(
    config: BrevoEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: Optional[str],
) -> dict[str, Any]:
    params: dict[str, Any] = {}

    # Brevo only sorts by record creation date. Sorting ascending keeps pagination boundaries
    # stable as new rows are inserted mid-sync and makes createdAt-based incremental monotonic.
    if config.paginate:
        params["sort"] = "asc"

    if should_use_incremental_field and incremental_field and db_incremental_field_last_value:
        param_name = config.incremental_param_map.get(incremental_field)
        if param_name:
            params[param_name] = _format_datetime(db_incremental_field_last_value)

    return params


def brevo_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BrevoResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: Optional[str] = None,
) -> SourceResponse:
    config = BREVO_ENDPOINTS[endpoint]
    params = _build_base_params(
        config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )

    # Brevo reports a top-level `count`, but termination stays short/empty page (total_path=None):
    # counts drift as rows are inserted mid-sync, and the short-page rule is exact.
    paginator: BasePaginator = (
        OffsetPaginator(limit=config.page_size, total_path=None) if config.paginate else SinglePagePaginator()
    )

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": BREVO_BASE_URL,
            "headers": {"accept": "application/json"},
            # Framework auth so the key is redacted from logs/samples wherever it appears.
            "auth": {"type": "api_key", "name": "api-key", "api_key": api_key, "location": "header"},
            "paginator": paginator,
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    # Brevo omits the array key entirely (or sets it to null) for an empty
                    # collection, e.g. {"count": 0} with no "campaigns"/"segments" key. That must
                    # read as an empty page rather than crash the sync, so the selector is NOT
                    # required.
                    "data_selector": config.data_key,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if config.paginate and resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"offset": resume.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; the framework saves AFTER a page is yielded so a
        # crash re-yields the last page (merge dedupes on primary key) rather than skipping it.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(BrevoResumeConfig(offset=int(state["offset"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value if should_use_incremental_field else None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=["id"],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
    )
