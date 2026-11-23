import re
import hmac
import hashlib
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

from django.conf import settings

from requests import HTTPError, Session
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.sources.chess_com.settings import (
    GAMES,
    LEADERBOARDS,
    PLAYERS,
    PRIMARY_KEYS,
    RATINGS,
    TEAM_MATCHES,
    TOURNAMENTS,
)
from products.warehouse_sources.sources.sdk import (
    SourceResponse,
    frozen,
    make_tracked_session,
    reach_safe_point,
    validate_via_probe,
)

CHESS_COM_API_URL = "https://api.chess.com/pub"
REQUEST_TIMEOUT_SECONDS = 30
# Every username costs one request per month of history, sent one at a time.
MAX_USERNAMES = 50
# Chess.com asks every client to identify itself, and blocks clients that do not.
HEADERS = {"User-Agent": "PostHog data warehouse (https://posthog.com)"}

_USERNAME_RE = re.compile(r"^[A-Za-z0-9_-]{3,25}$")
_ARCHIVE_MONTH_RE = re.compile(r"/games/(\d{4})/(\d{2})$")
_DRAW_RESULTS = frozenset({"agreed", "repetition", "stalemate", "insufficient", "50move", "timevsinsufficient"})
_RATING_CLASSES = {"chess_daily": "daily", "chess_rapid": "rapid", "chess_blitz": "blitz", "chess_bullet": "bullet"}
_PGN_TAG_RE = re.compile(r'^\[(\w+)\s+"((?:[^"\\]|\\.)*)"\]$')
# An allowlist, because tags such as White, Black, Termination, Link, Tournament and Match name a player or open the game.
_PGN_KEPT_TAGS = frozenset(
    {
        "Site",
        "Date",
        "Round",
        "Result",
        "CurrentPosition",
        "Timezone",
        "ECO",
        "ECOUrl",
        "UTCDate",
        "UTCTime",
        "WhiteElo",
        "BlackElo",
        "TimeControl",
        "StartTime",
        "EndDate",
        "EndTime",
        "SetUp",
        "FEN",
        "Variant",
    }
)
# The PGN standard requires these tags, so they stay with the value for unknown.
_PGN_MASKED_TAGS = frozenset({"Event", "White", "Black"})
# Tournament and team match lists group their entries by these states.
_LIST_STATES = ("finished", "in_progress", "registered")

RowsBuilder = Callable[[int, str, dict[str, Any]], list[dict[str, Any]]]


def split_usernames(raw: str) -> list[str]:
    return list(dict.fromkeys(part.lower() for part in re.split(r"[\s,]+", raw.strip()) if part))


def parse_usernames(raw: str) -> list[str]:
    """The Chess.com usernames in a comma or whitespace separated list, without duplicates."""
    usernames = split_usernames(raw)
    invalid = [username for username in usernames if not _USERNAME_RE.match(username)]
    if invalid:
        raise ValueError(f"Not a Chess.com username: {', '.join(invalid)}")
    if not usernames:
        raise ValueError("Add at least one username.")
    if len(usernames) > MAX_USERNAMES:
        raise ValueError(f"Add at most {MAX_USERNAMES} usernames. The list has {len(usernames)}.")
    return usernames


def opaque_key(team_id: int, value: str) -> str:
    """An opaque key for a player or a game. It is stable across syncs and different in every project."""
    # A username or a game URL opens the player's public profile, so the tables must not hold either.
    # The secret stops anyone from hashing known usernames to reverse a key.
    message = f"{team_id}:{value}".encode()
    return hmac.new(settings.SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()[:32]


def probe_username(username: str) -> int:
    """The HTTP status of the player's profile, or -1 when Chess.com cannot be reached."""
    _ok, status = validate_via_probe(
        lambda: make_tracked_session(headers=HEADERS), f"{CHESS_COM_API_URL}/player/{username}", timeout=10
    )
    return status if status is not None else -1


def _get(session: Session, url: str) -> dict[str, Any] | None:
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    if response.status_code == 404:
        return None
    if not response.ok:
        kind = "Client" if response.status_code < 500 else "Server"
        raise HTTPError(f"{response.status_code} {kind} Error: {response.reason}", response=response)
    return response.json()


def _timestamp(value: int | None) -> datetime | None:
    return datetime.fromtimestamp(value, tz=UTC) if value else None


def _outcome(result: str | None) -> str | None:
    if result is None:
        return None
    if result == "win":
        return "win"
    return "draw" if result in _DRAW_RESULTS else "loss"


def masked_pgn(pgn: str | None) -> str | None:
    """The game's PGN with the moves and only the tags that do not identify a player or the game."""
    if not pgn:
        return None
    lines = []
    for line in pgn.splitlines():
        if not line.lstrip().startswith("["):
            lines.append(line)
            continue
        tag = _PGN_TAG_RE.match(line.strip())
        if tag and tag[1] in _PGN_KEPT_TAGS:
            lines.append(line.strip())
        elif tag and tag[1] in _PGN_MASKED_TAGS:
            lines.append(f'[{tag[1]} "?"]')
    return "\n".join(lines)


def _game_row(team_id: int, username: str, game: dict[str, Any]) -> dict[str, Any] | None:
    sides = {color: game.get(color) or {} for color in ("white", "black")}
    color = next((c for c, side in sides.items() if str(side.get("username", "")).lower() == username), None)
    if color is None or not game.get("url"):
        return None
    player = sides[color]
    opponent = sides["black" if color == "white" else "white"]
    return {
        "player_key": opaque_key(team_id, username),
        "game_key": opaque_key(team_id, game["url"]),
        "end_time": _timestamp(game.get("end_time")),
        "time_class": game.get("time_class"),
        "time_control": game.get("time_control"),
        "rules": game.get("rules"),
        "rated": game.get("rated"),
        "color": color,
        "outcome": _outcome(player.get("result")),
        "result": player.get("result"),
        "rating": player.get("rating"),
        "opponent_rating": opponent.get("rating"),
        "accuracy": (game.get("accuracies") or {}).get(color),
        "pgn": masked_pgn(game.get("pgn")),
    }


def _games(
    session: Session, team_id: int, usernames: list[str], since: datetime | None, logger: FilteringBoundLogger
) -> Iterator[list[dict[str, Any]]]:
    # Chess.com groups archives by UTC month.
    if since and since.tzinfo:
        since = since.astimezone(UTC)
    for username in usernames:
        body = _get(session, f"{CHESS_COM_API_URL}/player/{username}/games/archives")
        if body is None:
            logger.warning("Chess.com has no player with this username.", player_key=opaque_key(team_id, username))
            continue
        for archive_url in body.get("archives") or []:
            month = _ARCHIVE_MONTH_RE.search(archive_url)
            # An archive holds one month, so a month before the last synced game has nothing new.
            if since and month and (int(month[1]), int(month[2])) < (since.year, since.month):
                continue
            games = (_get(session, archive_url) or {}).get("games") or []
            rows = [row for game in games if (row := _game_row(team_id, username, game))]
            if rows:
                yield rows


def _ratings(session: Session, team_id: int, usernames: list[str]) -> Iterator[list[dict[str, Any]]]:
    for username in usernames:
        body = _get(session, f"{CHESS_COM_API_URL}/player/{username}/stats") or {}
        rows = []
        for key, time_class in _RATING_CLASSES.items():
            stats = body.get(key)
            if not stats:
                continue
            last = stats.get("last") or {}
            record = stats.get("record") or {}
            rows.append(
                {
                    "player_key": opaque_key(team_id, username),
                    "time_class": time_class,
                    "rating": last.get("rating"),
                    "best_rating": (stats.get("best") or {}).get("rating"),
                    "wins": record.get("win"),
                    "losses": record.get("loss"),
                    "draws": record.get("draw"),
                    "last_rated_at": _timestamp(last.get("date")),
                }
            )
        if rows:
            yield rows


def _country_code(country_url: str | None) -> str | None:
    """The ISO code at the end of a country URL such as https://api.chess.com/pub/country/US."""
    if not country_url:
        return None
    return country_url.rstrip("/").rsplit("/", 1)[-1] or None


def _player_rows(team_id: int, username: str, profile: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "player_key": opaque_key(team_id, username),
            "title": profile.get("title"),
            "status": profile.get("status"),
            "country": _country_code(profile.get("country")),
            "joined_at": _timestamp(profile.get("joined")),
            "last_online_at": _timestamp(profile.get("last_online")),
            "followers": profile.get("followers"),
            "league": profile.get("league"),
            "fide_rating": profile.get("fide"),
            "is_streamer": profile.get("is_streamer"),
            "verified": profile.get("verified"),
        }
    ]


@frozen
class _ListedEntry:
    state: str
    ref: str
    entry: dict[str, Any]


def _listed_entries(body: dict[str, Any]) -> Iterator[_ListedEntry]:
    """Each entry of a tournament or team match list with its state and API URL, once per URL."""
    seen: set[str] = set()
    for state in _LIST_STATES:
        for entry in body.get(state) or []:
            ref = entry.get("@id") or entry.get("url")
            if ref and ref not in seen:
                seen.add(ref)
                yield _ListedEntry(state=state, ref=ref, entry=entry)


def _tournament_rows(team_id: int, username: str, body: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "player_key": opaque_key(team_id, username),
            "tournament_key": opaque_key(team_id, listed.ref),
            "state": listed.state,
            "status": listed.entry.get("status"),
            "type": listed.entry.get("type"),
            "time_class": listed.entry.get("time_class"),
            "wins": listed.entry.get("wins"),
            "losses": listed.entry.get("losses"),
            "draws": listed.entry.get("draws"),
            "points_awarded": listed.entry.get("points_awarded"),
            "placement": listed.entry.get("placement"),
            "total_players": listed.entry.get("total_players"),
        }
        for listed in _listed_entries(body)
    ]


def _team_match_rows(team_id: int, username: str, body: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for listed in _listed_entries(body):
        results = listed.entry.get("results") or {}
        club = listed.entry.get("club")
        rows.append(
            {
                "player_key": opaque_key(team_id, username),
                "match_key": opaque_key(team_id, listed.ref),
                "club_key": opaque_key(team_id, club) if club else None,
                "state": listed.state,
                "result_as_white": results.get("played_as_white"),
                "result_as_black": results.get("played_as_black"),
                "outcome_as_white": _outcome(results.get("played_as_white")),
                "outcome_as_black": _outcome(results.get("played_as_black")),
            }
        )
    return rows


def _per_player(
    session: Session, team_id: int, usernames: list[str], path: str, build_rows: RowsBuilder
) -> Iterator[list[dict[str, Any]]]:
    for username in usernames:
        body = _get(session, f"{CHESS_COM_API_URL}/player/{username}{path}")
        rows = build_rows(team_id, username, body) if body else []
        if rows:
            yield rows
        else:
            reach_safe_point()


def _leaderboards(session: Session, team_id: int) -> Iterator[list[dict[str, Any]]]:
    body = _get(session, f"{CHESS_COM_API_URL}/leaderboards") or {}
    for leaderboard, entries in body.items():
        rows = []
        for entry in entries or []:
            username = str(entry.get("username") or "").lower()
            if not username:
                continue
            trend_score = entry.get("trend_score") or {}
            trend_rank = entry.get("trend_rank") or {}
            rows.append(
                {
                    "leaderboard": leaderboard,
                    # Keyed like the listed players, so a listed player on a leaderboard joins to the other tables.
                    "player_key": opaque_key(team_id, username),
                    "rank": entry.get("rank"),
                    "score": entry.get("score"),
                    "title": entry.get("title"),
                    "status": entry.get("status"),
                    "country": _country_code(entry.get("country")),
                    "wins": entry.get("win_count"),
                    "losses": entry.get("loss_count"),
                    "draws": entry.get("draw_count"),
                    "score_trend_direction": trend_score.get("direction"),
                    "score_trend_delta": trend_score.get("delta"),
                    "rank_trend_direction": trend_rank.get("direction"),
                    "rank_trend_delta": trend_rank.get("delta"),
                }
            )
        if rows:
            yield rows


def chess_com_source(
    team_id: int, usernames: list[str], endpoint: str, since: datetime | None, logger: FilteringBoundLogger
) -> SourceResponse:
    def get_rows() -> Iterator[list[dict[str, Any]]]:
        session = make_tracked_session(headers=HEADERS)
        if endpoint == GAMES:
            yield from _games(session, team_id, usernames, since, logger)
        elif endpoint == RATINGS:
            yield from _ratings(session, team_id, usernames)
        elif endpoint == PLAYERS:
            yield from _per_player(session, team_id, usernames, "", _player_rows)
        elif endpoint == TOURNAMENTS:
            yield from _per_player(session, team_id, usernames, "/tournaments", _tournament_rows)
        elif endpoint == TEAM_MATCHES:
            yield from _per_player(session, team_id, usernames, "/matches", _team_match_rows)
        elif endpoint == LEADERBOARDS:
            yield from _leaderboards(session, team_id)

    if endpoint == GAMES:
        return SourceResponse(
            name=endpoint,
            items=get_rows,
            primary_keys=PRIMARY_KEYS[endpoint],
            partition_mode="datetime",
            partition_format="month",
            partition_keys=["end_time"],
        )
    return SourceResponse(name=endpoint, items=get_rows, primary_keys=PRIMARY_KEYS[endpoint])
