from datetime import UTC, date, datetime
from typing import Any

import pytest
import time_machine
from unittest.mock import patch

from parameterized import parameterized
from requests import (
    ConnectionError as RequestsConnectionError,
    HTTPError,
)

from products.warehouse_sources.sources.sdk.testing import RecordedRequest, ScriptedResponse, SourceDriver, always
from products.warehouse_sources.sources.steam._config import SteamSourceConfig
from products.warehouse_sources.sources.steam.source import SteamSource
from products.warehouse_sources.sources.steam.steam import parse_steam_ids, player_key

ADA = "76561197960287930"
GRACE = "76561197960435530"
TEAM_ID = 1
OWNED_GAMES_PATH = "/IPlayerService/GetOwnedGames/v1/"
PORTAL = {"appid": 620, "name": "Portal 2", "playtime_forever": 600, "has_community_visible_stats": True}


def _ok(body: dict[str, Any] | None = None) -> ScriptedResponse:
    return ScriptedResponse(json={"response": body or {}})


def _driver(api_key: str = "key", steam_ids: str = ADA) -> SourceDriver:
    return SourceDriver(SteamSource(), SteamSourceConfig(api_key=api_key, steam_ids=steam_ids))


class TestSteam:
    def test_ids_are_split_and_deduplicated(self) -> None:
        assert parse_steam_ids(f" {ADA},\n{GRACE} {ADA}\n") == [ADA, GRACE]

    @parameterized.expand(
        [
            ("gabe",),
            ("7656119796028793",),
            ("７６５６１１９７９６０２８７９３０",),
            (f"{ADA}, https://steamcommunity.com/id/gabe",),
            ("",),
        ]
    )
    def test_anything_but_17_digit_ids_is_rejected(self, raw: str) -> None:
        with pytest.raises(ValueError):
            parse_steam_ids(raw)

    def test_a_private_profile_does_not_block_the_other_players(self) -> None:
        game = {"appid": 620, "name": "Portal 2", "playtime_forever": 600, "rtime_last_played": 1791288000}

        def script(request: RecordedRequest) -> ScriptedResponse:
            return _ok() if request.param("steamid") == GRACE else _ok({"games": [game]})

        result = _driver(steam_ids=f"{GRACE},{ADA}").run("owned_games", script)

        assert [(row["player_key"], row["app_id"], row["playtime_2weeks_minutes"]) for row in result.rows] == [
            (player_key(TEAM_ID, ADA), 620, 0)
        ]

    def test_snapshots_are_keyed_by_the_day_they_were_read(self) -> None:
        game = {"appid": 620, "name": "Portal 2", "playtime_forever": 600, "playtime_2weeks": 90}

        with time_machine.travel("2026-10-07T23:30:00Z", tick=False):
            result = _driver().run("playtime_snapshots", [_ok({"games": [game]})])

        assert result.rows == [
            {
                "player_key": player_key(TEAM_ID, ADA),
                "app_id": 620,
                "name": "Portal 2",
                "snapshot_date": date(2026, 10, 7),
                "playtime_forever_minutes": 600,
                "playtime_2weeks_minutes": 90,
            }
        ]

    def test_no_table_holds_anything_that_identifies_the_player(self) -> None:
        player = {
            "steamid": ADA,
            "personaname": "ada",
            "profileurl": f"https://steamcommunity.com/profiles/{ADA}/",
            "communityvisibilitystate": 3,
            "loccountrycode": "GB",
            "timecreated": 1063407589,
        }

        result = _driver().run("players", [_ok({"players": [player]})])

        assert result.rows == [{"player_key": player_key(TEAM_ID, ADA), "is_public": True}]
        assert ADA not in player_key(TEAM_ID, ADA)
        assert player_key(TEAM_ID, ADA) != player_key(TEAM_ID + 1, ADA)

    @parameterized.expand(
        [
            ("players", [ScriptedResponse(status=403, json={"response": {}})]),
            ("friends", [ScriptedResponse(status=403, body=b"<html>Forbidden</html>")]),
            (
                "player_achievements",
                [_ok({"games": [PORTAL]}), ScriptedResponse(status=403, body=b"<html>Forbidden</html>")],
            ),
        ]
    )
    def test_a_rejected_key_fails_the_sync_without_the_key_in_the_error(
        self, endpoint: str, responses: list[ScriptedResponse]
    ) -> None:
        result = _driver().run(endpoint, responses)

        assert isinstance(result.raised, HTTPError)
        assert str(result.raised) == "403 Client Error: Forbidden"

    def test_a_connection_failure_keeps_the_key_out_of_the_error(self) -> None:
        result = _driver(api_key="secret-key").run(
            "players",
            always(RequestsConnectionError("Max retries exceeded with url: /?key=secret-key&steamids=1")),
        )

        assert isinstance(result.raised, RequestsConnectionError)
        assert "secret-key" not in str(result.raised)

    def test_achievements_are_read_for_played_games_with_stats(self) -> None:
        games = [
            PORTAL,
            {"appid": 400, "playtime_forever": 0, "has_community_visible_stats": True},
            {"appid": 10, "playtime_forever": 900},
        ]
        achievements = [
            {"apiname": "ACH_WAKE_UP", "achieved": 1, "unlocktime": 1791288000, "name": "Wake up call"},
            {"apiname": "ACH_LASER", "achieved": 0, "unlocktime": 0, "name": "You monster"},
        ]

        def script(request: RecordedRequest) -> ScriptedResponse:
            if request.path == OWNED_GAMES_PATH:
                return _ok({"games": games})
            return ScriptedResponse(json={"playerstats": {"success": True, "achievements": achievements}})

        result = _driver().run("player_achievements", script)

        assert result.params("appid")[1:] == ["620"]
        assert [(row["app_id"], row["api_name"], row["achieved"], row["unlocked_at"]) for row in result.rows] == [
            (620, "ACH_WAKE_UP", True, datetime(2026, 10, 6, 12, 0, tzinfo=UTC)),
            (620, "ACH_LASER", False, None),
        ]

    @parameterized.expand(
        [
            (
                "player_achievements",
                "appid",
                "400",
                ScriptedResponse(
                    status=400, json={"playerstats": {"error": "Requested app has no stats", "success": False}}
                ),
                2,
            ),
            (
                "player_achievements",
                "appid",
                "400",
                ScriptedResponse(
                    status=403, json={"playerstats": {"error": "Profile is not public", "success": False}}
                ),
                2,
            ),
            ("friends", "steamid", GRACE, ScriptedResponse(status=401, body=b"<html>Unauthorized</html>"), 1),
            ("current_players", "appid", "400", ScriptedResponse(status=404, json={"response": {"result": 42}}), 1),
            ("global_achievement_percentages", "gameid", "400", ScriptedResponse(status=403, json={}), 1),
        ]
    )
    def test_a_game_or_player_steam_has_no_data_for_is_skipped(
        self, endpoint: str, param: str, empty_value: str, empty_response: ScriptedResponse, expected_rows: int
    ) -> None:
        games = [{**PORTAL, "appid": 400}, PORTAL]
        data = {
            "player_achievements": {
                "playerstats": {"success": True, "achievements": [{"apiname": "A", "achieved": 1}]}
            },
            "friends": {"friendslist": {"friends": [{"steamid": GRACE, "relationship": "friend", "friend_since": 0}]}},
            "current_players": {"response": {"player_count": 5, "result": 1}},
            "global_achievement_percentages": {
                "achievementpercentages": {"achievements": [{"name": "A", "percent": "1"}]}
            },
        }

        def script(request: RecordedRequest) -> ScriptedResponse:
            if request.path == OWNED_GAMES_PATH:
                return _ok({"games": games})
            if request.param(param) == empty_value:
                return empty_response
            return ScriptedResponse(json=data[endpoint])

        result = _driver(steam_ids=f"{GRACE},{ADA}").run(endpoint, script)

        assert result.raised is None
        assert len(result.rows) == expected_rows

    def test_friends_are_keyed_like_players_so_listed_friends_join(self) -> None:
        friends = [{"steamid": GRACE, "relationship": "friend", "friend_since": 1791288000}]

        result = _driver().run("friends", [ScriptedResponse(json={"friendslist": {"friends": friends}})])

        assert result.rows == [
            {
                "player_key": player_key(TEAM_ID, ADA),
                "friend_key": player_key(TEAM_ID, GRACE),
                "relationship": "friend",
                "friend_since": datetime(2026, 10, 6, 12, 0, tzinfo=UTC),
            }
        ]
        assert GRACE not in str(result.rows)

    @parameterized.expand(
        [
            (
                "current_players",
                "appid",
                {"response": {"player_count": 12, "result": 1}},
                {"app_id": 620, "player_count": 12, "captured_at": datetime(2026, 10, 7, 23, 30, tzinfo=UTC)},
            ),
            (
                "global_achievement_percentages",
                "gameid",
                {"achievementpercentages": {"achievements": [{"name": "ACH_LASER", "percent": "49.5"}]}},
                {"app_id": 620, "api_name": "ACH_LASER", "percent": 49.5},
            ),
        ]
    )
    def test_app_tables_read_each_owned_game_once_without_the_key(
        self, endpoint: str, param: str, body: dict[str, Any], first_row: dict[str, Any]
    ) -> None:
        def script(request: RecordedRequest) -> ScriptedResponse:
            if request.path == OWNED_GAMES_PATH:
                return _ok({"games": [PORTAL, {"appid": 10, "playtime_forever": 900}]})
            return ScriptedResponse(json=body)

        with time_machine.travel("2026-10-07T23:30:00Z", tick=False):
            result = _driver(steam_ids=f"{GRACE},{ADA}").run(endpoint, script)

        app_requests = [request for request in result.requests if request.path != OWNED_GAMES_PATH]
        expected_ids = ["620", "10"] if endpoint == "current_players" else ["620"]
        assert [request.param(param) for request in app_requests] == expected_ids
        assert all(request.param("key") is None for request in app_requests)
        assert result.rows[0] == first_row

    @parameterized.expand(
        [
            (200, ADA, True, None),
            (403, ADA, False, "rejected"),
            (-1, ADA, False, "reach Steam"),
            (200, "gabe", False, "17-digit"),
        ]
    )
    def test_credentials_check_reports_what_to_fix(
        self, status: int, steam_ids: str, valid: bool, message: str | None
    ) -> None:
        with patch("products.warehouse_sources.sources.steam.source.probe_api_key") as probe:
            probe.return_value = status
            result = SteamSource().validate_credentials(SteamSourceConfig(api_key="key", steam_ids=steam_ids), 1)

        assert result[0] is valid
        assert message is None or message in (result[1] or "")
