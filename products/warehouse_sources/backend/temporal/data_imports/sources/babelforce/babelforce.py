import re
import time
import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from requests import PreparedRequest, Request, Response, Session

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.babelforce.settings import (
    BABELFORCE_ENDPOINTS,
    BabelforceEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import AuthConfigBase
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe

DEFAULT_ENVIRONMENT = "services"
PAGE_SIZE = 100

# The environment is the babelforce subdomain the customer's account lives on (usually
# "services", or a custom subdomain for dedicated environments). It becomes part of the
# request host, so it must be a plain DNS label — anything else could retarget credentials.
_ENVIRONMENT_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9-]*$")


@dataclasses.dataclass
class BabelforceResumeConfig:
    # Page index of the next unfetched page and the frozen request window; both are persisted
    # so a resumed run reissues the identical query (same date window, next page).
    next_page: int
    params: dict[str, Any]


class BabelforceAuth(AuthConfigBase):
    """Auth carrying babelforce's paired access ID/token on custom headers.

    The credentials ride ``X-Auth-Access-*`` headers the name-based sample scrubber can't know
    about, so both values are declared secret here — the tracked transport then masks them in
    logs, samples, and raised error messages.
    """

    def __init__(self, access_id: str, access_token: str) -> None:
        self.access_id = access_id
        self.access_token = access_token

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        request.headers["X-Auth-Access-Id"] = self.access_id
        request.headers["X-Auth-Access-Token"] = self.access_token
        return request

    def secret_values(self) -> tuple[str, ...]:
        return tuple(value for value in (self.access_id, self.access_token) if value)


class BabelforcePaginator(BasePaginator):
    """Page/max paginator driven by the server-reported ``pagination.current``.

    babelforce's first-page index is undocumented, so the first request omits ``page`` and the
    next page is derived from the response's ``pagination.current`` (``current + 1``). Pagination
    stops on the last page (``current >= pages``), an empty/short page, a missing/non-int
    ``current``, or a page that fails to advance (the server ignored ``page`` and re-served the
    same page) — which also prevents an infinite loop.
    """

    def __init__(self, page_param: str = "page") -> None:
        super().__init__()
        self.page_param = page_param
        # None => omit ``page`` on the first request and let the server pick the first index.
        self.page: Optional[int] = None
        self.previous_current: Optional[int] = None

    def _apply_page(self, request: Request) -> None:
        if self.page is not None:
            if request.params is None:
                request.params = {}
            request.params[self.page_param] = self.page

    def init_request(self, request: Request) -> None:
        self._apply_page(request)

    def update_request(self, request: Request) -> None:
        self._apply_page(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        items = data or []
        if not items:
            self._has_next_page = False
            return

        try:
            body = response.json()
        except Exception:
            body = {}
        pagination = body.get("pagination") or {} if isinstance(body, dict) else {}
        current = pagination.get("current")
        pages = pagination.get("pages")

        # The server ignored our ``page`` param and re-served the same (or an earlier) page; stop
        # rather than looping forever.
        if self.previous_current is not None and isinstance(current, int) and current <= self.previous_current:
            self._has_next_page = False
            return

        if not isinstance(current, int):
            self._has_next_page = False
            return

        if isinstance(pages, int) and current >= pages:
            self._has_next_page = False
            return

        self.previous_current = current
        self.page = current + 1
        self._has_next_page = True

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"next_page": self.page} if self._has_next_page and self.page is not None else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        page = state.get("next_page")
        if page is not None:
            self.page = int(page)
            self._has_next_page = True


def is_environment_valid(environment: str) -> bool:
    return bool(_ENVIRONMENT_RE.match(environment.strip()))


def _base_url(environment: str) -> str:
    environment = environment.strip()
    if not is_environment_valid(environment):
        raise ValueError(f"Invalid babelforce environment: {environment!r}")
    return f"https://{environment.lower()}.babelforce.com/api/v2"


def _get_headers(access_id: str, access_token: str) -> dict[str, str]:
    return {
        "X-Auth-Access-Id": access_id,
        "X-Auth-Access-Token": access_token,
        "Accept": "application/json",
    }


def _make_session(access_id: str, access_token: str) -> Session:
    # The credentials ride custom `X-Auth-Access-*` headers, which the sampler's name-based
    # auth-header denylist doesn't cover and which requests would forward on a cross-host
    # redirect (it only strips `Authorization`), so redact them by value and pin redirects
    # off. Responses carry customer communications (SMS bodies, phone numbers, recording
    # URLs) the generic scrubber can't safely clean, so keep them out of sample capture.
    return make_tracked_session(
        redact_values=(access_id, access_token),
        allow_redirects=False,
        capture=False,
    )


def _to_epoch(value: Any) -> Optional[int]:
    """Coerce an incremental cursor value to unix seconds for the `dateCreated.start` filter.

    babelforce returns ISO-8601 date-time strings (e.g. "2020-04-16T22:21:38.000Z"), so the
    persisted watermark is a datetime/string; ints are accepted defensively.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return int(dt.timestamp())
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp())
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            try:
                return int(value)
            except ValueError:
                return None
        dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
        return int(dt.timestamp())
    return None


def _build_params(
    config: BabelforceEndpointConfig, from_timestamp: Optional[int], to_timestamp: Optional[int]
) -> dict[str, Any]:
    params: dict[str, Any] = {"max": PAGE_SIZE}
    if config.supports_date_created_filter:
        # Documented on the call reporting endpoint as unix-second filters. The upper bound is
        # frozen at sync start so page contents stay stable while new calls arrive mid-sync;
        # newer rows are picked up by the next run's window.
        if from_timestamp is not None:
            params["dateCreated.start"] = from_timestamp
        if to_timestamp is not None:
            params["dateCreated.end"] = to_timestamp
    return params


def validate_credentials(environment: str, access_id: str, access_token: str) -> bool:
    """Confirm the access ID/token pair is valid with a one-row agents listing."""
    ok, _status = validate_via_probe(
        lambda: _make_session(access_id, access_token),
        f"{_base_url(environment)}/agents",
        headers=_get_headers(access_id, access_token),
    )
    return ok


def babelforce_source(
    environment: str,
    access_id: str,
    access_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BabelforceResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = BABELFORCE_ENDPOINTS[endpoint]

    initial_paginator_state: Optional[dict[str, Any]] = None
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None:
        # Reuse the saved window and page so the resumed run continues the identical query.
        params = dict(resume.params)
        initial_paginator_state = {"next_page": resume.next_page}
    else:
        from_timestamp = _to_epoch(db_incremental_field_last_value) if should_use_incremental_field else None
        to_timestamp = int(time.time()) if config.supports_date_created_filter else None
        params = _build_params(config, from_timestamp, to_timestamp)

    session = _make_session(access_id, access_token)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": _base_url(environment),
            "headers": {"Accept": "application/json"},
            "auth": BabelforceAuth(access_id, access_token),
            # Pre-built session so responses (SMS bodies, phone numbers, recording URLs) stay out
            # of sample capture and both credentials are value-redacted; redirects are pinned off.
            "session": session,
            "allow_redirects": False,
            "paginator": BabelforcePaginator(),
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    "data_selector": "items",
                },
            }
        ],
    }

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only while a next page remains; save AFTER the page is yielded so a crash
        # re-yields the last page (merge dedupes on primary key) rather than skipping it.
        if state and state.get("next_page") is not None:
            resumable_source_manager.save_state(
                BabelforceResumeConfig(next_page=int(state["next_page"]), params=params)
            )

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        # The date window is baked into ``params`` above (frozen at sync start), so the framework's
        # server-side incremental injection is intentionally not used.
        db_incremental_field_last_value=None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=[config.primary_key],
        # The reporting API doesn't document a sort order or expose a sort param, so we can't
        # assume ascending arrival. "desc" makes the pipeline finalize the incremental watermark
        # only after a fully successful sync, which is correct for any actual ordering; the
        # server-side dateCreated window bounds what each run re-reads.
        sort_mode="desc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )
