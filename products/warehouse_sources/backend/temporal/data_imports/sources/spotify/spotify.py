from collections.abc import Callable, Iterator, Sequence
from dataclasses import field
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

from requests import Session
from structlog.types import FilteringBoundLogger

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.spotify.settings import (
    ACCOUNTS,
    PRIMARY_KEYS,
    RECENTLY_PLAYED,
)

SPOTIFY_API_URL = "https://api.spotify.com/v1"
# The API maximum. Spotify also keeps no more than this many plays for an account.
RECENTLY_PLAYED_LIMIT = 50
REQUEST_TIMEOUT_SECONDS = 30

# 401 means the grant was revoked or expired. 403 means the account is not on the user list of a
# Spotify app in development mode. Neither affects the other connected accounts.
ACCOUNT_SKIP_STATUSES = (401, 403)

ALL_ACCOUNTS_UNREADABLE = "None of the connected Spotify accounts could be read"

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@frozen
class SpotifyAccount:
    account_id: str
    access_token: str = field(repr=False)


@frozen
class SpotifyPlaysCursor:
    """The `played_at` of the newest synced play of each account, in Unix milliseconds, keyed by Spotify account id.

    One watermark for the whole table cannot do this job. It would skip the history of an account
    connected later, and the missed plays of an account that failed in an earlier run.
    """

    cursor_kind: ClassVar[str] = "spotify_recently_played"

    newest_played_at_ms: dict[str, int]


def _parse_played_at(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def _to_unix_ms(value: datetime) -> int:
    return (value - _EPOCH) // timedelta(milliseconds=1)


def _play_row(account_id: str, item: dict[str, Any]) -> dict[str, Any]:
    track = item.get("track") or {}
    artists = track.get("artists") or [{}]
    album = track.get("album") or {}
    context = item.get("context") or {}
    return {
        "account_id": account_id,
        "played_at": _parse_played_at(item["played_at"]),
        "track_id": track.get("id"),
        "track_name": track.get("name"),
        "primary_artist_id": artists[0].get("id"),
        "primary_artist_name": artists[0].get("name"),
        "album_id": album.get("id"),
        "album_name": album.get("name"),
        "duration_ms": track.get("duration_ms"),
        "explicit": track.get("explicit"),
        "context_type": context.get("type"),
        "context_uri": context.get("uri"),
        "track": track,
    }


def _fetch_recent_plays(session: Session, account: SpotifyAccount, after_ms: int | None) -> list[dict[str, Any]] | None:
    """The account's recent plays, newest first, or None when Spotify refuses this account."""
    params: dict[str, int] = {"limit": RECENTLY_PLAYED_LIMIT}
    if after_ms is not None:
        params["after"] = after_ms
    response = session.get(
        f"{SPOTIFY_API_URL}/me/player/recently-played",
        params=params,
        headers={"Authorization": f"Bearer {account.access_token}"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code in ACCOUNT_SKIP_STATUSES:
        return None
    response.raise_for_status()
    return response.json().get("items") or []


def recently_played_source(
    accounts: Sequence[SpotifyAccount],
    cursor: SpotifyPlaysCursor | None,
    stage_cursor: Callable[[SpotifyPlaysCursor], None],
    logger: FilteringBoundLogger,
) -> SourceResponse:
    newest_played_at_ms: dict[str, int] = {}

    def get_rows() -> Iterator[list[dict[str, Any]]]:
        session = make_tracked_session(redact_values=tuple(account.access_token for account in accounts))
        skipped = 0
        for account in accounts:
            after_ms = cursor.newest_played_at_ms.get(account.account_id) if cursor is not None else None
            items = _fetch_recent_plays(session, account, after_ms)
            if items is None:
                skipped += 1
                logger.warning(
                    "Skipping a Spotify account that could not be read. Its owner needs to reconnect it.",
                    account_id=account.account_id,
                )
                continue
            if after_ms is not None and len(items) == RECENTLY_PLAYED_LIMIT:
                logger.warning(
                    "A Spotify account filled the recently played window since the last sync, so some "
                    "plays may be missing. Sync this table more often.",
                    account_id=account.account_id,
                )
            if not items:
                continue
            rows = [_play_row(account.account_id, item) for item in items]
            newest_played_at_ms[account.account_id] = max(_to_unix_ms(row["played_at"]) for row in rows)
            yield rows

        if accounts and skipped == len(accounts):
            raise ValueError(ALL_ACCOUNTS_UNREADABLE)

    def on_complete() -> None:
        if newest_played_at_ms:
            stage_cursor(SpotifyPlaysCursor(newest_played_at_ms=newest_played_at_ms))

    return SourceResponse(
        name=RECENTLY_PLAYED,
        items=get_rows,
        primary_keys=PRIMARY_KEYS[RECENTLY_PLAYED],
        partition_mode="datetime",
        partition_format="month",
        partition_keys=["played_at"],
        # Spotify returns plays newest first.
        sort_mode="desc",
        on_complete=on_complete,
    )


def accounts_source(rows: list[dict[str, Any]]) -> SourceResponse:
    def get_rows() -> Iterator[list[dict[str, Any]]]:
        if rows:
            yield rows

    return SourceResponse(name=ACCOUNTS, items=get_rows, primary_keys=PRIMARY_KEYS[ACCOUNTS])
