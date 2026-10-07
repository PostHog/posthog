import re
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from requests import Session
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.steam.settings import (
    OWNED_GAMES,
    PLAYERS,
    PLAYTIME_SNAPSHOTS,
    PRIMARY_KEYS,
)

STEAM_API_URL = "https://api.steampowered.com"
REQUEST_TIMEOUT_SECONDS = 30
# GetPlayerSummaries accepts at most this many ids in one request.
PLAYER_SUMMARIES_BATCH = 100

_STEAM_ID_RE = re.compile(r"^\d{17}$")


def parse_steam_ids(raw: str) -> list[str]:
    """The 64-bit Steam IDs in a comma or whitespace separated list, without duplicates."""
    steam_ids = list(dict.fromkeys(part for part in re.split(r"[\s,]+", raw.strip()) if part))
    invalid = [steam_id for steam_id in steam_ids if not _STEAM_ID_RE.match(steam_id)]
    if invalid:
        raise ValueError(f"Not a 17-digit Steam ID: {', '.join(invalid)}")
    if not steam_ids:
        raise ValueError("Add at least one Steam ID.")
    return steam_ids


def probe_api_key(api_key: str) -> int:
    """The HTTP status of a minimal request with this key, or -1 when Steam cannot be reached."""
    _ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{STEAM_API_URL}/ISteamUser/GetPlayerSummaries/v2/?key={api_key}&steamids=0",
        timeout=10,
    )
    return status if status is not None else -1


def _get(session: Session, api_key: str, path: str, params: dict[str, Any]) -> dict[str, Any]:
    response = session.get(f"{STEAM_API_URL}{path}", params={"key": api_key, **params}, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json().get("response") or {}


def _timestamp(value: int | None) -> datetime | None:
    return datetime.fromtimestamp(value, tz=UTC) if value else None


def _players(session: Session, api_key: str, steam_ids: list[str]) -> Iterator[list[dict[str, Any]]]:
    for start in range(0, len(steam_ids), PLAYER_SUMMARIES_BATCH):
        batch = steam_ids[start : start + PLAYER_SUMMARIES_BATCH]
        body = _get(session, api_key, "/ISteamUser/GetPlayerSummaries/v2/", {"steamids": ",".join(batch)})
        rows = [
            {
                "steam_id": player["steamid"],
                "persona_name": player.get("personaname"),
                "profile_url": player.get("profileurl"),
                # 3 is a public profile. Steam returns no games for any other value.
                "is_public": player.get("communityvisibilitystate") == 3,
                "country_code": player.get("loccountrycode"),
                "created_at": _timestamp(player.get("timecreated")),
            }
            for player in body.get("players") or []
        ]
        if rows:
            yield rows


def _owned_games(
    session: Session, api_key: str, steam_ids: list[str], logger: FilteringBoundLogger
) -> Iterator[list[dict[str, Any]]]:
    for steam_id in steam_ids:
        body = _get(
            session,
            api_key,
            "/IPlayerService/GetOwnedGames/v1/",
            {"steamid": steam_id, "include_appinfo": 1, "include_played_free_games": 1},
        )
        games = body.get("games") or []
        if not games:
            logger.warning(
                "Steam returned no games for a player. Their game details are probably private.", steam_id=steam_id
            )
            continue
        yield [
            {
                "steam_id": steam_id,
                "app_id": game["appid"],
                "name": game.get("name"),
                "playtime_forever_minutes": game.get("playtime_forever"),
                "playtime_2weeks_minutes": game.get("playtime_2weeks") or 0,
                "last_played_at": _timestamp(game.get("rtime_last_played")),
            }
            for game in games
        ]


def _playtime_snapshots(
    session: Session, api_key: str, steam_ids: list[str], logger: FilteringBoundLogger
) -> Iterator[list[dict[str, Any]]]:
    snapshot_date = datetime.now(UTC).date()
    for steam_id in steam_ids:
        body = _get(session, api_key, "/IPlayerService/GetRecentlyPlayedGames/v1/", {"steamid": steam_id})
        rows = [
            {
                "steam_id": steam_id,
                "app_id": game["appid"],
                "name": game.get("name"),
                "snapshot_date": snapshot_date,
                "playtime_forever_minutes": game.get("playtime_forever"),
                "playtime_2weeks_minutes": game.get("playtime_2weeks") or 0,
            }
            for game in body.get("games") or []
        ]
        if rows:
            yield rows


def steam_source(api_key: str, steam_ids: list[str], endpoint: str, logger: FilteringBoundLogger) -> SourceResponse:
    def get_rows() -> Iterator[list[dict[str, Any]]]:
        session = make_tracked_session(redact_values=(api_key,))
        if endpoint == PLAYERS:
            yield from _players(session, api_key, steam_ids)
        elif endpoint == OWNED_GAMES:
            yield from _owned_games(session, api_key, steam_ids, logger)
        else:
            yield from _playtime_snapshots(session, api_key, steam_ids, logger)

    if endpoint == PLAYTIME_SNAPSHOTS:
        # Steam reports running totals and no sessions. One row per game per day lets a query
        # subtract consecutive days to get the minutes played on each day.
        return SourceResponse(
            name=endpoint,
            items=get_rows,
            primary_keys=PRIMARY_KEYS[endpoint],
            partition_mode="datetime",
            partition_format="month",
            partition_keys=["snapshot_date"],
        )
    return SourceResponse(name=endpoint, items=get_rows, primary_keys=PRIMARY_KEYS[endpoint])
