import json
from collections.abc import Iterable
from datetime import date
from typing import Any, cast

import pytest
import time_machine
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.steam import SteamSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.steam.source import SteamSource
from products.warehouse_sources.backend.temporal.data_imports.sources.steam.steam import parse_steam_ids, steam_source

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.steam.steam"
ADA = "76561197960287930"
GRACE = "76561197960435530"


def _response(status_code: int, body: dict[str, Any] | None = None) -> Response:
    response = Response()
    response.status_code = status_code
    response.url = "https://api.steampowered.com/"
    response._content = json.dumps({"response": body or {}}).encode()
    return response


def _rows(endpoint: str, session: MagicMock, steam_ids: list[str]) -> list[dict[str, Any]]:
    with patch(f"{MODULE}.make_tracked_session", return_value=session):
        response = steam_source("key", steam_ids, endpoint, MagicMock())
        return [row for batch in cast(Iterable[list[dict[str, Any]]], response.items()) for row in batch]


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
        session = MagicMock()
        session.get.side_effect = lambda url, **kwargs: (
            _response(200) if kwargs["params"]["steamid"] == GRACE else _response(200, {"games": [game]})
        )

        rows = _rows("owned_games", session, [GRACE, ADA])

        assert [(row["steam_id"], row["app_id"], row["playtime_2weeks_minutes"]) for row in rows] == [(ADA, 620, 0)]

    def test_snapshots_are_keyed_by_the_day_they_were_read(self) -> None:
        game = {"appid": 620, "name": "Portal 2", "playtime_forever": 600, "playtime_2weeks": 90}
        session = MagicMock()
        session.get.return_value = _response(200, {"games": [game]})

        with time_machine.travel("2026-10-07T23:30:00Z", tick=False):
            rows = _rows("playtime_snapshots", session, [ADA])

        assert rows == [
            {
                "steam_id": ADA,
                "app_id": 620,
                "name": "Portal 2",
                "snapshot_date": date(2026, 10, 7),
                "playtime_forever_minutes": 600,
                "playtime_2weeks_minutes": 90,
            }
        ]

    def test_a_rejected_key_fails_the_sync_with_a_non_retryable_error(self) -> None:
        response = _response(403)
        response.reason = "Forbidden"
        response.url = "https://api.steampowered.com/?key=secret-key"
        session = MagicMock()
        session.get.return_value = response

        with pytest.raises(HTTPError) as error:
            _rows("players", session, [ADA])

        assert any(pattern in str(error.value) for pattern in SteamSource().get_non_retryable_errors())
        assert "secret-key" not in str(error.value)

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
