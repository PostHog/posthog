import time
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.squadcast.settings import (
    SQUADCAST_ENDPOINTS,
    SquadcastEndpointConfig,
)

# Squadcast is region-sharded: a US account's refresh token only works against the US hosts and
# vice versa, so the user picks the region in the source form.
REGION_HOSTS: dict[str, tuple[str, str]] = {
    "us": ("https://auth.squadcast.com", "https://api.squadcast.com"),
    "eu": ("https://auth.eu.squadcast.com", "https://api.eu.squadcast.com"),
}

PAGE_SIZE = 100

# The postmortem list endpoint requires a `limit` and exposes no offset/page param, so we ask for
# a generous window and warn if the reported total exceeds what came back.
POSTMORTEM_LIMIT = 1000

# The incident export requires a start/end window; chunking it bounds each response's size on
# accounts with years of history and gives us natural resume checkpoints.
INCIDENT_EXPORT_WINDOW_DAYS = 30

# Window start used on full refresh / first sync (predates Squadcast's launch).
FULL_REFRESH_START = datetime(2015, 1, 1, tzinfo=UTC)

# Retry/throttle settings kept near the top for easy tuning.
RETRY_ATTEMPTS = 5
REQUEST_TIMEOUT_SECONDS = 60

# Re-exchange the refresh token this many seconds before the access token's `expires_at`.
TOKEN_REFRESH_LEEWAY_SECONDS = 120


class SquadcastRetryableError(Exception):
    pass


class SquadcastAuthError(Exception):
    """Raised when the refresh token exchange is rejected — a permanent credential failure."""


@dataclasses.dataclass
class SquadcastResumeConfig:
    # Bookmark of the team currently being processed (fan-out endpoints). A stable team-ID
    # bookmark rather than a positional index, so teams added/removed between a crash and the
    # retry can't resume us into the wrong team. None for org-level endpoints.
    team_id: str | None = None
    # Position within the bookmarked team: an offset, a page cursor, or an ISO window start,
    # depending on the endpoint's pagination style. None means "start the team from the top".
    cursor: str | None = None


def _hosts_for_region(region: str | None) -> tuple[str, str]:
    return REGION_HOSTS.get((region or "us").lower(), REGION_HOSTS["us"])


def _format_datetime(value: Any) -> str:
    """Format a datetime as RFC 3339 with a Z suffix, which Squadcast's date filters expect."""
    if isinstance(value, datetime):
        utc_value = value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    elif isinstance(value, date):
        utc_value = datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    else:
        return str(value)
    return utc_value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)


def _error_message(response: requests.Response) -> str:
    try:
        return response.json().get("meta", {}).get("error_message") or response.text
    except Exception:
        return response.text


class SquadcastClient:
    """Minimal Squadcast API client that exchanges the long-lived refresh token for a short-lived
    bearer access token and transparently re-exchanges it before expiry."""

    def __init__(self, refresh_token: str, region: str | None, logger: FilteringBoundLogger) -> None:
        self._auth_host, self.api_host = _hosts_for_region(region)
        self._refresh_token = refresh_token
        self._logger = logger
        # One session reused across every request so urllib3 keeps the connection alive.
        self._session = make_tracked_session()
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0

    def _get_access_token(self) -> str:
        now = time.time()
        if self._access_token is None or now >= self._token_expires_at - TOKEN_REFRESH_LEEWAY_SECONDS:
            response = self._session.get(
                f"{self._auth_host}/oauth/access-token",
                headers={"X-Refresh-Token": self._refresh_token},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            if response.status_code == 429 or response.status_code >= 500:
                raise SquadcastRetryableError(
                    f"Squadcast auth error (retryable): status={response.status_code}, host={self._auth_host}"
                )
            if not response.ok:
                raise SquadcastAuthError(
                    f"Squadcast refresh token was rejected (status={response.status_code}): {_error_message(response)}"
                )

            data = response.json().get("data", {})
            access_token = data.get("access_token")
            if not access_token:
                raise SquadcastAuthError("Squadcast token exchange succeeded but returned no access token")

            self._access_token = access_token
            # `expires_at` is a unix timestamp; fall back to a conservative 10 minutes if absent.
            self._token_expires_at = float(data.get("expires_at") or (now + 600))

        assert self._access_token is not None
        return self._access_token

    @retry(
        retry=retry_if_exception_type((SquadcastRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def get(self, path: str, params: Optional[dict[str, Any]] = None) -> Any:
        url = f"{self.api_host}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"

        response = self._session.get(
            url,
            headers={"Authorization": f"Bearer {self._get_access_token()}"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

        if response.status_code == 429 or response.status_code >= 500:
            raise SquadcastRetryableError(f"Squadcast API error (retryable): status={response.status_code}, url={url}")

        if not response.ok:
            self._logger.error(f"Squadcast API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return response.json()


def _extract_rows(data: Any, envelope: tuple[str, ...]) -> list[dict[str, Any]]:
    current = data
    for key in envelope:
        if not isinstance(current, dict):
            return []
        current = current.get(key)
    return current if isinstance(current, list) else []


def _with_team(rows: list[dict[str, Any]], team_id: str) -> list[dict[str, Any]]:
    """Stamp the owning team onto fan-out rows — most Squadcast payloads don't carry it."""
    for row in rows:
        if isinstance(row, dict) and "team_id" not in row:
            row["team_id"] = team_id
    return rows


def _iter_offset_pages(
    client: SquadcastClient,
    config: SquadcastEndpointConfig,
    team_id: str,
    start_cursor: str | None,
    resumable_source_manager: ResumableSourceManager[SquadcastResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    offset = int(start_cursor) if start_cursor else 0
    while True:
        assert config.team_param is not None
        data = client.get(config.path, {config.team_param: team_id, "offset": offset, "limit": PAGE_SIZE})
        rows = _extract_rows(data, config.envelope)
        if not rows:
            break

        yield _with_team(rows, team_id)

        if len(rows) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
        # Save AFTER yielding so a crash re-fetches the last page; merge dedupes on primary key.
        resumable_source_manager.save_state(SquadcastResumeConfig(team_id=team_id, cursor=str(offset)))


def _iter_cursor_pages(
    client: SquadcastClient,
    config: SquadcastEndpointConfig,
    team_id: str,
    start_cursor: str | None,
    resumable_source_manager: ResumableSourceManager[SquadcastResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    cursor = start_cursor
    while True:
        assert config.team_param is not None
        params: dict[str, Any] = {config.team_param: team_id, "pageSize": PAGE_SIZE}
        if cursor:
            params["cursor"] = cursor

        data = client.get(config.path, params)
        rows = _extract_rows(data, config.envelope)
        page_info = data.get("pageInfo", {}) if isinstance(data, dict) else {}
        next_cursor = page_info.get("nextCursor") if page_info.get("hasNext") else None

        if rows:
            yield _with_team(rows, team_id)

        if not next_cursor:
            break
        cursor = next_cursor
        resumable_source_manager.save_state(SquadcastResumeConfig(team_id=team_id, cursor=cursor))


def _iter_incident_export_windows(
    client: SquadcastClient,
    config: SquadcastEndpointConfig,
    team_id: str,
    start_cursor: str | None,
    resumable_source_manager: ResumableSourceManager[SquadcastResumeConfig],
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    if start_cursor:
        window_start = _parse_datetime(start_cursor)
    elif db_incremental_field_last_value is not None:
        window_start = _parse_datetime(db_incremental_field_last_value)
    else:
        window_start = FULL_REFRESH_START

    now = datetime.now(UTC)
    while window_start < now:
        window_end = min(window_start + timedelta(days=INCIDENT_EXPORT_WINDOW_DAYS), now)
        assert config.team_param is not None
        data = client.get(
            config.path,
            {
                config.team_param: team_id,
                "type": "json",
                "start_time": _format_datetime(window_start),
                "end_time": _format_datetime(window_end),
            },
        )

        # The JSON export's envelope isn't documented; accept both a bare list and the
        # `{"data": [...]}` / `{"incidents": [...]}` wrappers used elsewhere in the API.
        if isinstance(data, list):
            rows = [row for row in data if isinstance(row, dict)]
        else:
            rows = _extract_rows(data, ("data",)) or _extract_rows(data, ("incidents",))

        if rows:
            yield _with_team(rows, team_id)

        window_start = window_end
        if window_start < now:
            resumable_source_manager.save_state(
                SquadcastResumeConfig(team_id=team_id, cursor=_format_datetime(window_start))
            )


def _get_postmortem_rows(
    client: SquadcastClient,
    config: SquadcastEndpointConfig,
    team_id: str,
    logger: FilteringBoundLogger,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    window_start = (
        _parse_datetime(db_incremental_field_last_value)
        if db_incremental_field_last_value is not None
        else FULL_REFRESH_START
    )
    assert config.team_param is not None
    data = client.get(
        config.path,
        {
            config.team_param: team_id,
            "fromDate": _format_datetime(window_start),
            "toDate": _format_datetime(datetime.now(UTC)),
            "limit": POSTMORTEM_LIMIT,
        },
    )

    rows: list[dict[str, Any]] = []
    total_count: Optional[int] = None
    for item in _extract_rows(data, ("data",)):
        rows.extend(row for row in item.get("result") or [] if isinstance(row, dict))
        for counter in item.get("total_count") or []:
            if isinstance(counter, dict) and counter.get("count") is not None:
                total_count = counter["count"]

    # The endpoint requires `limit` and has no offset param, so an unusually large backlog
    # can't be paged through — surface the truncation instead of hiding it.
    if total_count is not None and total_count > len(rows):
        logger.warning(
            f"Squadcast: postmortems for team {team_id} truncated ({len(rows)} of {total_count}); "
            f"the API exposes no pagination beyond limit={POSTMORTEM_LIMIT}"
        )

    if rows:
        yield _with_team(rows, team_id)


def _iter_team_rows(
    client: SquadcastClient,
    config: SquadcastEndpointConfig,
    team_id: str,
    start_cursor: str | None,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SquadcastResumeConfig],
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    if config.pagination == "offset":
        yield from _iter_offset_pages(client, config, team_id, start_cursor, resumable_source_manager)
    elif config.pagination == "cursor":
        yield from _iter_cursor_pages(client, config, team_id, start_cursor, resumable_source_manager)
    elif config.pagination == "incident_export":
        yield from _iter_incident_export_windows(
            client, config, team_id, start_cursor, resumable_source_manager, db_incremental_field_last_value
        )
    elif config.pagination == "postmortems":
        yield from _get_postmortem_rows(client, config, team_id, logger, db_incremental_field_last_value)
    else:
        assert config.team_param is not None
        data = client.get(config.path, {config.team_param: team_id})
        rows = _extract_rows(data, config.envelope)

        # See settings.py: escalation policies aren't paginated client-side, so check the
        # reported total for silent truncation.
        if isinstance(data, dict):
            total_count = data.get("meta", {}).get("total_count")
            if total_count is not None and total_count > len(rows):
                logger.warning(
                    f"Squadcast: endpoint '{config.path}' for team {team_id} returned {len(rows)} "
                    f"of {total_count} rows; results may be truncated"
                )

        if rows:
            yield _with_team(rows, team_id)


def get_rows(
    refresh_token: str,
    region: str | None,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SquadcastResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = SQUADCAST_ENDPOINTS[endpoint]
    client = SquadcastClient(refresh_token, region, logger)
    last_value = db_incremental_field_last_value if should_use_incremental_field else None

    if config.team_param is None:
        data = client.get(config.path)
        rows = _extract_rows(data, config.envelope)
        if rows:
            yield rows
        return

    team_ids = [str(team["id"]) for team in _extract_rows(client.get("/v3/teams"), ("data",)) if team.get("id")]

    # Resolve the saved team-ID bookmark to the slice of teams still to process. If the
    # bookmarked team no longer exists, start over from the first team — merge dedupes the
    # re-pulled rows on the primary key. `resume_cursor` is consumed by the first team only.
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = team_ids
    resume_cursor: str | None = None
    if resume is not None and resume.team_id is not None and resume.team_id in team_ids:
        remaining = team_ids[team_ids.index(resume.team_id) :]
        resume_cursor = resume.cursor
        logger.debug(f"Squadcast: resuming {endpoint} from team {resume.team_id}, cursor={resume_cursor}")

    for index, team_id in enumerate(remaining):
        start_cursor = resume_cursor
        resume_cursor = None  # only the resumed-into team uses the saved cursor

        try:
            yield from _iter_team_rows(
                client, config, team_id, start_cursor, logger, resumable_source_manager, last_value
            )
        except requests.HTTPError as exc:
            # The connecting user's role may not grant access to every team. Skip teams we
            # can't read rather than failing the whole sync. Any other HTTP error re-raises.
            if exc.response is not None and exc.response.status_code in (403, 404):
                logger.warning(
                    f"Squadcast: no access to team {team_id} for endpoint '{endpoint}' "
                    f"(status={exc.response.status_code}), skipping"
                )
            else:
                raise

        # Advance the bookmark to the next team so a crash between teams resumes correctly.
        if index + 1 < len(remaining):
            resumable_source_manager.save_state(SquadcastResumeConfig(team_id=remaining[index + 1], cursor=None))


def squadcast_source(
    refresh_token: str,
    region: str | None,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SquadcastResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = SQUADCAST_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            refresh_token=refresh_token,
            region=region,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=[config.primary_key],
        # Incremental endpoints fan out over teams, so rows are not globally ordered by the
        # incremental field; "desc" makes the pipeline persist the watermark only after the
        # whole job completes instead of checkpointing a possibly-unsafe per-batch maximum.
        sort_mode="desc" if config.incremental_fields else "asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(
    refresh_token: str, region: str | None, endpoint: Optional[str] = None
) -> tuple[bool, int, str | None]:
    """Exchange the refresh token, then probe a cheap list endpoint.

    Returns ``(ok, status_code, error_message)``. ``status_code`` is 0 on transport failure.
    The caller decides how to treat 403 (valid token, missing access for the probed endpoint).
    """
    auth_host, api_host = _hosts_for_region(region)
    session = make_tracked_session()

    try:
        auth_response = session.get(
            f"{auth_host}/oauth/access-token",
            headers={"X-Refresh-Token": refresh_token},
            timeout=10,
        )
    except requests.exceptions.RequestException as e:
        return False, 0, str(e)

    if not auth_response.ok:
        if auth_response.status_code in (400, 401):
            return False, 401, "Invalid Squadcast refresh token"
        return False, auth_response.status_code, _error_message(auth_response)

    access_token = auth_response.json().get("data", {}).get("access_token")
    if not access_token:
        return False, 0, "Squadcast token exchange returned no access token"

    # Team-scoped endpoints require query params a probe can't guess, so probe /v3/teams for
    # them (the fan-out needs it anyway); org-level endpoints are probed directly.
    config = SQUADCAST_ENDPOINTS.get(endpoint) if endpoint else None
    probe_path = config.path if config is not None and config.team_param is None else "/v3/teams"

    try:
        response = session.get(
            f"{api_host}{probe_path}",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
    except requests.exceptions.RequestException as e:
        return False, 0, str(e)

    if response.status_code == 200:
        return True, 200, None
    if response.status_code == 401:
        return False, 401, "Invalid Squadcast refresh token"
    if response.status_code == 403:
        return False, 403, "Your Squadcast account does not have access to this resource"

    return False, response.status_code, _error_message(response)
