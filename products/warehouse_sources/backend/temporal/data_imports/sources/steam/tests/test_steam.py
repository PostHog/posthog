from datetime import date
from typing import Any

import pytest
import time_machine
from unittest.mock import patch

from parameterized import parameterized
from requests import (
    ConnectionError as RequestsConnectionError,
    HTTPError,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.steam import SteamSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.steam.source import SteamSource
from products.warehouse_sources.backend.temporal.data_imports.sources.steam.steam import parse_steam_ids, player_key

ADA = "76561197960287930"
GRACE = "76561197960435530"
TEAM_ID = 1


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

    def test_a_rejected_key_fails_the_sync_without_the_key_in_the_error(self) -> None:
        result = _driver().run("players", [ScriptedResponse(status=403, json={"response": {}})])

        assert isinstance(result.raised, HTTPError)
        assert str(result.raised) == "403 Client Error: Forbidden"

    def test_a_connection_failure_keeps_the_key_out_of_the_error(self) -> None:
        result = _driver(api_key="secret-key").run(
            "players",
            always(RequestsConnectionError("Max retries exceeded with url: /?key=secret-key&steamids=1")),
        )

        assert isinstance(result.raised, RequestsConnectionError)
        assert "secret-key" not in str(result.raised)

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
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.steam.source.probe_api_key"
        ) as probe:
            probe.return_value = status
            result = SteamSource().validate_credentials(SteamSourceConfig(api_key="key", steam_ids=steam_ids), 1)

        assert result[0] is valid
        assert message is None or message in (result[1] or "")
