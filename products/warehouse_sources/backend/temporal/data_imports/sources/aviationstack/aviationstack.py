import datetime
import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.aviationstack.settings import (
    AVIATIONSTACK_ENDPOINTS,
    FLIGHTS_FUTURE_DEFAULT_DAYS,
    FLIGHTS_FUTURE_FIRST_DAY_AHEAD,
    FLIGHTS_FUTURE_MAX_DAYS,
    MAX_AIRPORTS,
    SCHEDULE_TYPES,
    AviationstackEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    ResponseAction,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

AVIATIONSTACK_BASE_URL = "https://api.aviationstack.com/v1"
DEFAULT_PAGE_SIZE = 100

# The per-airport feeds allow one request every 10s (paid) or 60s (free), so a throttled page has to
# be able to wait out a whole window. The client's default budget (5 attempts, doubling from 1s)
# tops out at 15s of waiting, which clears neither window.
THROTTLED_RETRY_ATTEMPTS = 8
THROTTLED_RETRY_BACKOFF_MAX_SECONDS = 70.0

# Every IATA airport code is exactly three letters; anything else is junk we should not request.
IATA_CODE_LENGTH = 3

# aviationstack returns HTTP 200 with an error envelope (`{"error": {"code": ...}}`). The single
# transient body code is retried in-process; every listed permanent code (bad/blocked key, plan
# gating, exhausted monthly quota) fails fast and is surfaced with a stable `[code]` token matched by
# AviationstackSource.get_non_retryable_errors. An unrecognized error code has no `data` key, so the
# framework fails loud on the missing selector (data_selector_required) rather than syncing 0 rows.
_RETRYABLE_BODY_CODE = "rate_limit_reached"
_PERMANENT_BODY_CODES = (
    "invalid_access_key",
    "missing_access_key",
    "inactive_user",
    "function_access_restricted",
    "https_access_restricted",
    "usage_limit_reached",
)


@dataclasses.dataclass(frozen=True)
class AviationstackResumeConfig:
    # Offset of the next page to fetch — aviationstack uses limit/offset pagination.
    next_offset: int
    # Position in the per-airport request plan to pick back up from. Always 0 for the endpoints that
    # take a single request.
    next_request_index: int = 0
    # First lookahead date of the plan the index refers to, so a resume rebuilds the same plan.
    plan_start_date: str | None = None


@dataclasses.dataclass(frozen=True)
class AviationstackRequest:
    """One (airport, schedule type, date) request in a per-airport endpoint's fan-out plan."""

    params: dict[str, str]
    # Which airport/type/date produced a row. /flightsFuture rows carry a weekday and a wall-clock
    # time but no date, so without this the future schedule cannot be placed on a calendar at all.
    row_context: dict[str, str]


def parse_iata_codes(raw: str | None) -> list[str]:
    """Split the user's airport list into upper-case IATA codes, dropping junk and duplicates."""
    if not raw:
        return []

    codes: list[str] = []
    seen: set[str] = set()
    for token in raw.replace("\n", ",").replace(" ", ",").split(","):
        code = token.strip().upper()
        if len(code) != IATA_CODE_LENGTH or not code.isascii() or not code.isalpha() or code in seen:
            continue
        seen.add(code)
        codes.append(code)
        # Stop at the cap rather than walking a list of any length just to truncate it after.
        if len(codes) == MAX_AIRPORTS:
            break
    return codes


def _future_dates(days: int | None, today: datetime.date | None = None) -> list[str]:
    window = FLIGHTS_FUTURE_DEFAULT_DAYS if days is None else days
    window = max(1, min(window, FLIGHTS_FUTURE_MAX_DAYS))
    start = (today or datetime.datetime.now(datetime.UTC).date()) + datetime.timedelta(
        days=FLIGHTS_FUTURE_FIRST_DAY_AHEAD
    )
    return [(start + datetime.timedelta(days=offset)).isoformat() for offset in range(window)]


def build_request_plan(
    config: AviationstackEndpointConfig,
    iata_codes: list[str],
    flights_future_days: int | None = None,
    today: datetime.date | None = None,
) -> list[AviationstackRequest]:
    if not config.per_airport:
        return [AviationstackRequest(params={}, row_context={})]

    dates = _future_dates(flights_future_days, today) if config.needs_date else [None]
    plan: list[AviationstackRequest] = []
    for code in iata_codes:
        for schedule_type in SCHEDULE_TYPES:
            for date in dates:
                params = {"iataCode": code, "type": schedule_type}
                context = {"queried_iata_code": code, "queried_type": schedule_type}
                if date is not None:
                    params["date"] = date
                    context["queried_date"] = date
                plan.append(AviationstackRequest(params=params, row_context=context))
    return plan


def _response_actions() -> list[ResponseAction]:
    # The `content` matches the quoted error code as it appears in the JSON body, independent of
    # whitespace around the colon. Retryable code first; each permanent code raises a secret-free,
    # non-retryable error whose message carries the `[code]` token get_non_retryable_errors matches.
    actions: list[ResponseAction] = [
        {
            "content": f'"{_RETRYABLE_BODY_CODE}"',
            "action": "retry",
            "message": f"aviationstack API error (retryable) [{_RETRYABLE_BODY_CODE}]",
        }
    ]
    actions.extend(
        {
            "content": f'"{code}"',
            "action": "raise",
            "message": f"aviationstack API error [{code}]",
        }
        for code in _PERMANENT_BODY_CODES
    )
    # aviationstack also returns hard 401/403 for a bad key / plan gating. Author a secret-free
    # message (the access_key rides in the query string, so a bare raise_for_status would leak it)
    # that still matches the stable host prefix in get_non_retryable_errors.
    actions.append(
        {
            "status_code": 401,
            "action": "raise",
            "message": "401 Client Error: Unauthorized for url: https://api.aviationstack.com",
        }
    )
    actions.append(
        {
            "status_code": 403,
            "action": "raise",
            "message": "403 Client Error: Forbidden for url: https://api.aviationstack.com",
        }
    )
    return actions


def _rest_config(access_key: str, config: AviationstackEndpointConfig, params: dict[str, str]) -> RESTAPIConfig:
    client: ClientConfig = {
        "base_url": AVIATIONSTACK_BASE_URL,
        # access_key rides in the query string; the framework auth redacts its value from every
        # logged URL, captured sample, and raised error message.
        "auth": {"type": "api_key", "api_key": access_key, "name": "access_key", "location": "query"},
        "paginator": OffsetPaginator(limit=DEFAULT_PAGE_SIZE, total_path="pagination.total"),
    }
    if config.throttled:
        client["max_retries"] = THROTTLED_RETRY_ATTEMPTS
        client["retry_backoff_max_seconds"] = THROTTLED_RETRY_BACKOFF_MAX_SECONDS

    endpoint: Endpoint = {
        "path": config.path,
        "data_selector": "data",
        # A 200 body without `data` means an error envelope (recognized codes are caught
        # by response_actions first) or a changed shape — fail loud, don't sync 0 rows.
        "data_selector_required": True,
        "response_actions": _response_actions(),
    }
    if params:
        endpoint["params"] = dict(params)

    return {"client": client, "resources": [{"name": config.name, "endpoint": endpoint}]}


def _plan_anchor(resume: Optional[AviationstackResumeConfig]) -> Optional[datetime.date]:
    """Recover the date the saved plan was built from, so a resumed run rebuilds the same plan.

    The lookahead dates are derived from "today", so a job resumed after a UTC midnight would
    otherwise shift its window by a day and skip whichever date the crash interrupted.
    """
    if resume is None or not resume.plan_start_date:
        return None
    try:
        first_date = datetime.date.fromisoformat(resume.plan_start_date)
    except ValueError:
        return None
    return first_date - datetime.timedelta(days=FLIGHTS_FUTURE_FIRST_DAY_AHEAD)


def aviationstack_source(
    access_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[AviationstackResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
    airport_iata_codes: Optional[str] = None,
    flights_future_days: Optional[int] = None,
) -> SourceResponse:
    config = AVIATIONSTACK_ENDPOINTS[endpoint]
    iata_codes = parse_iata_codes(airport_iata_codes)

    if config.per_airport and not iata_codes:
        raise ValueError(
            f"The {endpoint} table needs at least one airport. Add an airport IATA code to the "
            "source settings, then sync again."
        )

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    plan = build_request_plan(config, iata_codes, flights_future_days, today=_plan_anchor(resume))
    plan_start_date = plan[0].row_context.get("queried_date") if config.needs_date else None

    def items() -> Iterator[list[dict[str, Any]]]:
        start_index = min(resume.next_request_index, len(plan) - 1) if resume is not None else 0

        for index in range(start_index, len(plan)):
            request = plan[index]

            initial_paginator_state: Optional[dict[str, Any]] = None
            if resume is not None and index == start_index and resume.next_offset:
                initial_paginator_state = {"offset": resume.next_offset}

            def save_checkpoint(state: Optional[dict[str, Any]], _index: int = index) -> None:
                # Persist only while work remains; save AFTER a page is yielded so a crash re-yields
                # the last page (merge/replace dedupes) rather than skipping it.
                if state and state.get("offset") is not None:
                    next_state = AviationstackResumeConfig(
                        next_offset=int(state["offset"]),
                        next_request_index=_index,
                        plan_start_date=plan_start_date,
                    )
                elif _index + 1 < len(plan):
                    # This request is exhausted, so a resumed attempt starts at the next one.
                    next_state = AviationstackResumeConfig(
                        next_offset=0, next_request_index=_index + 1, plan_start_date=plan_start_date
                    )
                else:
                    return
                resumable_source_manager.save_state(next_state)

            resource = rest_api_resource(
                _rest_config(access_key, config, request.params),
                team_id,
                job_id,
                db_incremental_field_last_value,
                resume_hook=save_checkpoint,
                initial_paginator_state=initial_paginator_state,
            )

            for page in resource:
                yield [row | request.row_context for row in page] if request.row_context else page

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=config.primary_keys,
    )


def validate_credentials(access_key: str) -> bool:
    # `/countries` is a static reference endpoint available on every plan (including free), so it's a
    # cheap probe that the access key is genuine without depending on a paid-tier endpoint. A bad key
    # can surface either as a non-200 status or as an HTTP 200 with a body-level error envelope, so
    # both are checked here (validate_via_probe only inspects the status).
    url = f"{AVIATIONSTACK_BASE_URL}/countries"
    params: dict[str, Any] = {"access_key": access_key, "limit": 1}
    try:
        session = make_tracked_session(redact_values=(access_key,))
        response = session.get(url, params=params, timeout=10)
    except Exception:
        return False

    if response.status_code != 200:
        return False

    try:
        body = response.json()
    except ValueError:
        return False

    return not (isinstance(body, dict) and bool(body.get("error")))
