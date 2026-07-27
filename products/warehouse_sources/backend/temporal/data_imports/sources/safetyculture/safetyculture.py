import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponsePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.utils import (
    resolve_request_url,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.safetyculture.settings import (
    SAFETYCULTURE_ENDPOINTS,
)

SAFETYCULTURE_BASE_URL = "https://api.safetyculture.io"
# Cheap feed used to confirm an API token is genuine. Feed access is permission-scoped, so a 403
# here still proves the token itself is valid (see `validate_credentials` on the source class).
DEFAULT_PROBE_PATH = "/feed/users"


@dataclasses.dataclass
class SafetyCultureResumeConfig:
    # The next page to fetch, resolved from the API's `metadata.next_page` (the docs forbid
    # constructing it yourself). It embeds every filter — including `modified_after` on an
    # incremental sync — so a crashed sync resumes from the page after the last one yielded; merge
    # dedupes the re-pulled page on `id`. Historic saves stored a relative path; the paginator
    # resolves either form against the API host on load.
    next_page: str | None = None


def _format_modified_after(value: Any) -> str:
    """Format an incremental cursor as the Internet Date-Time string SafetyCulture expects.

    Since 2025-02-01 the Feed APIs reject anything that isn't `{Y}-{m}-{d}T{H}:{M}:{S}[.{frac}]Z`.
    """
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    return str(value)


class SafetyCultureFeedPaginator(JSONResponsePaginator):
    """Follows SafetyCulture Data Feed pagination.

    Every feed wraps records in `{"metadata": {"next_page", "remaining_records"}, "data": [...]}`.
    `metadata.next_page` is a RELATIVE path (e.g. `/feed/users?opaque-cursor=xyz`) that must be
    followed verbatim, so it's resolved against the API host before it becomes a request URL. An
    empty page also terminates the feed defensively, so a lingering cursor can never loop forever.
    """

    def __init__(self) -> None:
        super().__init__(next_url_path="metadata.next_page")

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if not data:
            self._has_next_page = False
            return
        super().update_state(response, data)
        self._absolutize()

    def set_resume_state(self, state: dict[str, Any]) -> None:
        super().set_resume_state(state)
        self._absolutize()

    def _absolutize(self) -> None:
        if self._next_url and not self._next_url.startswith(("http://", "https://")):
            self._next_url = resolve_request_url(SAFETYCULTURE_BASE_URL, self._next_url)


def safetyculture_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SafetyCultureResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = SAFETYCULTURE_ENDPOINTS[endpoint]

    # Static params ride only on the first request; every later page comes from the verbatim
    # `metadata.next_page`, which already carries them. `modified_after` is added only for an
    # incremental sync that actually has a watermark to filter from.
    params: dict[str, Any] = dict(config.params)
    if config.supports_incremental and should_use_incremental_field and db_incremental_field_last_value:
        params["modified_after"] = _format_modified_after(db_incremental_field_last_value)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": SAFETYCULTURE_BASE_URL,
            # Auth (Bearer) goes through the framework auth config so its value is redacted from
            # logs and raised errors; only the non-secret Accept header is set here.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "bearer", "token": api_token},
            "paginator": SafetyCultureFeedPaginator(),
            # `metadata.next_page` is followed verbatim, so pin every request (and the Bearer token)
            # to api.safetyculture.io and refuse redirects — a tampered/off-host next_page or a 3xx
            # can't retarget the credentialed request. `allowed_hosts=[]` means base-host only.
            "allowed_hosts": [],
            "allow_redirects": False,
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    "data_selector": "data",
                    # A 200 whose body isn't the documented {"metadata", "data": [...]} envelope is
                    # treated as transient (a truncating proxy, a flaky gateway) and retried.
                    "data_selector_malformed_retryable": True,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_page:
            initial_paginator_state = {"next_url": resume.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist AFTER a page is yielded and only while a next page remains, so a crash re-fetches
        # the next page (merge dedupes) rather than skipping it. A null `next_page` (feed end) or an
        # empty page yields state=None and nothing is saved.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(SafetyCultureResumeConfig(next_page=state["next_url"]))

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
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Incremental feeds paginate by advancing `modified_after` in the server-issued `next_page`
        # path, so rows arrive oldest-modified-first — matching the pipeline's ascending watermark.
        sort_mode="asc",
        column_hints=resource.column_hints,
    )


def check_access(api_token: str, path: str = DEFAULT_PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single feed to validate the API token.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    session = make_tracked_session(
        headers={"Authorization": f"Bearer {api_token}", "Accept": "application/json"},
        redact_values=(api_token,),
    )
    try:
        response = session.get(f"{SAFETYCULTURE_BASE_URL}{path}", timeout=15)
    except Exception as e:
        return 0, f"Could not connect to SafetyCulture: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"SafetyCulture returned HTTP {response.status_code}"

    return 200, None
