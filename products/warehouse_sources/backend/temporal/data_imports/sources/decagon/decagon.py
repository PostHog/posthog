import math
import time
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.decagon.settings import (
    DECAGON_ENDPOINTS,
    DecagonEndpointConfig,
)

DECAGON_BASE_URL = "https://api.decagon.ai"

REQUEST_TIMEOUT_SECONDS = 60

# Server-side page size of /conversation/export, per Decagon's docs.
DECAGON_PAGE_SIZE = 100

# Decagon enforces a hard limit of 1 request/second across all API endpoints and
# automatically IP-bans gross violators, so requests are spaced client-side rather
# than relying on 429 backoff alone.
MIN_SECONDS_BETWEEN_REQUESTS = 1.0

# Hard bound on the requests a "page" or "offset" walk makes when the response gives no
# total to derive one from. It stops a server that ignores the position param and returns
# a full page on every request; a real export of this size would still end on its short
# last page.
MAX_PAGES_WITHOUT_TOTAL = 10_000

# Maps a conversation row column to the `timestamp_filter` enum value that makes the
# export's min_timestamp/max_timestamp params bound that column. The filter for the
# `last_message_at` column is named `last_message_time`; both spellings are the
# vendor's, not a typo.
TIMESTAMP_FILTER_BY_FIELD: dict[str, str] = {
    "created_at": "created_at",
    "updated_at": "updated_at",
    "last_message_at": "last_message_time",
}

# Fallback window value for endpoints whose incremental bound is mandatory. Used when a
# walk has no natural window (a full refresh, or an incremental sync's first run), so it
# fetches full history instead of omitting the param the endpoint requires.
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class DecagonRetryableError(Exception):
    pass


# Stable opening of the DecagonContractError message. The rest of the message names the
# endpoint and the reported total, so `DecagonSource.get_non_retryable_errors` needs a fixed
# fragment to match the failure on.
CONTRACT_MISMATCH_ERROR = "Decagon imported no rows against a nonzero reported total"

# Stable opening of the failure raised when the response holds lists but the config can
# identify none of them as rows. Classified apart from the mismatch above because only two
# endpoints report a total, so that guard cannot see this failure for the other six.
UNREADABLE_ENVELOPE_ERROR = "Decagon sent lists this table's config cannot read as rows"


class DecagonContractError(Exception):
    """The response does not match the contract the endpoint is configured against."""


@dataclasses.dataclass
class DecagonResumeConfig:
    # Position of the next unfetched page, one field per pagination mode: the next-page
    # cursor ("cursor"), the next page number ("page"), or the next row offset ("offset").
    cursor: Optional[str] = None
    page: Optional[int] = None
    offset: Optional[int] = None
    # Rows already received across the walk ("page" mode). Counts what the server actually
    # returned rather than page * page_size, so termination against the reported total
    # stays exact even if the server caps the requested page size.
    rows_walked: Optional[int] = None
    # The incremental window the position belongs to, in the format the endpoint's
    # incremental_param takes (the field is named after the exports' param). A resumed
    # run must reissue exactly this alongside the position: the stored watermark can
    # advance while a walk is in flight, and recomputing the window would pair a fresh
    # lower bound with a position inside the old window. Optional so states saved before
    # these fields existed still parse.
    min_timestamp: Optional[int | str] = None
    timestamp_filter: Optional[str] = None


@dataclasses.dataclass(frozen=True)
class _IncrementalWindow:
    """The server-side bound a walk sends on every request."""

    value: Optional[int | str] = None
    timestamp_filter: Optional[str] = None
    # True when a real watermark bounds the request, rather than the fallback bound an
    # endpoint with a mandatory filter needs. A windowed walk can legitimately keep no
    # rows, so the contract guard at the end of the walk must not fire for it.
    from_watermark: bool = False

    def request_params(self, config: DecagonEndpointConfig) -> dict[str, str]:
        if self.value is None or not config.incremental_param:
            return {}
        params = {config.incremental_param: str(self.value)}
        if self.timestamp_filter and config.timestamp_filter_param:
            params[config.timestamp_filter_param] = self.timestamp_filter
        return params


@dataclasses.dataclass(frozen=True)
class _ListCandidate:
    """A list found in a response envelope, with the object that held it."""

    path: str
    items: list[Any]
    parent: dict[str, Any]


@dataclasses.dataclass(frozen=True)
class _Batch:
    """One page of a walk: the response envelope, the rows it carried, and the rows to emit."""

    data: dict[str, Any]
    # Where the walk reads its cursor, has_more and total. Rows found one object down take
    # their pagination fields with them, so reading only the top level ends the walk after
    # one page; the response itself stays the fallback for fields the wrapper leaves outside.
    pagination: dict[str, Any]
    items: list[Any]
    fresh: list[dict[str, Any]]


class RequestThrottle:
    """Spaces consecutive requests at least `min_interval` seconds apart."""

    def __init__(self, min_interval: float = MIN_SECONDS_BETWEEN_REQUESTS) -> None:
        self._min_interval = min_interval
        self._last_request_at: Optional[float] = None

    def wait(self) -> None:
        if self._last_request_at is not None:
            remaining = self._min_interval - (time.monotonic() - self._last_request_at)
            if remaining > 0:
                time.sleep(remaining)
        self._last_request_at = time.monotonic()


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _to_epoch_seconds(value: Any) -> int:
    """Coerce an incremental watermark to Unix epoch seconds.

    The watermark is stored from an ISO 8601 column, but the pipeline may hand it back as
    a datetime, a date, or an epoch number depending on how it round-tripped through
    storage. int() truncates any sub-second part, so the boundary second is re-fetched and
    a merge dedupes it on the primary key.
    """
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return int(dt.timestamp())
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp())
    return int(value)


def _incremental_window_value(config: DecagonEndpointConfig, value: Any) -> int | str:
    if config.incremental_param_format == "iso8601":
        return datetime.fromtimestamp(_to_epoch_seconds(value), UTC).isoformat()
    return _to_epoch_seconds(value)


def _list_candidates(data: dict[str, Any]) -> list[_ListCandidate]:
    """Every list in the envelope, at the top level or one object below it."""
    candidates: list[_ListCandidate] = []
    for key, value in data.items():
        if isinstance(value, list):
            candidates.append(_ListCandidate(path=key, items=value, parent=data))
        elif isinstance(value, dict):
            candidates.extend(
                _ListCandidate(path=f"{key}.{nested}", items=item, parent=value)
                for nested, item in value.items()
                if isinstance(item, list)
            )
    return candidates


def _looks_like_rows(config: DecagonEndpointConfig, items: list[Any]) -> bool:
    """Whether a list can hold this endpoint's rows: every item an object carrying its primary keys.

    A keyless endpoint never qualifies. "A list of objects" is not evidence of anything, and
    its stream appends without a merge, so a wrong pick lands rows no later sync can clean up.
    """
    if config.primary_keys is None or not items:
        return False
    return all(isinstance(item, dict) and all(key in item for key in config.primary_keys) for item in items)


def _describe_shape(data: dict[str, Any]) -> str:
    """The envelope's keys and value shapes, so the log names what arrived, not what did not."""
    parts: list[str] = []
    for key in sorted(data):
        value = data[key]
        if isinstance(value, list):
            parts.append(f"{key}: list[{len(value)}]")
        elif isinstance(value, dict):
            parts.append(f"{key}: object({', '.join(sorted(value))})")
        else:
            parts.append(f"{key}: {type(value).__name__}")
    return ", ".join(parts)


def _unreadable_reason(
    config: DecagonEndpointConfig, same_key: list[_ListCandidate], row_like: list[_ListCandidate]
) -> str:
    """Why the walk could not choose a row list, in the words the operator has to act on.

    Two lists matching needs a different repair from none matching, and support reads this
    text without a Decagon credential to check it against. So name the lists that matched
    rather than report every failure as a response that carries no rows anywhere.
    """
    if len(same_key) > 1:
        paths = ", ".join(f"'{found.path}'" for found in same_key)
        return f"{len(same_key)} of them are named '{config.data_key}' ({paths})"
    if len(row_like) > 1:
        paths = ", ".join(f"'{found.path}'" for found in row_like)
        return f"{len(row_like)} of them carry this endpoint's primary keys ({paths})"
    if row_like:
        return (
            f"only '{row_like[0].path}' carries this endpoint's primary keys, but an empty list beside it "
            f"reads the same as this table's rows returning none"
        )
    return f"none of them is named '{config.data_key}' or carries this endpoint's primary keys"


def _resolve_rows(
    data: dict[str, Any], config: DecagonEndpointConfig, endpoint: str, logger: FilteringBoundLogger
) -> _ListCandidate:
    """Read the row list out of a response envelope, with the object that held it.

    Decagon renames and re-nests envelope fields between doc revisions (the conversations
    export alone documents three names for one cursor field), and a lookup that misses
    reads as an empty page, which fails the walk against the reported total. So search the
    envelope for the list the rows moved to: the same key one object down, or the only
    list whose items carry this endpoint's primary keys. A response holding lists that
    match neither fails the sync rather than reading as an empty page.
    """
    items = data.get(config.data_key)
    if isinstance(items, list):
        return _ListCandidate(path=config.data_key, items=items, parent=data)

    candidates = _list_candidates(data)
    same_key = [found for found in candidates if found.path.rsplit(".", 1)[-1] == config.data_key]
    row_like = [found for found in candidates if _looks_like_rows(config, found.items)]
    # An empty list reads the same as a renamed key that returned no rows, so the primary
    # keys stop separating the two readings. Most keyed endpoints key on `id`, which any
    # sibling list of objects carries, and a full refresh would replace the table with that
    # list. A name match is unaffected: there the response names the rows.
    inferred = [] if any(not found.items for found in candidates) else row_like
    # A list qualifies on its name or on the endpoint's primary keys. Being the envelope's
    # only list is not evidence: "the only list" also describes a list of warnings, and
    # reading that one imports metadata as rows. Anything that leaves more than one
    # candidate is a guess, so it fails instead.
    for shortlist in (same_key, inferred):
        if len(shortlist) == 1:
            found = shortlist[0]
            logger.warning(
                f"Decagon: {endpoint} response carries no '{config.data_key}' list; reading rows from "
                f"'{found.path}' instead (response shape: {_describe_shape(data)})"
            )
            return found

    if candidates:
        reason = _unreadable_reason(config, same_key, row_like)
        # Finalization replaces this message with the fixed operator-facing one, so the
        # shape only reaches whoever has to act on it through the log.
        logger.error(
            f"Decagon: {endpoint} cannot read rows from its response; {reason} "
            f"(response shape: {_describe_shape(data)}, rows read from '{config.data_key}')"
        )
        # Only `articles` and `admin_logs` report a total, so for every other endpoint the
        # contract check has nothing to fail on and this would complete as an empty sync.
        # A full refresh clears the table before extraction, so the populated table would
        # be gone and the job green. The rows are in one of these lists, so fail instead.
        raise DecagonContractError(
            f"{UNREADABLE_ENVELOPE_ERROR}: {endpoint} carries {len(candidates)} list(s) and {reason} "
            f"(response shape: {_describe_shape(data)})."
        )

    # No list anywhere can be an endpoint that omits its key instead of sending it empty,
    # so an empty page stays a warning rather than a failed sync.
    logger.warning(
        f"Decagon: {endpoint} response carries no '{config.data_key}' list and no list to read it from "
        f"(response shape: {_describe_shape(data)})"
    )
    return _ListCandidate(path=config.data_key, items=[], parent=data)


def _next_cursor(data: dict[str, Any], cursor_keys: tuple[str, ...]) -> Optional[str]:
    # Skip falsy values rather than returning the first key present: a response that
    # carries `next_page_cursor: null` alongside a populated alias must keep paginating.
    for key in cursor_keys:
        value = data.get(key)
        if value:
            # Cursors can be integers (a last-updated epoch watermark in Decagon's example
            # response); requests and the saved resume state both want strings.
            return str(value)
    return None


def validate_credentials(api_key: str) -> bool:
    """Probe the conversations export (the cheapest authenticated read) to confirm the key works."""
    try:
        response = make_tracked_session(redact_values=(api_key,)).get(
            f"{DECAGON_BASE_URL}/conversation/export",
            headers=_get_headers(api_key),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        return response.status_code == 200
    except Exception:
        return False


def _resolve_window(
    config: DecagonEndpointConfig,
    resume_config: Optional[DecagonResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
    incremental_field: Optional[str],
    logger: FilteringBoundLogger,
) -> _IncrementalWindow:
    """Decide the server-side bound the walk sends on every request."""
    value: Optional[int | str] = None
    timestamp_filter: Optional[str] = None

    if resume_config:
        # Resume the walk exactly where it stopped: same window, same position. See the
        # DecagonResumeConfig field comments for why the window is not recomputed here.
        value = resume_config.min_timestamp
        timestamp_filter = resume_config.timestamp_filter
    elif (
        should_use_incremental_field
        and db_incremental_field_last_value is not None
        and incremental_field
        and config.incremental_param
    ):
        if config.timestamp_filter_param:
            filter_name = TIMESTAMP_FILTER_BY_FIELD.get(incremental_field)
            if filter_name:
                value = _incremental_window_value(config, db_incremental_field_last_value)
                timestamp_filter = filter_name
            else:
                logger.warning(
                    f"Decagon: incremental field {incremental_field} has no server-side timestamp "
                    f"filter; walking the full export instead"
                )
        else:
            value = _incremental_window_value(config, db_incremental_field_last_value)
            if config.primary_keys is None and isinstance(value, int):
                # Keyless streams append without a merge to dedupe re-fetched rows, so an
                # inclusive bound would re-import the watermark second on every sync and
                # inflate counts indefinitely. Advance past it instead: an event landing in
                # that same second after the walk read it is the rarer failure, and a full
                # refresh trues the table up.
                value += 1

    # Read before the mandatory-bound fallback below, because an epoch bound includes every
    # row: a walk under it that keeps nothing carries the same mismatch signal as a walk
    # with no bound at all.
    from_watermark = value is not None

    if value is None and config.incremental_param and config.incremental_param_required:
        # No prior state and no watermark left the window unset, but this endpoint 400s
        # on a request that omits the bound entirely. The epoch keeps a full walk honest
        # (every row is included) while still satisfying the requirement.
        value = _incremental_window_value(config, _EPOCH)

    return _IncrementalWindow(value=value, timestamp_filter=timestamp_filter, from_watermark=from_watermark)


class _PageFetcher:
    """Reads one page: spaces requests, retries transient failures, and drops add-on params."""

    def __init__(
        self, api_key: str, config: DecagonEndpointConfig, endpoint: str, logger: FilteringBoundLogger
    ) -> None:
        self._session = make_tracked_session(redact_values=(api_key,))
        self._url = f"{DECAGON_BASE_URL}{config.path}"
        self._headers = _get_headers(api_key)
        self._config = config
        self._endpoint = endpoint
        self._logger = logger
        self._throttle = RequestThrottle()
        self._optional_params_dropped = not config.optional_params

    @retry(
        retry=retry_if_exception_type((DecagonRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(5),
        # The 1 rps limit means a 429 needs a generous backoff, not a quick retry.
        wait=wait_exponential_jitter(initial=2, max=60),
        reraise=True,
    )
    def _request(self, params: dict[str, str]) -> dict[str, Any]:
        self._throttle.wait()
        response = self._session.get(self._url, params=params, headers=self._headers, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise DecagonRetryableError(
                f"Decagon API error (retryable): status={response.status_code}, url={self._url}"
            )

        if not response.ok:
            self._logger.error(
                f"Decagon API error: status={response.status_code}, body={response.text}, url={self._url}"
            )
            response.raise_for_status()

        return response.json()

    def fetch(self, params: dict[str, str]) -> dict[str, Any]:
        # Decagon refuses the whole request when an optional add-on param names an entitlement
        # the team does not hold, so a table whose base response would sync fine never loads.
        # Drop the add-on params and retry; a 403 about the endpoint itself fails again and
        # still surfaces. The drop persists for the rest of the walk so each page costs one
        # request, which matters against the 1 rps limit.
        if not self._optional_params_dropped:
            try:
                return self._request({**params, **self._config.optional_params})
            except requests.HTTPError as err:
                if err.response is None or err.response.status_code != 403:
                    raise
                self._optional_params_dropped = True
                self._logger.warning(
                    f"Decagon: {self._endpoint} refused {sorted(self._config.optional_params)}; "
                    f"retrying without the add-on params"
                )
        return self._request(params)


class _RowDeduplicator:
    """Skips rows this walk already emitted.

    A row can re-enter the stream on a later page of one walk (a conversation that
    receives new messages re-enters the export). Full-refresh writes are plain appends
    (no primary-key merge), so re-emissions are skipped client-side; the next sync picks
    up the newer version. Incremental writes merge on the primary key and the writer
    keeps the last occurrence per key within a batch, so there the re-emission must flow
    through (dropping it would keep the stale version) and the set, which grows
    unboundedly across a large export, is not needed. Keyless streams have nothing to
    dedupe on and always flow through.
    """

    def __init__(self, config: DecagonEndpointConfig, should_use_incremental_field: bool) -> None:
        self._primary_keys = config.primary_keys
        self._seen_keys: Optional[set[tuple[Any, ...]]] = (
            set() if config.primary_keys is not None and not should_use_incremental_field else None
        )

    def fresh(self, items: list[Any]) -> list[dict[str, Any]]:
        fresh: list[dict[str, Any]] = []
        for item in items:
            if self._primary_keys is not None:
                # Direct access on purpose: these fields are the primary key, so a row
                # missing one should fail the sync loudly rather than land in the
                # warehouse unkeyed and undeduplicatable.
                key = tuple(item[k] for k in self._primary_keys)
                if self._seen_keys is not None:
                    if key in self._seen_keys:
                        continue
                    self._seen_keys.add(key)
            fresh.append(item)
        return fresh


def _usable_total(reported: Any) -> Optional[int | float]:
    """The reported total when it can bound a walk: a finite, non-negative number."""
    if isinstance(reported, bool) or not isinstance(reported, int | float) or not math.isfinite(reported):
        return None
    return reported if reported >= 0 else None


class _RowWalk:
    """Walks one endpoint's pages, one method per pagination mode.

    Tracks what the walk observed, so it can check the response against the endpoint's
    contract once the walk ends.
    """

    def __init__(
        self,
        config: DecagonEndpointConfig,
        endpoint: str,
        fetcher: _PageFetcher,
        window: _IncrementalWindow,
        resume_config: Optional[DecagonResumeConfig],
        resumable_source_manager: ResumableSourceManager[DecagonResumeConfig],
        deduplicator: _RowDeduplicator,
        logger: FilteringBoundLogger,
    ) -> None:
        self._config = config
        self._endpoint = endpoint
        self._fetcher = fetcher
        self._window = window
        self._window_params = window.request_params(config)
        self._resumed = resume_config is not None
        self._resume = resume_config or DecagonResumeConfig()
        self._manager = resumable_source_manager
        self._deduplicator = deduplicator
        self._logger = logger
        self._saw_rows = False
        self._reported_total: Any = None
        self._envelope_shape = ""

    def run(self) -> Iterator[list[dict[str, Any]]]:
        yield from self._walk()
        self._check_contract()

    def _walk(self) -> Iterator[list[dict[str, Any]]]:
        if self._config.pagination == "single":
            return self._walk_single()
        if self._config.pagination == "cursor":
            return self._walk_cursor()
        if self._config.pagination == "page":
            return self._walk_page()
        return self._walk_offset()

    def _read(self, position_params: dict[str, str]) -> _Batch:
        params: dict[str, str] = {**self._config.extra_params, **position_params, **self._window_params}
        data = self._fetcher.fetch(params)
        self._envelope_shape = _describe_shape(data)
        rows = _resolve_rows(data, self._config, self._endpoint, self._logger)
        fresh = self._deduplicator.fresh(rows.items)
        self._saw_rows = self._saw_rows or bool(fresh)
        pagination = data if rows.parent is data else {**data, **rows.parent}
        # Recorded here rather than in the walk, so the contract check sees the reported
        # total whichever mode read the response. A later page that omits the total keeps
        # the one an earlier page reported: dropping it falls the walk back to short-page
        # termination, which a server-capped page then ends before the total is reached.
        reported = pagination.get(self._config.total_key) if self._config.total_key else None
        if _usable_total(reported) is not None or _usable_total(self._reported_total) is None:
            self._reported_total = reported
        return _Batch(data=data, pagination=pagination, items=rows.items, fresh=fresh)

    def _short_page(self, batch: _Batch) -> bool:
        """Termination signal left when the response carries no usable total."""
        page_size = self._config.page_size
        return not batch.items or (page_size is not None and len(batch.items) < page_size)

    def _request_cap_reached(self, requests_made: int, position_param: str) -> bool:
        """Constant bound for a walk with no usable total to size one from.

        A server that ignores the position param answers every request with a full page,
        which short-page termination never ends. With no total to check the kept rows
        against, the cap can only warn.
        """
        if requests_made < MAX_PAGES_WITHOUT_TOTAL:
            return False
        self._logger.warning(
            f"Decagon: {self._endpoint} walk stopped at the cap of {MAX_PAGES_WITHOUT_TOTAL} requests with no "
            f"usable total (got {self._reported_total!r}). If the synced row count looks truncated, check that "
            f"the endpoint honors the {position_param} param."
        )
        return True

    def _check_contract(self) -> None:
        # A walk that read every row of the endpoint and kept none, while the endpoint itself
        # reports rows, means the response no longer matches this config. Fail the sync: the
        # alternative is the table reporting success forever and never holding a row.
        if (
            not self._saw_rows
            and not self._resumed
            and not self._window.from_watermark
            and isinstance(self._reported_total, int | float)
            and self._reported_total > 0
        ):
            # Finalization replaces the message below with the fixed operator-facing one, so
            # the shape only reaches whoever has to act on it through the log.
            self._logger.error(
                f"Decagon: {self._endpoint} kept no rows against a reported total of {self._reported_total} "
                f"(response shape: {self._envelope_shape}, rows read from '{self._config.data_key}')"
            )
            raise DecagonContractError(
                f"{CONTRACT_MISMATCH_ERROR}: {self._endpoint} reports {self._reported_total} rows and the walk "
                f"kept none. The last response carried {self._envelope_shape}, and the config reads rows from "
                f"'{self._config.data_key}'."
            )

    def _save_position(self, **position: Any) -> None:
        # Persisted only after a yield, so a crash re-yields the last batch rather than
        # skipping it (the duplicate rows a resumed re-yield can produce are bounded to
        # one page, and are cleaned up by the next full refresh or merged away on the
        # primary key).
        self._manager.save_state(
            DecagonResumeConfig(
                min_timestamp=self._window.value, timestamp_filter=self._window.timestamp_filter, **position
            )
        )

    def _walk_single(self) -> Iterator[list[dict[str, Any]]]:
        batch = self._read({})
        if batch.fresh:
            yield batch.fresh

    def _walk_cursor(self) -> Iterator[list[dict[str, Any]]]:
        config = self._config
        cursor = self._resume.cursor

        while True:
            # An omitted cursor starts the stream at the oldest rows.
            batch = self._read({"cursor": cursor} if cursor else {})
            next_cursor = _next_cursor(batch.pagination, config.next_cursor_keys or ())
            more = batch.pagination.get(config.has_more_key) if config.has_more_key else None

            if batch.fresh:
                yield batch.fresh
                if next_cursor and more is not False:
                    self._save_position(cursor=next_cursor)

            if config.has_more_key is not None and not more:
                return
            # The next-page cursor is null once the stream is exhausted. Also stop if the
            # server ever returns the cursor we just used, to guard against spinning on
            # one page forever.
            if not next_cursor or next_cursor == cursor:
                if more:
                    # The walk has to stop here, but the response says rows remain, so this
                    # is a truncated stream rather than an exhausted one. The endpoints that
                    # send has_more append with no merge and walk desc, so a completed run
                    # advances the watermark past the newest rows this page held and every
                    # later sync skips the pages this walk never reached.
                    stopped = "repeated the cursor just used" if next_cursor else "carried no next-page cursor"
                    self._logger.warning(
                        f"Decagon: {self._endpoint} stopped after a page that {stopped} while "
                        f"'{config.has_more_key}' reports {more!r} (response keys: {sorted(batch.data.keys())}, "
                        f"cursor read from {list(config.next_cursor_keys or ())}). The rows past this page did "
                        f"not sync; check the export pagination contract."
                    )
                elif config.has_more_key is None and not next_cursor and len(batch.items) >= DECAGON_PAGE_SIZE:
                    # A full page that ends the walk is legitimate only when the total row
                    # count happens to be a multiple of the page size; far more often it means
                    # Decagon renamed the pagination field again and rows were truncated.
                    self._logger.warning(
                        f"Decagon: {self._endpoint} stream ended on a full page of {len(batch.items)} items "
                        f"without a next-page cursor (response keys: {sorted(batch.data.keys())}). If the "
                        f"synced row count looks truncated, check the export pagination contract."
                    )
                return

            cursor = next_cursor

    def _walk_page(self) -> Iterator[list[dict[str, Any]]]:
        config = self._config
        page = self._resume.page or 1
        # Rows actually kept, not page * page_size: a row that shifted pages mid-walk arrives
        # twice but counts once toward the server's unique total, so counting raw items could
        # reach the total a page early and drop the final page. This also stays exact if the
        # server caps the requested page size.
        rows_walked = self._resume.rows_walked or 0
        # The largest raw page the server returned: its effective page size, which can be
        # smaller than the one requested.
        page_rows = 0

        while True:
            params = {"page": str(page)}
            if config.page_size is not None:
                params["page_size"] = str(config.page_size)

            batch = self._read(params)
            total = self._reported_total
            rows_walked += len(batch.fresh)
            page_rows = max(page_rows, len(batch.items))
            exhausted = self._page_walk_exhausted(page, rows_walked, page_rows, total, batch)

            if batch.fresh:
                yield batch.fresh
                if not exhausted:
                    self._save_position(page=page + 1, rows_walked=rows_walked)
            if exhausted:
                return

            page += 1

    def _page_walk_exhausted(self, page: int, rows_walked: int, page_rows: int, reported: Any, batch: _Batch) -> bool:
        # A page of only already-seen rows does not end the walk: the catalog can shift rows
        # between pages mid-walk, so a later page can still hold rows this walk has not kept.
        # The page bound is what stops a server that ignores the page param instead.
        if not batch.items:
            return True
        total = _usable_total(reported)
        if total is not None and rows_walked >= total:
            return True

        if total is None:
            # A missing or malformed total falls back to short-page termination, bounded by
            # the constant cap.
            return self._short_page(batch) or self._request_cap_reached(page, "page")

        # One page more than the total needs at the server's page size, so rows that shift
        # pages mid-walk (arriving twice, kept once) do not push the last unique rows past
        # the bound. Sized from the pages received, not the size requested, because the
        # server can cap the requested size and a bound from the larger size would truncate.
        max_pages = math.ceil(total / page_rows) + 1
        if page < max_pages:
            return False
        # Every page the total allows for is walked and rows are still missing: the server
        # ignores the page param or the total does not describe the export. Completing here
        # would report success on a partial table.
        raise DecagonContractError(
            f"Decagon: {self._endpoint} walked {max_pages} pages and kept {rows_walked} rows against a "
            f"reported total of {total}. Check that the endpoint honors the page param."
        )

    def _walk_offset(self) -> Iterator[list[dict[str, Any]]]:
        config = self._config
        offset = self._resume.offset or 0
        requests_made = 0

        while True:
            params = {"offset": str(offset)}
            if config.page_size is not None:
                params["limit"] = str(config.page_size)

            batch = self._read(params)
            requests_made += 1
            total = _usable_total(self._reported_total)

            # Advance by the rows actually received rather than by page_size, so a server that
            # caps `limit` below what we asked still walks every row. The offset itself is the
            # cumulative row count, so the total check needs no separate counter.
            next_offset = offset + len(batch.items)
            if total is not None:
                exhausted = not batch.items or next_offset >= total
            else:
                # A server that ignores `offset` sends a full page to every request and never
                # the short page this would otherwise end on.
                exhausted = self._short_page(batch) or self._request_cap_reached(requests_made, "offset")

            if batch.fresh:
                yield batch.fresh
                if not exhausted:
                    self._save_position(offset=next_offset)
            if exhausted:
                return

            offset = next_offset


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DecagonResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: Optional[str] = None,
) -> Iterator[list[dict[str, Any]]]:
    config = DECAGON_ENDPOINTS[endpoint]

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config:
        logger.debug(f"Decagon: resuming {endpoint} from saved state")

    window = _resolve_window(
        config, resume_config, should_use_incremental_field, db_incremental_field_last_value, incremental_field, logger
    )

    walk = _RowWalk(
        config=config,
        endpoint=endpoint,
        fetcher=_PageFetcher(api_key=api_key, config=config, endpoint=endpoint, logger=logger),
        window=window,
        resume_config=resume_config,
        resumable_source_manager=resumable_source_manager,
        deduplicator=_RowDeduplicator(config, should_use_incremental_field),
        logger=logger,
    )

    yield from walk.run()

    # Walked to completion, so drop any checkpoint: a retried attempt of this job would
    # otherwise resume at the final page and append its rows again.
    resumable_source_manager.clear_state()


def decagon_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DecagonResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: Optional[str] = None,
) -> SourceResponse:
    config = DECAGON_ENDPOINTS[endpoint]
    partitioned = config.partition_key is not None

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=config.primary_keys,
        partition_count=1 if partitioned else None,
        partition_size=1 if partitioned else None,
        partition_mode="datetime" if partitioned else None,
        partition_format="month" if partitioned else None,
        partition_keys=[config.partition_key] if config.partition_key is not None else None,
        sort_mode=config.sort_mode,
        chunk_size=config.chunk_size,
        chunk_size_bytes=config.chunk_size_bytes,
    )
