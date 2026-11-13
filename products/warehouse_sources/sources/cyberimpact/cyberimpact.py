from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

from requests import Request, Response
from requests.exceptions import RequestException

from products.warehouse_sources.sources.cyberimpact.settings import (
    BASE_URL,
    CYBERIMPACT_ENDPOINTS,
    DATE_PARAMS,
    CyberimpactEndpointConfig,
)
from products.warehouse_sources.sources.sdk import (
    BasePaginator,
    ClientConfig,
    EndpointResource,
    PageNumberPaginator,
    RESTAPIConfig,
    ResumableSourceManager,
    SinglePagePaginator,
    SourceResponse,
    build_dependent_resource,
    capture_exception,
    frozen,
    make_tracked_session,
    rest_api_resource,
)

INVALID_TOKEN_ERROR = (
    "Cyberimpact rejected your API token. The token may have expired or been deleted. "
    "Create a new token in Cyberimpact under Settings > API tokens, then reconnect the source."
)
UNREACHABLE_ERROR = "PostHog couldn't reach Cyberimpact to check your API token. Wait a few minutes, then try again."
UNVERIFIED_TOKEN_ERROR = "PostHog couldn't verify your Cyberimpact API token. Check the token, then try again."

# (connect, read) seconds for the one-request credential probe.
PROBE_TIMEOUT = (10, 30)

# The date filters take a day in the account's time zone, which the API does not report. Starting one
# day before the watermark's UTC date covers every offset; the merge drops the rows read twice.
INCREMENTAL_LOOKBACK = timedelta(days=1)


@frozen
class CyberimpactResumeConfig:
    # Top-level listings: the next page to fetch and, for a member walk with several filters, which one.
    page: Optional[int] = None
    phase: int = 0
    # Fan-out tables: the state `build_dependent_resource` checkpoints over the parent listing.
    fanout_state: Optional[dict[str, Any]] = None


class CyberimpactPaginator(PageNumberPaginator):
    """Walks `page` until the pages cover `totalCount`, or until a page comes back empty.

    `phases` are alternative filter param sets. The paginator reads them one after another, each
    from page 1, in the same request series.
    """

    def __init__(self, phases: Sequence[Mapping[str, Any]] = ()) -> None:
        super().__init__(base_page=1, page_param="page")
        self.phases = [dict(phase) for phase in phases]
        self.phase = 0

    def _apply(self, request: Request) -> None:
        if self.phases:
            params = dict(request.params or {})
            for phase in self.phases:
                for key in phase:
                    params.pop(key, None)
            params.update(self.phases[self.phase])
            request.params = params
        super().update_request(request)

    def init_request(self, request: Request) -> None:
        self._apply(request)

    def update_request(self, request: Request) -> None:
        self._apply(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if data and not self._is_last_page(response):
            self.page += 1
            self._has_next_page = True
        elif self.phase + 1 < len(self.phases):
            self.phase += 1
            self.page = self.base_page
            self._has_next_page = True
        else:
            self._has_next_page = False

    def _is_last_page(self, response: Response) -> bool:
        try:
            body = response.json()
        except ValueError:
            return False
        if not isinstance(body, dict):
            return False
        total, limit = body.get("totalCount"), body.get("limit")
        if not isinstance(total, int) or not isinstance(limit, int) or limit <= 0:
            return False
        return self.page * limit >= total

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"page": self.page, "phase": self.phase} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        super().set_resume_state(state)
        phase = state.get("phase")
        if isinstance(phase, int) and 0 <= phase < max(len(self.phases), 1):
            self.phase = phase


def clean_token(api_token: str) -> str:
    token = api_token.strip()
    if token.lower().startswith("bearer "):
        token = token[len("bearer ") :].strip()
    return token


def _client_config(api_token: str) -> ClientConfig:
    return {
        "base_url": BASE_URL,
        "auth": {"type": "bearer", "token": clean_token(api_token)},
        # The bearer token must never follow a redirect to another host.
        "allowed_hosts": [],
        "allow_redirects": False,
    }


def _paginator(config: CyberimpactEndpointConfig, phases: Sequence[Mapping[str, Any]] = ()) -> BasePaginator:
    return CyberimpactPaginator(phases) if config.paginated else SinglePagePaginator()


def _filter_day(value: Any) -> Optional[str]:
    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=UTC)
        day = moment.astimezone(UTC).date()
    elif isinstance(value, date):
        day = value
    elif isinstance(value, str) and value:
        try:
            return _filter_day(datetime.fromisoformat(value))
        except ValueError:
            return None
    else:
        return None
    return (day - INCREMENTAL_LOOKBACK).isoformat()


def member_phases(should_use_incremental_field: bool, db_incremental_field_last_value: Any) -> list[dict[str, Any]]:
    """The filter passes of a member walk.

    Sorting by join date keeps the page walk stable: an update during the walk does not move a row.
    A member that was never edited can have a null `updatedOn`, which the `updatedOnFrom` filter
    leaves out, so an incremental run reads the members that joined since the watermark too.
    """
    day = _filter_day(db_incremental_field_last_value) if should_use_incremental_field else None
    if day is None:
        return [{"sort": "date_asc"}]
    return [
        {"sort": "date_asc", "updatedOnFrom": day},
        {"sort": "date_asc", "joinedOnFrom": day},
    ]


def get_resource(
    config: CyberimpactEndpointConfig, should_use_incremental_field: bool, phases: Sequence[Mapping[str, Any]]
) -> EndpointResource:
    params: dict[str, Any] = {**config.params, **DATE_PARAMS}
    if config.paginated:
        params["limit"] = config.page_size
    use_merge = should_use_incremental_field and bool(config.incremental_fields)
    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"} if use_merge else "replace",
        "endpoint": {
            "path": config.path,
            "params": params,
            "data_selector": config.data_selector,
            "data_selector_required": config.data_selector is not None,
            "paginator": _paginator(config, phases),
        },
        "table_format": "delta",
    }


def _initial_paginator_state(resume_state: Optional[CyberimpactResumeConfig]) -> Optional[dict[str, Any]]:
    if resume_state is None or resume_state.page is None:
        return None
    return {"page": resume_state.page, "phase": resume_state.phase}


def _save_paginator_state(
    manager: ResumableSourceManager[CyberimpactResumeConfig], state: Optional[dict[str, Any]]
) -> None:
    if state and state.get("page") is not None:
        manager.save_state(CyberimpactResumeConfig(page=int(state["page"]), phase=int(state.get("phase") or 0)))


def _save_fanout_state(
    manager: ResumableSourceManager[CyberimpactResumeConfig], state: Optional[dict[str, Any]]
) -> None:
    if state:
        manager.save_state(CyberimpactResumeConfig(fanout_state=state))


def cyberimpact_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CyberimpactResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    config = CYBERIMPACT_ENDPOINTS.get(endpoint)
    if config is None:
        raise ValueError(f"Unknown Cyberimpact endpoint: {endpoint}")

    client_config = _client_config(api_token)
    resume_state = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    response_kwargs: dict[str, Any] = {
        "name": config.name,
        "primary_keys": config.primary_keys,
        "partition_mode": "datetime" if config.partition_key else None,
        "partition_format": "month" if config.partition_key else None,
        "partition_keys": [config.partition_key] if config.partition_key else None,
    }

    if config.fanout is not None:
        parent_config = CYBERIMPACT_ENDPOINTS[config.fanout.parent_name]
        child = build_dependent_resource(
            endpoint_configs=CYBERIMPACT_ENDPOINTS,
            child_endpoint=endpoint,
            fanout=config.fanout,
            client_config=client_config,
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            # Page sizes go in the fan-out params, because the single-mailing endpoint takes none.
            page_size_param=None,
            parent_endpoint_extra={
                "data_selector": parent_config.data_selector,
                "data_selector_required": True,
                "paginator": _paginator(parent_config),
            },
            child_endpoint_extra={
                "data_selector": config.data_selector,
                "data_selector_required": config.data_selector is not None,
                "paginator": _paginator(config),
            },
            resume_hook=lambda state: _save_fanout_state(resumable_source_manager, state),
            initial_paginator_state=resume_state.fanout_state if resume_state else None,
            # The parent listing can save its page, so a resume starts there instead of keeping every
            # finished parent in the state.
            resume_parent_pagination=True,
        )
        return SourceResponse(items=lambda: child, **response_kwargs)

    phases = (
        member_phases(should_use_incremental_field, db_incremental_field_last_value)
        if config.incremental_fields
        else []
    )
    rest_config: RESTAPIConfig = {
        "client": client_config,
        "resource_defaults": {},
        "resources": [get_resource(config, should_use_incremental_field, phases)],
    }
    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=lambda state: _save_paginator_state(resumable_source_manager, state),
        initial_paginator_state=_initial_paginator_state(resume_state),
    )
    return SourceResponse(items=lambda: resource, column_hints=resource.column_hints, **response_kwargs)


def validate_credentials(api_token: str) -> tuple[bool, str | None]:
    token = clean_token(api_token)
    if not token:
        return False, INVALID_TOKEN_ERROR

    session = make_tracked_session(redact_values=(token,))
    try:
        response = session.get(
            f"{BASE_URL}/ping",
            headers={"Authorization": f"Bearer {token}"},
            allow_redirects=False,
            timeout=PROBE_TIMEOUT,
        )
    except RequestException:
        return False, UNREACHABLE_ERROR

    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return False, INVALID_TOKEN_ERROR
    capture_exception(Exception(f"Unexpected Cyberimpact credential validation response ({response.status_code})"))
    return False, UNVERIFIED_TOKEN_ERROR
