import re
import hmac
import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from django.conf import settings

from requests import HTTPError, Session
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.sources.chess_com.settings import GAMES, PRIMARY_KEYS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

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


def chess_com_source(
    team_id: int, usernames: list[str], endpoint: str, since: datetime | None, logger: FilteringBoundLogger
) -> SourceResponse:
    def get_rows() -> Iterator[list[dict[str, Any]]]:
        session = make_tracked_session(headers=HEADERS)
        if endpoint == GAMES:
            yield from _games(session, team_id, usernames, since, logger)
        else:
            yield from _ratings(session, team_id, usernames)

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
