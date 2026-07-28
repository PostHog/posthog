import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

from requests import Request, Response
from requests.auth import HTTPBasicAuth
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.chargedesk.settings import (
    CHARGEDESK_ENDPOINTS,
    ChargedeskEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe

CHARGEDESK_BASE_URL = "https://api.chargedesk.com/v1"


@dataclasses.dataclass
class ChargedeskResumeConfig:
    # ChargeDesk has no opaque page cursor — pagination is purely `offset` within a `[max]`-bounded window,
    # so resuming only needs the next offset and the current upper time bound.
    offset: int = 0
    window_max: int | None = None
    # Which pass we were in when state was saved. An incremental sync against a newest-first API runs an
    # "earliest" backfill (rows older than what we have) followed by a "latest" pass (rows newer than the
    # watermark); "full" is the first/full-refresh scan. Tracking the phase lets a resume pick up the right
    # pass instead of restarting the whole sync.
    phase: str = "full"


class ChargedeskOffsetWindowPaginator(BasePaginator):
    """Offset pagination within a ``[max]``-bounded time window.

    ChargeDesk list endpoints return rows newest first and reject an ``offset`` past a per-endpoint
    cap. When the next page would step past the cap we reset the offset to 0 and pin
    ``<filter>[max]`` to the oldest timestamp seen so far, as the docs recommend (the boundary row
    is re-fetched and deduped on the primary key by the merge). A short page (fewer rows than
    requested) means there's nothing after it in this window.
    """

    def __init__(
        self,
        cfg: ChargedeskEndpointConfig,
        logger: Optional[FilteringBoundLogger] = None,
        offset: int = 0,
        window_max: int | None = None,
    ) -> None:
        super().__init__()
        self._cfg = cfg
        self._logger = logger
        self.offset = offset
        self.window_max = window_max

    def __deepcopy__(self, memo: dict[int, Any]) -> "ChargedeskOffsetWindowPaginator":
        # RESTClient deep-copies the paginator per paginate() call; share the logger (structlog
        # loggers may hold uncopyable handles) and copy only the pagination state.
        clone = ChargedeskOffsetWindowPaginator(
            self._cfg, logger=self._logger, offset=self.offset, window_max=self.window_max
        )
        clone._has_next_page = self._has_next_page
        return clone

    def _warn(self, message: str) -> None:
        if self._logger is not None:
            self._logger.warning(message)

    def _inject(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["count"] = self._cfg.page_size
        request.params["offset"] = self.offset
        if self.window_max is not None:
            request.params[f"{self._cfg.filter_param}[max]"] = self.window_max

    def init_request(self, request: Request) -> None:
        self._inject(request)

    def update_request(self, request: Request) -> None:
        self._inject(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        items = data or []

        # A short page (fewer rows than requested) means there's nothing after it in this window.
        if len(items) < self._cfg.page_size:
            self._has_next_page = False
            return

        next_offset = self.offset + self._cfg.page_size

        if next_offset + self._cfg.page_size > self._cfg.max_offset:
            cfg = self._cfg
            oldest_ts = items[-1].get(cfg.timestamp_field)
            if not isinstance(oldest_ts, int):
                # Can't shift the window without a timestamp to anchor it, and stepping past the cap would
                # 400. Surface it rather than silently dropping the tail.
                self._warn(
                    f"ChargeDesk: {cfg.name} hit the offset cap ({cfg.max_offset}) but the last row has no "
                    f"usable '{cfg.timestamp_field}' to continue from; stopping pagination for this window."
                )
                self._has_next_page = False
                return
            if oldest_ts == self.window_max:
                # The whole offset window collapsed onto a single timestamp: more than `max_offset` rows
                # share `oldest_ts`, so re-pinning `[max]` to the same value would re-fetch this exact page
                # forever (offset can't advance past the cap). Surface it and stop rather than spin until
                # Temporal kills the activity. The unreachable tail is a hard limitation of an offset+`[max]`
                # API when a single timestamp exceeds the offset cap.
                self._warn(
                    f"ChargeDesk: {cfg.name} has more than {cfg.max_offset} rows at {cfg.timestamp_field}="
                    f"{oldest_ts}; the offset cap prevents fetching the rest of this timestamp, stopping "
                    f"pagination for this window."
                )
                self._has_next_page = False
                return
            if self._logger is not None:
                self._logger.debug(
                    f"ChargeDesk: {cfg.name} reached offset cap, shifting {cfg.filter_param}[max] to {oldest_ts}"
                )
            self.offset = 0
            self.window_max = oldest_ts
        else:
            self.offset = next_offset

        self._has_next_page = True

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        # offset/window_max already point at the next page to fetch (update_state advanced them).
        return {"offset": self.offset, "window_max": self.window_max} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        offset = state.get("offset")
        if offset is not None:
            self.offset = int(offset)
        window_max = state.get("window_max")
        if window_max is not None:
            self.window_max = int(window_max)
        self._has_next_page = True

    def __str__(self) -> str:
        return f"ChargedeskOffsetWindowPaginator(offset={self.offset}, window_max={self.window_max})"


def _run_pass(
    api_key: str,
    cfg: ChargedeskEndpointConfig,
    team_id: int,
    job_id: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: "ResumableSourceManager[ChargedeskResumeConfig]",
    *,
    phase: str,
    min_value: int | None,
    start_offset: int,
    start_window_max: int | None,
) -> Iterator[list[dict[str, Any]]]:
    """Run a single pass over a list endpoint, saving resume state at page boundaries.

    State is saved AFTER a page is yielded (framework contract), tagged with the current phase so
    a resume picks up the right pass. The terminal page carries no state, matching the old
    behavior of never checkpointing past the end of a pass.
    """
    params: dict[str, Any] = {}
    if min_value is not None:
        params[f"{cfg.filter_param}[min]"] = min_value

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": CHARGEDESK_BASE_URL,
            # HTTP Basic with the secret key as the username and an empty password.
            "auth": {"type": "http_basic", "username": api_key, "password": ""},
            "paginator": ChargedeskOffsetWindowPaginator(cfg, logger=logger),
        },
        "resources": [
            {
                "name": cfg.name,
                "endpoint": {
                    "path": cfg.path,
                    "params": params,
                    "data_selector": "data",
                },
            }
        ],
    }

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when a next page remains; a crash re-yields the last page (merge dedupes)
        # rather than skipping it.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(
                ChargedeskResumeConfig(offset=int(state["offset"]), window_max=state.get("window_max"), phase=phase)
            )

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state={"offset": start_offset, "window_max": start_window_max},
    )

    yield from resource


def get_rows(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: "ResumableSourceManager[ChargedeskResumeConfig]",
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    db_incremental_field_earliest_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    cfg = CHARGEDESK_ENDPOINTS[endpoint]

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    incremental = should_use_incremental_field and cfg.supports_incremental
    no_watermark = db_incremental_field_last_value is None and db_incremental_field_earliest_value is None

    if not incremental or no_watermark:
        start_offset, window_max = (
            (resume.offset, resume.window_max) if resume and resume.phase == "full" else (0, None)
        )
        yield from _run_pass(
            api_key,
            cfg,
            team_id,
            job_id,
            logger,
            resumable_source_manager,
            phase="full",
            min_value=None,
            start_offset=start_offset,
            start_window_max=window_max,
        )
    else:
        # Newest-first incremental: first walk older rows we don't have yet (bounded by the earliest value
        # we've synced), then the rows newer than our watermark. Skip the earliest pass entirely if a resume
        # tells us we already finished it.
        if db_incremental_field_earliest_value is not None and (resume is None or resume.phase == "earliest"):
            if resume is not None and resume.phase == "earliest":
                start_offset, window_max = resume.offset, resume.window_max
            else:
                start_offset, window_max = 0, int(db_incremental_field_earliest_value)
            yield from _run_pass(
                api_key,
                cfg,
                team_id,
                job_id,
                logger,
                resumable_source_manager,
                phase="earliest",
                min_value=None,
                start_offset=start_offset,
                start_window_max=window_max,
            )

        if db_incremental_field_last_value is not None:
            if resume is not None and resume.phase == "latest":
                start_offset, window_max = resume.offset, resume.window_max
            else:
                start_offset, window_max = 0, None
            yield from _run_pass(
                api_key,
                cfg,
                team_id,
                job_id,
                logger,
                resumable_source_manager,
                phase="latest",
                min_value=int(db_incremental_field_last_value),
                start_offset=start_offset,
                start_window_max=window_max,
            )


def chargedesk_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: "ResumableSourceManager[ChargedeskResumeConfig]",
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    db_incremental_field_earliest_value: Optional[Any] = None,
) -> SourceResponse:
    cfg = CHARGEDESK_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            team_id=team_id,
            job_id=job_id,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            db_incremental_field_earliest_value=db_incremental_field_earliest_value,
        ),
        primary_keys=cfg.primary_keys,
        # ChargeDesk list endpoints return rows newest first (offset 0 is the most recent; the docs
        # recommend paginating earlier with `[max]`). Matches the newest-first contract Stripe uses.
        sort_mode="desc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="week",
        partition_keys=[cfg.timestamp_field],
    )


def validate_credentials(api_key: str) -> bool:
    # A single company secret key grants full read access (ChargeDesk has no per-resource scopes), so one
    # cheap probe against /charges confirms the key is genuine. The key rides in the Basic auth header, so
    # register it for value-based redaction in logged URLs / captured samples.
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{CHARGEDESK_BASE_URL}/charges?count=1",
        auth=HTTPBasicAuth(api_key, ""),
    )
    return ok
