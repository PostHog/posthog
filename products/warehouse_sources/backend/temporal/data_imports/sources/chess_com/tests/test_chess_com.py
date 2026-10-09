import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.chess_com.chess_com import (
    chess_com_source,
    opaque_key,
    parse_usernames,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.chess_com.source import ChessComSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.chesscom import (
    ChessComSourceConfig,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.chess_com"
API = "https://api.chess.com/pub"
TEAM_ID = 1
GAME_URL = "https://www.chess.com/game/live/1"


def _response(status_code: int, body: dict[str, Any] | None = None) -> Response:
    response = Response()
    response.status_code = status_code
    response._content = json.dumps(body or {}).encode()
    return response


def _session(pages: dict[str, dict[str, Any]]) -> MagicMock:
    session = MagicMock()
    session.get.side_effect = lambda url, **kwargs: _response(200, pages[url]) if url in pages else _response(404)
    return session


def _rows(
    endpoint: str, session: MagicMock, usernames: list[str], since: datetime | None = None
) -> list[dict[str, Any]]:
    with patch(f"{MODULE}.chess_com.make_tracked_session", return_value=session):
        response = chess_com_source(TEAM_ID, usernames, endpoint, since, MagicMock())
        return [row for batch in cast(Iterable[list[dict[str, Any]]], response.items()) for row in batch]


def _game(white: str, black: str, white_result: str, black_result: str) -> dict[str, Any]:
    return {
        "url": GAME_URL,
        "pgn": "1. e4 e5",
        "end_time": 1791288000,
        "time_class": "blitz",
        "time_control": "180+2",
        "rules": "chess",
        "rated": True,
        "accuracies": {"white": 91.5, "black": 80.1},
        "white": {"username": white, "rating": 1510, "result": white_result},
        "black": {"username": black, "rating": 1490, "result": black_result},
    }


class TestChessCom:
    def test_usernames_are_split_lowercased_and_deduplicated(self) -> None:
        assert parse_usernames(" Ada,\ngrace ada\n") == ["ada", "grace"]

    @parameterized.expand(
        [
            ("ab",),
            ("ada lovelace!",),
            ("https://www.chess.com/member/ada",),
            ("",),
            (", ".join(f"player{n}" for n in range(51)),),
        ]
    )
    def test_anything_but_a_username_is_rejected(self, raw: str) -> None:
        with pytest.raises(ValueError):
            parse_usernames(raw)

    @parameterized.expand(
        [
            ("Ada", "grace", "win", "resigned", "white", "win", 1510, 1490, 91.5),
            ("grace", "ADA", "win", "checkmated", "black", "loss", 1490, 1510, 80.1),
            ("ada", "grace", "repetition", "repetition", "white", "draw", 1510, 1490, 91.5),
        ]
    )
    def test_a_game_is_told_from_the_listed_player_side(
        self,
        white: str,
        black: str,
        white_result: str,
        black_result: str,
        color: str,
        outcome: str,
        rating: int,
        opponent_rating: int,
        accuracy: float,
    ) -> None:
        archive = f"{API}/player/ada/games/2026/10"
        session = _session(
            {
                f"{API}/player/ada/games/archives": {"archives": [archive]},
                archive: {"games": [_game(white, black, white_result, black_result)]},
            }
        )

        rows = _rows("games", session, ["ada"])

        assert rows == [
            {
                "player_key": opaque_key(TEAM_ID, "ada"),
                "game_key": opaque_key(TEAM_ID, GAME_URL),
                "end_time": datetime.fromtimestamp(1791288000, tz=UTC),
                "time_class": "blitz",
                "time_control": "180+2",
                "rules": "chess",
                "rated": True,
                "color": color,
                "outcome": outcome,
                "result": white_result if color == "white" else black_result,
                "rating": rating,
                "opponent_rating": opponent_rating,
                "accuracy": accuracy,
            }
        ]
        assert "ada" not in json.dumps(rows, default=str) and "grace" not in json.dumps(rows, default=str)
        assert opaque_key(TEAM_ID, "ada") != opaque_key(TEAM_ID + 1, "ada")

    def test_an_incremental_sync_skips_months_before_the_last_game(self) -> None:
        archives = [f"{API}/player/ada/games/2026/{month}" for month in ("08", "09", "10")]
        session = _session(
            {
                f"{API}/player/ada/games/archives": {"archives": archives},
                **{archive: {"games": [_game("ada", "grace", "win", "resigned")]} for archive in archives},
            }
        )

        rows = _rows("games", session, ["ada"], since=datetime(2026, 9, 20, tzinfo=UTC))

        assert len(rows) == 2
        assert archives[0] not in [call.args[0] for call in session.get.call_args_list]

    def test_an_unknown_player_does_not_block_the_other_players(self) -> None:
        archive = f"{API}/player/ada/games/2026/10"
        session = _session(
            {
                f"{API}/player/ada/games/archives": {"archives": [archive]},
                archive: {"games": [_game("ada", "grace", "win", "resigned")]},
            }
        )

        rows = _rows("games", session, ["nobody", "ada"])

        assert [row["player_key"] for row in rows] == [opaque_key(TEAM_ID, "ada")]

    def test_ratings_have_one_row_per_game_speed_the_player_has_played(self) -> None:
        stats = {
            "chess_blitz": {
                "last": {"rating": 1510, "date": 1791288000},
                "best": {"rating": 1600},
                "record": {"win": 10, "loss": 4, "draw": 1},
            },
            "tactics": {"highest": {"rating": 2000}},
        }
        session = _session({f"{API}/player/ada/stats": stats})

        assert _rows("ratings", session, ["ada"]) == [
            {
                "player_key": opaque_key(TEAM_ID, "ada"),
                "time_class": "blitz",
                "rating": 1510,
                "best_rating": 1600,
                "wins": 10,
                "losses": 4,
                "draws": 1,
                "last_rated_at": datetime.fromtimestamp(1791288000, tz=UTC),
            }
        ]

    def test_a_refused_request_fails_the_sync_with_the_status_and_reason(self) -> None:
        response = _response(403)
        response.reason = "Forbidden"
        session = MagicMock()
        session.get.return_value = response

        with pytest.raises(HTTPError) as error:
            _rows("ratings", session, ["ada"])

        assert str(error.value) == "403 Client Error: Forbidden"

    @parameterized.expand(
        [
            ({"ada": 200, "grace": 200}, "ada, grace", True, None),
            ({"ada": 200, "grace": 404}, "ada, grace", False, "no player named grace"),
            ({"ada": -1}, "ada", False, "reach Chess.com"),
            ({}, "a!", False, "Not a Chess.com username"),
        ]
    )
    def test_credentials_check_reports_what_to_fix(
        self, statuses: dict[str, int], usernames: str, valid: bool, message: str | None
    ) -> None:
        with patch(f"{MODULE}.source.probe_username", side_effect=lambda username: statuses[username]):
            result = ChessComSource().validate_credentials(ChessComSourceConfig(usernames=usernames), TEAM_ID)

        assert result[0] is valid
        assert (message is None and result[1] is None) or (message is not None and message in (result[1] or ""))
