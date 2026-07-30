import re
import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from urllib3.util.retry import Retry

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.nocrm.settings import (
    NOCRM_ENDPOINTS,
    NoCRMEndpointConfig,
)

# noCRM caps `/leads` at a default of 100 per page; request the max to minimise round-trips against
# the low (~2000 req/day) account quota.
PAGE_SIZE = 100

# noCRM reports the grand total (used to stop before an extra empty request) in this response header.
TOTAL_COUNT_HEADER = "X-TOTAL-COUNT"

# noCRM hosts every account under `<subdomain>.nocrm.io`. Only the subdomain label is user-supplied,
# so restrict it to the DNS-label charset — this keeps a crafted value from breaking out of the
# `.nocrm.io` origin and pointing the authenticated request somewhere else (SSRF).
_SUBDOMAIN_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


class NoCRMConfigError(Exception):
    """The connector config is malformed (e.g. an invalid subdomain) and can never succeed."""


def normalize_subdomain(subdomain: str) -> str:
    """Reduce whatever the user typed to a bare, validated noCRM subdomain label.

    Accepts a bare label (`acme`) or a full host/URL (`acme.nocrm.io`, `https://acme.nocrm.io/`) and
    returns just `acme`. Raises `NoCRMConfigError` when nothing valid remains, so we never build a
    request URL around an attacker-controlled host.
    """
    value = (subdomain or "").strip().lower()
    # Strip scheme and any path if the user pasted a full URL.
    value = re.sub(r"^https?://", "", value)
    value = value.split("/")[0]
    # Strip the shared apex domain if present, leaving just the account label.
    value = value.removesuffix(".nocrm.io")
    if not _SUBDOMAIN_RE.match(value):
        raise NoCRMConfigError(
            "Invalid noCRM subdomain. Enter just your account's subdomain, e.g. 'acme' for acme.nocrm.io."
        )
    return value


def _base_url(subdomain: str) -> str:
    return f"https://{normalize_subdomain(subdomain)}.nocrm.io/api/v2"


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "X-API-KEY": api_key,
        "Accept": "application/json",
    }


def _format_updated_after(value: Any) -> str:
    """Format an incremental cursor as the ISO 8601 UTC string noCRM's `updated_after` expects."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def _clamp_future_value_to_now(value: Any) -> Any:
    """Cap a future datetime/date cursor at now.

    If bad source data pushes the `updated_at` cursor past now, every later sync would ask noCRM for
    changes since a future date and get nothing back, wedging the table until real data catches up.
    Asking for changes newer than now is a no-op anyway, so clamping lets the sync self-heal.
    """
    now = datetime.now(UTC)
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return now if aware > now else value
    if isinstance(value, date):
        return now.date() if value > now.date() else value
    return value


def _build_base_params(
    config: NoCRMEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    """Query params shared by every page of a sync (everything except limit/offset)."""
    params: dict[str, Any] = {}

    if config.default_sort_order:
        params["order"] = config.default_sort_order
        params["direction"] = "asc"

    if (
        config.supports_incremental
        and config.incremental_param
        and should_use_incremental_field
        and db_incremental_field_last_value is not None
    ):
        params[config.incremental_param] = _format_updated_after(
            _clamp_future_value_to_now(db_incremental_field_last_value)
        )
        # Sort ascending by the changed field so pages arrive in the order the `asc` watermark expects.
        if config.incremental_sort_order:
            params["order"] = config.incremental_sort_order
            params["direction"] = "asc"

    return params


@dataclasses.dataclass
class NoCRMResumeConfig:
    # Offset (row count already consumed) to resume limit/offset pagination from. The incremental
    # window is recomputed from the job's stable last-value, so only the offset needs persisting.
    offset: int = 0


class NoCRMOffsetPaginator(OffsetPaginator):
    """OffsetPaginator with a no-progress guard.

    An endpoint that ignores `offset` re-serves the first page forever. When a fetched page leads with
    the same id we already saw, pagination isn't advancing, so stop instead of looping. The offending
    page still surfaces once (merge dedupes on the primary key), but the loop terminates.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._previous_first_id: Any = None

    def update_state(self, response: Any, data: Optional[list[Any]] = None) -> None:
        if data:
            first = data[0]
            first_id = first.get("id") if isinstance(first, dict) else None
            # self.offset is still the offset this page was requested at (super increments it below).
            if self.offset > 0 and first_id is not None and first_id == self._previous_first_id:
                self._has_next_page = False
                return
            self._previous_first_id = first_id
        super().update_state(response, data)


def nocrm_source(
    api_key: str,
    subdomain: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[NoCRMResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = NOCRM_ENDPOINTS[endpoint]
    base_params = _build_base_params(config, should_use_incremental_field, db_incremental_field_last_value)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": _base_url(subdomain),
            # Non-secret header only; the API key rides on the framework auth so it's redacted from
            # logs, samples, and raised error messages.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "api_key", "api_key": api_key, "name": "X-API-KEY", "location": "header"},
            # Pin every request (including seeded resume pages) to the account's own *.nocrm.io host,
            # and refuse to follow redirects, so the key can't be steered to another origin.
            "allowed_hosts": [],
            "allow_redirects": False,
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": base_params,
                    # List endpoints return a bare JSON array; no data_selector needed. noCRM reports
                    # the grand total in a header, so stop on the header total / short / empty page.
                    "paginator": NoCRMOffsetPaginator(
                        limit=PAGE_SIZE, total_path=None, total_header=TOTAL_COUNT_HEADER
                    ),
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"offset": resume.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields the
        # last page (merge dedupes) rather than skipping it.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(NoCRMResumeConfig(offset=int(state["offset"])))

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
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Leads are requested with `order=last_update&direction=asc` on incremental syncs, and the
        # ResumableSource offset state (not the watermark) drives mid-sync resume, so `asc` matches
        # the framework's incremental checkpointing.
        sort_mode="asc",
    )


def validate_credentials(api_key: str, subdomain: str) -> bool:
    """Probe the cheap `/ping` endpoint to confirm the API key and subdomain are genuine."""
    try:
        url = f"{_base_url(subdomain)}/ping"
    except NoCRMConfigError:
        return False

    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,), allow_redirects=False, retry=Retry(total=0)),
        url,
        headers=_get_headers(api_key),
    )
    return ok
