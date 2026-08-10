import json
import hashlib
import dataclasses
from collections.abc import Iterator
from datetime import datetime
from typing import Any, Optional

import structlog
from requests import Response
from requests.exceptions import HTTPError
from structlog.types import FilteringBoundLogger
from urllib3.util.retry import Retry

from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import (
    coerce_datetime_to_utc,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import (
    DEFAULT_RETRY,
    make_tracked_session,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.dropbox.settings import (
    DROPBOX_ENDPOINTS,
    EVENT_ID_FIELD,
    DropboxEndpointConfig,
)

DROPBOX_API_HOST = "https://api.dropboxapi.com"
# Echoes back whatever `query` it is given and needs no scopes, so it probes the access token
# without implying the connection can reach any particular table.
CHECK_USER_PATH = "/2/check/user"
CHECK_USER_QUERY = "posthog"
REQUEST_TIMEOUT_SECONDS = 120
VALIDATE_TIMEOUT_SECONDS = 15

# Every Dropbox endpoint is a read-only POST-RPC, so POST is safe to retry — the shared
# policy excludes it. Derived from `DEFAULT_RETRY` so the retry/backoff settings stay in
# one place; the only intentional difference is adding POST.
DROPBOX_RETRY = Retry(
    total=DEFAULT_RETRY.total,
    backoff_factor=DEFAULT_RETRY.backoff_factor,
    status_forcelist=DEFAULT_RETRY.status_forcelist,
    allowed_methods=frozenset(DEFAULT_RETRY.allowed_methods or ()) | {"POST"},
    raise_on_status=DEFAULT_RETRY.raise_on_status,
)

# Dropbox reports endpoint-level failures as 409 with a tagged error body. These two tags mean
# the cursor we sent is no longer usable and the listing has to start over.
CURSOR_RESET_TAGS = ("reset", "invalid_cursor")


class DropboxCursorReset(Exception):
    """The pagination cursor expired or was invalidated by Dropbox."""


@dataclasses.dataclass
class DropboxResumeConfig:
    # The cursor is the whole resume position: Dropbox encodes the listing args (folder path,
    # recursion, audit-log time window) into it server-side.
    cursor: str


@dataclasses.dataclass
class DropboxCredentials:
    # Short-lived access token from the PostHog Dropbox OAuth integration. Renewing it is the
    # integration's job (`OauthIntegration.refresh_access_token` plus the scheduled sweep), not
    # this client's.
    access_token: str
    # Dropbox Business only: act as one team member, and/or resolve paths against the team space.
    team_member_id: str | None = None
    root_namespace_id: str | None = None


class DropboxClient:
    """POST-RPC client for `api.dropboxapi.com`."""

    def __init__(self, credentials: DropboxCredentials, logger: FilteringBoundLogger | None = None) -> None:
        self._credentials = credentials
        # Credential validation and the scope probe run outside a sync, with no job logger.
        self._logger = logger or structlog.get_logger(__name__)
        # Dropbox responses carry customer file/audit metadata and shared-link URLs (bearer
        # capabilities anyone can redeem) that the name-based sample scrubbers can't recognise,
        # so keep the session out of sample capture. Requests stay metered and logged.
        self._session = make_tracked_session(
            headers={"Content-Type": "application/json"},
            redact_values=(credentials.access_token,),
            retry=DROPBOX_RETRY,
            capture=False,
        )

    def _headers(self, select_user: bool) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self._credentials.access_token}"}
        if select_user and self._credentials.team_member_id:
            headers["Dropbox-API-Select-User"] = self._credentials.team_member_id
        if self._credentials.root_namespace_id:
            headers["Dropbox-API-Path-Root"] = json.dumps({".tag": "root", "root": self._credentials.root_namespace_id})
        return headers

    def post(
        self,
        path: str,
        body: dict[str, Any],
        select_user: bool = True,
        timeout: int = REQUEST_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
        response = self._send(path, body, select_user, timeout)

        if response.status_code == 409:
            summary = _error_summary(response)
            if any(summary.startswith(tag) for tag in CURSOR_RESET_TAGS):
                raise DropboxCursorReset(summary)

        if not response.ok:
            self._logger.error(f"Dropbox API error: status={response.status_code}, body={response.text}, path={path}")
            response.raise_for_status()

        result = response.json()
        return result if isinstance(result, dict) else {}

    def _send(self, path: str, body: dict[str, Any], select_user: bool, timeout: int) -> Response:
        return self._session.post(
            f"{DROPBOX_API_HOST}{path}",
            json=body,
            headers=self._headers(select_user),
            timeout=timeout,
        )


def _error_summary(response: Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return ""
    if not isinstance(body, dict):
        return ""
    summary = body.get("error_summary")
    if isinstance(summary, str):
        return summary
    error = body.get("error")
    if isinstance(error, dict):
        tag = error.get(".tag")
        if isinstance(tag, str):
            return tag
    return ""


def normalize_folder_path(folder_path: str | None) -> str:
    """Dropbox wants "" for the root and a leading-slash, no-trailing-slash path otherwise."""
    path = (folder_path or "").strip().rstrip("/")
    if not path or path == "/":
        return ""
    return path if path.startswith("/") else f"/{path}"


def format_time(value: Any) -> str | None:
    """Format an incremental watermark for `team_log/get_events`, which rejects sub-second precision."""
    parsed = coerce_datetime_to_utc(value)
    if parsed is None and isinstance(value, str):
        try:
            parsed = coerce_datetime_to_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            return None
    if parsed is None:
        return None
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")


def _rename_tag_keys(row: dict[str, Any]) -> dict[str, Any]:
    """Rename Dropbox's `.tag` union discriminators to `tag`, at every nesting level.

    A leading dot in a column name is awkward to query and to express as a nested Delta field.
    """
    result: dict[str, Any] = {}
    for key, value in row.items():
        new_key = "tag" if key == ".tag" and "tag" not in row else key
        result[new_key] = _rename_tags_in_value(value)
    return result


def _rename_tags_in_value(value: Any) -> Any:
    if isinstance(value, dict):
        return _rename_tag_keys(value)
    if isinstance(value, list):
        return [_rename_tags_in_value(item) for item in value]
    return value


def _event_id(event: dict[str, Any]) -> str:
    """Stable synthetic id for an audit event, which Dropbox returns without one."""
    return hashlib.sha256(json.dumps(event, sort_keys=True, default=str).encode()).hexdigest()


def normalize_row(endpoint: str, item: dict[str, Any]) -> dict[str, Any]:
    if endpoint == "team_members":
        # `members/list_v2` nests everything queryable under `profile`; lift it to the row root
        # so the primary key and the member's email/name are top-level columns.
        row = {**(item.get("profile") or {})}
        for key in ("roles", "role"):
            if key in item:
                row[key] = item[key]
    else:
        row = dict(item)

    row = _rename_tag_keys(row)

    if endpoint == "team_events":
        row[EVENT_ID_FIELD] = _event_id(row)

    return row


def _build_request(
    config: DropboxEndpointConfig,
    cursor: str | None,
    folder_path: str | None,
    start_time: str | None,
) -> tuple[str, dict[str, Any]]:
    if cursor is not None:
        # `/continue` endpoints take only the cursor; list_shared_links takes it on the same path.
        return config.continue_path or config.path, {"cursor": cursor}

    body: dict[str, Any] = dict(config.start_args)
    if config.name == "files":
        body["path"] = normalize_folder_path(folder_path)
    if config.name == "team_events" and start_time is not None:
        body["time"] = {"start_time": start_time}
    return config.path, body


def validate_credentials(credentials: DropboxCredentials) -> tuple[bool, str | None]:
    """Confirm the connected account's access token still works.

    Only `check/user` is probed: it needs no scopes, so a connection that can reach some tables
    but not others still connects. Per-endpoint scope gaps surface through
    `get_endpoint_permissions`.
    """
    try:
        result = DropboxClient(credentials).post(
            CHECK_USER_PATH,
            {"query": CHECK_USER_QUERY},
            select_user=False,
            timeout=VALIDATE_TIMEOUT_SECONDS,
        )
    except Exception:
        return False, "Could not authenticate with Dropbox. Reconnect your Dropbox account."

    if result.get("result") != CHECK_USER_QUERY:
        return False, "Dropbox did not accept the connected account. Reconnect your Dropbox account."
    return True, None


def check_endpoint_access(credentials: DropboxCredentials, endpoints: list[str]) -> dict[str, str | None]:
    """Probe each endpoint with a one-row request to report which tables the app can reach."""
    client = DropboxClient(credentials)
    results: dict[str, str | None] = {}

    for name in endpoints:
        config = DROPBOX_ENDPOINTS.get(name)
        if config is None:
            results[name] = None
            continue

        path, body = _build_request(config, cursor=None, folder_path=None, start_time=None)
        if "limit" in body:
            body["limit"] = 1
        try:
            client.post(path, body, select_user=not config.is_team_endpoint)
            results[name] = None
        except HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            if status == 403:
                results[name] = (
                    "Your Dropbox connection cannot read this table. The team tables need a Dropbox Business "
                    "team connection, which PostHog does not request."
                )
            elif status == 409:
                results[name] = "Dropbox rejected this request. The folder path may not exist."
            else:
                # Throttles, 5xx and network blips aren't permission problems.
                results[name] = None
        except Exception:
            results[name] = None

    return results


def get_rows(
    credentials: DropboxCredentials,
    endpoint: str,
    folder_path: str | None,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DropboxResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = DROPBOX_ENDPOINTS[endpoint]
    client = DropboxClient(credentials, logger)
    select_user = not config.is_team_endpoint

    start_time = (
        format_time(db_incremental_field_last_value)
        if should_use_incremental_field and db_incremental_field_last_value is not None
        else None
    )

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor = resume_config.cursor if resume_config is not None else None
    if resume_config is not None:
        logger.debug(f"Dropbox: resuming {endpoint} from a saved cursor")

    while True:
        path, body = _build_request(config, cursor, folder_path, start_time)
        try:
            page = client.post(path, body, select_user=select_user)
        except DropboxCursorReset:
            if cursor is None:
                raise
            # The cursor went stale, so the only way forward is to list from the start. The
            # merge on primary key makes the re-listed rows idempotent.
            logger.warning(f"Dropbox: cursor for {endpoint} was reset, restarting the listing")
            resumable_source_manager.clear_state()
            cursor = None
            continue

        rows = [normalize_row(endpoint, item) for item in page.get(config.data_key) or []]
        keyed_rows = [row for row in rows if row.get(config.primary_key) is not None]
        if len(keyed_rows) != len(rows):
            logger.warning(
                f"Dropbox: skipped {len(rows) - len(keyed_rows)} {endpoint} rows with no {config.primary_key}"
            )

        if keyed_rows:
            yield keyed_rows

        cursor = page.get("cursor")
        has_more = bool(page.get("has_more", cursor is not None)) and bool(cursor)
        if not has_more:
            break

        # Saved after the yield, so a crash re-yields the last page (merge dedupes it) instead
        # of skipping it.
        resumable_source_manager.save_state(DropboxResumeConfig(cursor=str(cursor)))

    resumable_source_manager.clear_state()


def dropbox_source(
    credentials: DropboxCredentials,
    endpoint: str,
    folder_path: str | None,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DropboxResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = DROPBOX_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            credentials=credentials,
            endpoint=endpoint,
            folder_path=folder_path,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Dropbox documents no ordering for any of these listings, and cursor pagination
        # accepts no sort argument. "desc" is the safe read: the watermark is committed once
        # at the end of a completed run rather than after every batch.
        sort_mode="desc",
    )
