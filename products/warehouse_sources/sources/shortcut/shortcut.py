import logging
from collections.abc import Iterable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional, cast

from requests import Request, Response

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    EndpointResource,
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SortMode, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.shortcut.settings import (
    SHORTCUT_ENDPOINTS,
    ShortcutEndpointConfig,
)

logger = logging.getLogger(__name__)

SHORTCUT_BASE_URL = "https://api.app.shortcut.com/api/v3"

# `POST /stories/search` returns nothing for an empty body, so full refresh and the first
# incremental run send this created_at floor to match every story. It is also the start of the
# first created_at window the paginator fetches.
STORY_SEARCH_EPOCH_START = "1970-01-01T00:00:00Z"

# `POST /stories/search` returns a bare array and documents no result cap, no result order, and no
# pagination. The paginator therefore never trusts one response to be complete. A response with at
# least this many stories is treated as possibly truncated, and its created_at window is split in
# two and fetched again. The value only sets how eagerly windows split: completeness does not
# depend on it, because the paginator also re-fetches the largest accepted windows in halves and
# lowers this threshold when the halves hold more stories than the parent did.
STORY_SEARCH_SPLIT_THRESHOLD = 1000

_SEARCH_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _base_headers() -> dict[str, str]:
    # The Shortcut-Token credential is supplied via the framework api_key auth (location="header"),
    # so its value is redacted from logs and raised errors; only the non-secret content headers here.
    return {"Content-Type": "application/json", "Accept": "application/json"}


def _format_incremental_value(value: Any) -> str:
    """Format an incremental cursor value for Shortcut's `*_start` search filters (RFC 3339)."""
    if isinstance(value, datetime):
        utc_dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return utc_dt.strftime(_SEARCH_TIMESTAMP_FORMAT)
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return str(value)


def _parse_search_timestamp(value: Any) -> datetime | None:
    """Read a `created_at_start` filter back into an aware UTC datetime, or None if it is not one."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _build_search_body(
    config: ShortcutEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    """Build the JSON body for `POST /stories/search`.

    Maps the user-selected incremental field to the matching server-side filter param, and
    always sets a created_at floor so the body is never empty — an empty body makes the
    endpoint return zero stories on full refresh and the first incremental run.
    """
    body: dict[str, Any] = {}
    # GET list endpoints carry no request body.
    if config.method != "POST":
        return body
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        field_name = incremental_field or "updated_at"
        param = config.incremental_params.get(field_name)
        if param:
            body[param] = _format_incremental_value(db_incremental_field_last_value)
    # An epoch floor matches every story; a real created_at cursor above overrides it.
    body.setdefault("created_at_start", STORY_SEARCH_EPOCH_START)
    # StorySlim omits the description unless asked; the canonical schema advertises the column.
    body["includes_description"] = True
    return body


class _SplitCheck:
    """One verification split: the parent's story count, and what its two halves return."""

    def __init__(self, parent_count: int) -> None:
        self.parent_count = parent_count
        self.ids: set[Any] = set()
        self.halves: list[tuple[_CreatedAtWindow, int]] = []

    @property
    def complete(self) -> bool:
        return len(self.halves) == 2

    @property
    def proves_truncation(self) -> bool:
        # A complete parent response holds every story of both halves, so the halves cannot add
        # up to more than it. Boundary re-reads are counted once through the id set.
        return len(self.ids) > self.parent_count


@frozen
class _CreatedAtWindow:
    """A closed `created_at` range sent as `created_at_start` / `created_at_end`."""

    start: datetime
    end: datetime
    # Set when this window is one half of a verification split.
    check: _SplitCheck | None = None

    def halves(self, check: _SplitCheck | None = None) -> list["_CreatedAtWindow"] | None:
        """Split around the midpoint second, or return None when the window is too narrow to split.

        The halves overlap by one second on each side of the midpoint, so no story is lost whether
        the endpoint treats either bound as inclusive or exclusive. Stories in the overlap are read
        twice; `_dedupe_pages_by_id` drops the second copy.
        """
        span_seconds = int((self.end - self.start).total_seconds())
        if span_seconds < 3:
            return None
        midpoint = self.start + timedelta(seconds=span_seconds // 2)
        return [
            _CreatedAtWindow(start=self.start, end=midpoint + timedelta(seconds=1), check=check),
            _CreatedAtWindow(start=midpoint, end=self.end, check=check),
        ]


class StoriesSearchPaginator(BasePaginator):
    """Read every story from `POST /stories/search` without trusting an undocumented cap or order.

    The endpoint returns a bare array with no pagination. It documents neither how many stories a
    response holds at most nor the order they come in, so this paginator only relies on the
    `created_at_start` / `created_at_end` filters and on story ids:

    - Each request covers one closed `created_at` window. The first window runs from the body's
      `created_at_start` floor to the moment the sync started.
    - A response with at least `split_threshold` stories may be truncated. Its window is split in
      two and both halves are fetched. A window under three seconds wide cannot split; it is
      kept and a warning is logged.
    - Once every window is fetched, the accepted windows with the most stories are fetched again in
      halves. If the halves hold more distinct stories than the parent response did, the endpoint
      truncated at the parent's count. The threshold drops to that count and every accepted window
      at or above it is split again. A half that returns as many stories as its parent is verified
      in turn, so a truncated parent whose stories all sit in one half cannot pass.

    Row order never matters, and the threshold only sets how many requests a large workspace costs.
    Stories created after the sync started are picked up by the next run.
    """

    def __init__(
        self,
        primary_key: str = "id",
        split_threshold: int = STORY_SEARCH_SPLIT_THRESHOLD,
        now: datetime | None = None,
    ) -> None:
        super().__init__()
        self._primary_key = primary_key
        self._threshold = split_threshold
        end = (now or datetime.now(UTC)).replace(microsecond=0)
        self._current = _CreatedAtWindow(start=_EPOCH, end=max(_EPOCH, end))
        self._pending: list[_CreatedAtWindow] = []
        # Windows fetched in full with the distinct story count each returned. Only these can be
        # split again when the threshold drops; unsplittable windows are not kept.
        self._accepted: list[tuple[_CreatedAtWindow, int]] = []
        self._verified_largest = False

    def init_request(self, request: Request) -> None:
        body = request.json if isinstance(request.json, dict) else {}
        floor = _parse_search_timestamp(body.get("created_at_start")) or _EPOCH
        self._current = _CreatedAtWindow(start=floor, end=max(floor, self._current.end))
        self._apply_window(request, self._current)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        window = self._current
        rows = data or []
        ids = {row.get(self._primary_key) for row in rows if isinstance(row, dict)}
        ids.discard(None)
        count = len(ids)

        if count >= self._threshold:
            self._split(window)
        else:
            self._accepted.append((window, count))
        if window.check is not None:
            self._record_half(window, count, ids)
        if not self._pending and not self._verified_largest:
            self._verified_largest = True
            self._verify_largest_windows()
        self._has_next_page = bool(self._pending)

    def update_request(self, request: Request) -> None:
        if not self._pending:
            return
        self._current = self._pending.pop()
        self._apply_window(request, self._current)

    def _apply_window(self, request: Request, window: _CreatedAtWindow) -> None:
        body = request.json if isinstance(request.json, dict) else {}
        body["created_at_start"] = _format_incremental_value(window.start)
        body["created_at_end"] = _format_incremental_value(window.end)
        request.json = body

    def _split(self, window: _CreatedAtWindow) -> None:
        halves = window.halves()
        if halves is None:
            logger.warning(
                "Shortcut stories/search returned at least %s stories created between %s and %s; the window cannot "
                "be split further, so some stories in it may be missing",
                self._threshold,
                _format_incremental_value(window.start),
                _format_incremental_value(window.end),
            )
            return
        self._pending.extend(halves)

    def _verify_window(self, window: _CreatedAtWindow, count: int) -> None:
        halves = window.halves(check=_SplitCheck(count))
        if halves is None:
            logger.warning(
                "Shortcut stories/search returned %s stories created between %s and %s; the window cannot be split "
                "to confirm the response was complete",
                count,
                _format_incremental_value(window.start),
                _format_incremental_value(window.end),
            )
            return
        self._accepted = [(accepted, n) for accepted, n in self._accepted if accepted is not window]
        self._pending.extend(halves)

    def _verify_largest_windows(self) -> None:
        largest = max((count for _, count in self._accepted), default=0)
        if largest == 0:
            return
        for window, count in list(self._accepted):
            if count == largest:
                self._verify_window(window, count)

    def _record_half(self, window: _CreatedAtWindow, count: int, ids: set[Any]) -> None:
        check = window.check
        if check is None:
            return
        check.ids |= ids
        check.halves.append((window, count))
        if not check.complete:
            return
        if check.proves_truncation:
            self._lower_threshold(check.parent_count)
            return
        # A half that returned every story of its parent proves nothing yet. Verify it in turn,
        # unless the threshold has since dropped and the rule above already split it.
        for half, half_count in check.halves:
            if half_count == check.parent_count and half_count < self._threshold:
                self._verify_window(half, half_count)

    def _lower_threshold(self, cap: int) -> None:
        if cap >= self._threshold:
            return
        logger.info("Shortcut stories/search truncates responses at %s stories; splitting windows at that size", cap)
        self._threshold = cap
        truncated = [(window, count) for window, count in self._accepted if count >= cap]
        self._accepted = [(window, count) for window, count in self._accepted if count < cap]
        for window, _ in truncated:
            self._split(window)


def _dedupe_pages_by_id(pages: Iterable[Any], primary_key: str) -> Iterator[list[dict[str, Any]]]:
    """Drop stories re-read across window boundaries so no id lands in the table twice.

    Neighbouring `created_at` windows overlap by a second or two, and a window fetched again in
    halves repeats every story of the parent response. Full refresh appends without the merge's
    primary-key dedup (that runs only for incremental writes), so drop the re-read rows here. Keyed
    on the unique story id, so it never drops a distinct story whatever order the endpoint returns
    rows in. Holds the seen ids for one sync, bounded by the story count.
    """
    seen: set[Any] = set()
    for page in pages:
        fresh: list[dict[str, Any]] = []
        for row in page:
            key = row.get(primary_key)
            if key is not None and key in seen:
                continue
            if key is not None:
                seen.add(key)
            fresh.append(row)
        if fresh:
            yield fresh


def shortcut_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = SHORTCUT_ENDPOINTS[endpoint]

    endpoint_config: dict[str, Any] = {
        "path": config.path,
        "method": config.method,
        # Every Shortcut list endpoint (and stories/search) returns a bare JSON array; require it to
        # be a list so a changed/error 200 body fails loud instead of syncing a stray object as a row.
        "data_selector_required": True,
    }
    if config.method == "POST":
        # Shortcut's stories/search carries its server-side timestamp filters in the POST body (not the
        # query string). This seeds the first window; the paginator sets the created_at bounds per request.
        endpoint_config["json"] = _build_search_body(
            config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
        )

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": SHORTCUT_BASE_URL,
            "headers": _base_headers(),
            "auth": {
                "type": "api_key",
                "api_key": api_token,
                "name": "Shortcut-Token",
                "location": "header",
            },
            # Flat list endpoints return the whole collection in one response; stories/search
            # documents no cap or order, so it is read in created_at windows.
            "paginator": StoriesSearchPaginator(
                primary_key=config.primary_key, split_threshold=STORY_SEARCH_SPLIT_THRESHOLD
            )
            if config.method == "POST"
            else SinglePagePaginator(),
        },
        "resource_defaults": {},
        "resources": [
            cast(
                "EndpointResource",
                {
                    "name": endpoint,
                    "endpoint": endpoint_config,
                },
            )
        ],
    }

    resource = rest_api_resource(rest_config, team_id, job_id, None)

    # stories/search windows share boundary seconds and verification re-reads whole windows, so
    # dedupe on id before the rows reach the writer — the full-refresh append path never runs the
    # merge's primary-key dedup. Flat GET endpoints return the whole collection in one page, no re-reads.
    def items() -> Iterable[Any]:
        if config.method == "POST":
            return _dedupe_pages_by_id(resource, config.primary_key)
        return resource

    # stories/search windows arrive in no cursor order, so use desc for every cursor field: it
    # advances the watermark once the run finishes rather than after each batch. A per-batch max on
    # an unordered stream would skip unwritten lower rows on the next run's server-side filter.
    sort_mode: SortMode = "desc"

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
        sort_mode=sort_mode,
    )


def validate_credentials(api_token: str) -> tuple[bool, str | None]:
    """Probe the cheapest authenticated endpoint to confirm the token is genuine."""
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        f"{SHORTCUT_BASE_URL}/member",
        headers={"Shortcut-Token": api_token, **_base_headers()},
    )
    if ok:
        return True, None
    if status == 401:
        return False, "Invalid Shortcut API token. Generate a new token in Settings > API Tokens and reconnect."
    if status == 403:
        return False, "Your Shortcut API token does not have access to this workspace. Please check its permissions."
    return False, f"Shortcut API returned an unexpected status: {status}"
