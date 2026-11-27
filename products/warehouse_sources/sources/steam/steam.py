import re
import hmac
import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from django.conf import settings

from requests import HTTPError, RequestException, Response, Session
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.sources.sdk import (
    SourceResponse,
    make_tracked_session,
    redact_literal_values,
    validate_via_probe,
)
from products.warehouse_sources.sources.steam.settings import (
    CURRENT_PLAYERS,
    FRIENDS,
    GLOBAL_ACHIEVEMENT_PERCENTAGES,
    OWNED_GAMES,
    PLAYER_ACHIEVEMENTS,
    PLAYERS,
    PLAYTIME_SNAPSHOTS,
    PRIMARY_KEYS,
)

STEAM_API_URL = "https://api.steampowered.com"
REQUEST_TIMEOUT_SECONDS = 30
# GetPlayerSummaries accepts at most this many ids in one request.
PLAYER_SUMMARIES_BATCH = 100

_STEAM_ID_RE = re.compile(r"^[0-9]{17}$")


def split_steam_ids(raw: str) -> list[str]:
    return list(dict.fromkeys(part for part in re.split(r"[\s,]+", raw.strip()) if part))


def parse_steam_ids(raw: str) -> list[str]:
    """The 64-bit Steam IDs in a comma or whitespace separated list, without duplicates."""
    steam_ids = split_steam_ids(raw)
    invalid = [steam_id for steam_id in steam_ids if not _STEAM_ID_RE.match(steam_id)]
    if invalid:
        raise ValueError(f"Not a 17-digit Steam ID: {', '.join(invalid)}")
    if not steam_ids:
        raise ValueError("Add at least one Steam ID.")
    return steam_ids


def player_key(team_id: int, steam_id: str) -> str:
    """An opaque key for a player. It is stable across syncs and different in every project."""
    # A Steam ID is public and opens the player's profile, so the tables must not hold it.
    # The secret stops anyone from hashing every Steam ID to reverse a key.
    message = f"{team_id}:{steam_id}".encode()
    return hmac.new(settings.SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()[:32]


def probe_api_key(api_key: str) -> int:
    """The HTTP status of a minimal request with this key, or -1 when Steam cannot be reached."""
    _ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{STEAM_API_URL}/ISteamUser/GetPlayerSummaries/v2/?key={api_key}&steamids=0",
        timeout=10,
    )
    return status if status is not None else -1


def _send(session: Session, api_key: str | None, path: str, params: dict[str, Any]) -> Response:
    # The request URL carries the API key, and `requests` puts the URL in its error messages.
    key_params = {"key": api_key} if api_key else {}
    try:
        return session.get(f"{STEAM_API_URL}{path}", params={**key_params, **params}, timeout=REQUEST_TIMEOUT_SECONDS)
    except RequestException as error:
        if not api_key:
            raise
        raise type(error)(redact_literal_values(str(error), (api_key,))) from None


def _raise_for_status(response: Response) -> None:
    if not response.ok:
        kind = "Client" if response.status_code < 500 else "Server"
        raise HTTPError(f"{response.status_code} {kind} Error: {response.reason}", response=response)


def _json(response: Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _get(session: Session, api_key: str, path: str, params: dict[str, Any]) -> dict[str, Any]:
    response = _send(session, api_key, path, params)
    _raise_for_status(response)
    return response.json().get("response") or {}


def _timestamp(value: int | None) -> datetime | None:
    return datetime.fromtimestamp(value, tz=UTC) if value else None


def _players(session: Session, api_key: str, team_id: int, steam_ids: list[str]) -> Iterator[list[dict[str, Any]]]:
    for start in range(0, len(steam_ids), PLAYER_SUMMARIES_BATCH):
        batch = steam_ids[start : start + PLAYER_SUMMARIES_BATCH]
        body = _get(session, api_key, "/ISteamUser/GetPlayerSummaries/v2/", {"steamids": ",".join(batch)})
        rows = [
            {
                "player_key": player_key(team_id, player["steamid"]),
                # 3 is a public profile. Steam returns no games for any other value.
                "is_public": player.get("communityvisibilitystate") == 3,
            }
            for player in body.get("players") or []
        ]
        if rows:
            yield rows


def _owned_game_list(session: Session, api_key: str, steam_id: str) -> list[dict[str, Any]]:
    body = _get(
        session,
        api_key,
        "/IPlayerService/GetOwnedGames/v1/",
        {"steamid": steam_id, "include_appinfo": 1, "include_played_free_games": 1},
    )
    return body.get("games") or []


def _owned_games(
    session: Session, api_key: str, team_id: int, steam_ids: list[str], logger: FilteringBoundLogger
) -> Iterator[list[dict[str, Any]]]:
    for steam_id in steam_ids:
        games = _owned_game_list(session, api_key, steam_id)
        if not games:
            logger.warning(
                "Steam returned no games for a player. Their game details are probably private.",
                player_key=player_key(team_id, steam_id),
            )
            continue
        yield [
            {
                "player_key": player_key(team_id, steam_id),
                "app_id": game["appid"],
                "name": game.get("name"),
                "playtime_forever_minutes": game.get("playtime_forever"),
                "playtime_2weeks_minutes": game.get("playtime_2weeks") or 0,
                "last_played_at": _timestamp(game.get("rtime_last_played")),
            }
            for game in games
        ]


def _playtime_snapshots(
    session: Session, api_key: str, team_id: int, steam_ids: list[str], logger: FilteringBoundLogger
) -> Iterator[list[dict[str, Any]]]:
    snapshot_date = datetime.now(UTC).date()
    for steam_id in steam_ids:
        body = _get(session, api_key, "/IPlayerService/GetRecentlyPlayedGames/v1/", {"steamid": steam_id})
        rows = [
            {
                "player_key": player_key(team_id, steam_id),
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


def _player_achievements(
    session: Session, api_key: str, team_id: int, steam_ids: list[str], logger: FilteringBoundLogger
) -> Iterator[list[dict[str, Any]]]:
    for steam_id in steam_ids:
        key = player_key(team_id, steam_id)
        # A game never played has no unlocked achievements, so only played games with stats are read.
        app_ids = [
            game["appid"]
            for game in _owned_game_list(session, api_key, steam_id)
            if game.get("has_community_visible_stats") and game.get("playtime_forever")
        ]
        for app_id in app_ids:
            response = _send(
                session,
                api_key,
                "/ISteamUserStats/GetPlayerAchievements/v1/",
                {"steamid": steam_id, "appid": app_id, "l": "english"},
            )
            stats = _json(response).get("playerstats")
            # Steam answers 400 for a game with no achievements and 403 for a private profile, both
            # with `success: false` in the body. A rejected key gets a 403 with no such body.
            if response.status_code in (400, 403) and isinstance(stats, dict) and stats.get("success") is False:
                logger.info("Steam returned no achievements for a game.", player_key=key, app_id=app_id)
                continue
            _raise_for_status(response)
            rows = [
                {
                    "player_key": key,
                    "app_id": app_id,
                    "api_name": achievement["apiname"],
                    "name": achievement.get("name"),
                    "description": achievement.get("description"),
                    "achieved": bool(achievement.get("achieved")),
                    "unlocked_at": _timestamp(achievement.get("unlocktime")),
                }
                for achievement in (stats or {}).get("achievements") or []
            ]
            if rows:
                yield rows


def _friends(
    session: Session, api_key: str, team_id: int, steam_ids: list[str], logger: FilteringBoundLogger
) -> Iterator[list[dict[str, Any]]]:
    for steam_id in steam_ids:
        key = player_key(team_id, steam_id)
        response = _send(
            session, api_key, "/ISteamUser/GetFriendList/v1/", {"steamid": steam_id, "relationship": "friend"}
        )
        # Steam answers 401 for a private friend list. A rejected key gets a 403.
        if response.status_code == 401:
            logger.warning(
                "Steam returned no friends for a player. Their friend list is probably private.", player_key=key
            )
            continue
        _raise_for_status(response)
        rows = [
            {
                "player_key": key,
                # The same key as in the other tables, so a listed friend joins to their own rows.
                "friend_key": player_key(team_id, friend["steamid"]),
                "relationship": friend.get("relationship"),
                "friend_since": _timestamp(friend.get("friend_since")),
            }
            for friend in (_json(response).get("friendslist") or {}).get("friends") or []
        ]
        if rows:
            yield rows


def _owned_app_ids(session: Session, api_key: str, steam_ids: list[str], *, with_stats_only: bool) -> Iterator[int]:
    """The app ID of each game that any listed player owns, one time each."""
    seen: set[int] = set()
    for steam_id in steam_ids:
        for game in _owned_game_list(session, api_key, steam_id):
            app_id = game["appid"]
            if app_id in seen or (with_stats_only and not game.get("has_community_visible_stats")):
                continue
            seen.add(app_id)
            yield app_id


def _current_players(session: Session, api_key: str, steam_ids: list[str]) -> Iterator[list[dict[str, Any]]]:
    captured_at = datetime.now(UTC)
    for app_id in _owned_app_ids(session, api_key, steam_ids, with_stats_only=False):
        # The method needs no key. Steam answers 404 for an app it has no count for.
        response = _send(session, None, "/ISteamUserStats/GetNumberOfCurrentPlayers/v1/", {"appid": app_id})
        if response.status_code == 404:
            continue
        _raise_for_status(response)
        count = (_json(response).get("response") or {}).get("player_count")
        if count is not None:
            yield [{"app_id": app_id, "player_count": count, "captured_at": captured_at}]


def _percent(value: Any) -> float | None:
    # Steam sends the percentage as a string, for example "49.5".
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _global_achievement_percentages(
    session: Session, api_key: str, steam_ids: list[str]
) -> Iterator[list[dict[str, Any]]]:
    for app_id in _owned_app_ids(session, api_key, steam_ids, with_stats_only=True):
        # The method needs no key. Steam answers 403 for an app with no achievements.
        response = _send(
            session, None, "/ISteamUserStats/GetGlobalAchievementPercentagesForApp/v2/", {"gameid": app_id}
        )
        if response.status_code == 403:
            continue
        _raise_for_status(response)
        rows = [
            {"app_id": app_id, "api_name": achievement["name"], "percent": _percent(achievement.get("percent"))}
            for achievement in (_json(response).get("achievementpercentages") or {}).get("achievements") or []
        ]
        if rows:
            yield rows


def steam_source(
    api_key: str, team_id: int, steam_ids: list[str], endpoint: str, logger: FilteringBoundLogger
) -> SourceResponse:
    def get_rows() -> Iterator[list[dict[str, Any]]]:
        session = make_tracked_session(redact_values=(api_key,))
        if endpoint == PLAYERS:
            yield from _players(session, api_key, team_id, steam_ids)
        elif endpoint == OWNED_GAMES:
            yield from _owned_games(session, api_key, team_id, steam_ids, logger)
        elif endpoint == PLAYER_ACHIEVEMENTS:
            yield from _player_achievements(session, api_key, team_id, steam_ids, logger)
        elif endpoint == FRIENDS:
            yield from _friends(session, api_key, team_id, steam_ids, logger)
        elif endpoint == CURRENT_PLAYERS:
            yield from _current_players(session, api_key, steam_ids)
        elif endpoint == GLOBAL_ACHIEVEMENT_PERCENTAGES:
            yield from _global_achievement_percentages(session, api_key, steam_ids)
        else:
            yield from _playtime_snapshots(session, api_key, team_id, steam_ids, logger)

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
    if endpoint == CURRENT_PLAYERS:
        # Each sync reads the counts at that moment, so a series of syncs is the history.
        return SourceResponse(
            name=endpoint,
            items=get_rows,
            primary_keys=PRIMARY_KEYS[endpoint],
            partition_mode="datetime",
            partition_format="month",
            partition_keys=["captured_at"],
        )
    return SourceResponse(name=endpoint, items=get_rows, primary_keys=PRIMARY_KEYS[endpoint])
