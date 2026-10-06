import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.spotify.spotify import (
    ALL_ACCOUNTS_UNREADABLE,
    SpotifyAccount,
    SpotifyPlaysCursor,
    recently_played_source,
)

SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.spotify.spotify.make_tracked_session"

ADA = SpotifyAccount(account_id="ada", access_token="ada-token")
GRACE = SpotifyAccount(account_id="grace", access_token="grace-token")


def _play(played_at: str, **overrides: Any) -> dict[str, Any]:
    return {
        "played_at": played_at,
        "track": {
            "id": "track-1",
            "name": "Song",
            "duration_ms": 180000,
            "explicit": False,
            "artists": [{"id": "artist-1", "name": "Artist"}, {"id": "artist-2", "name": "Guest"}],
            "album": {"id": "album-1", "name": "Album"},
        },
        "context": {"type": "playlist", "uri": "spotify:playlist:1"},
        **overrides,
    }


def _response(status_code: int, items: list[dict[str, Any]] | None = None) -> Response:
    response = Response()
    response.status_code = status_code
    response._content = json.dumps({"items": items or []}).encode()
    return response


def _session(responses_by_token: dict[str, Response]) -> MagicMock:
    session = MagicMock()
    session.get.side_effect = lambda url, **kwargs: responses_by_token[
        kwargs["headers"]["Authorization"].removeprefix("Bearer ")
    ]
    return session


def _run(
    accounts: list[SpotifyAccount], session: MagicMock, cursor: SpotifyPlaysCursor | None = None
) -> tuple[list[dict[str, Any]], list[SpotifyPlaysCursor]]:
    staged: list[SpotifyPlaysCursor] = []
    with patch(SESSION_PATCH, return_value=session):
        response = recently_played_source(accounts, cursor, staged.append, MagicMock())
        rows = [row for batch in cast(Iterable[list[dict[str, Any]]], response.items()) for row in batch]
        assert response.on_complete is not None
        response.on_complete()
    return rows, staged


class TestRecentlyPlayedSource:
    @parameterized.expand([(401,), (403,)])
    def test_an_account_spotify_refuses_does_not_block_the_others(self, refused_status: int) -> None:
        session = _session(
            {
                "ada-token": _response(200, [_play("2026-10-06T12:00:02.500Z"), _play("2026-10-06T12:00:01.000Z")]),
                "grace-token": _response(refused_status),
            }
        )

        rows, staged = _run([ADA, GRACE], session)

        assert [(row["account_id"], row["played_at"]) for row in rows] == [
            ("ada", datetime(2026, 10, 6, 12, 0, 2, 500000, tzinfo=UTC)),
            ("ada", datetime(2026, 10, 6, 12, 0, 1, tzinfo=UTC)),
        ]
        assert staged == [SpotifyPlaysCursor(newest_played_at_ms={"ada": 1791288002500})]

    def test_every_account_refused_fails_the_sync(self) -> None:
        session = _session({"ada-token": _response(401), "grace-token": _response(403)})

        with pytest.raises(ValueError, match=ALL_ACCOUNTS_UNREADABLE):
            _run([ADA, GRACE], session)

    def test_no_connected_accounts_syncs_nothing(self) -> None:
        rows, staged = _run([], MagicMock())

        assert rows == []
        assert staged == []

    def test_a_server_error_fails_the_sync_instead_of_skipping_the_account(self) -> None:
        session = _session({"ada-token": _response(500)})

        with pytest.raises(HTTPError):
            _run([ADA], session)

    def test_each_account_resumes_from_its_own_position(self) -> None:
        session = _session({"ada-token": _response(200), "grace-token": _response(200)})

        _run([ADA, GRACE], session, cursor=SpotifyPlaysCursor(newest_played_at_ms={"ada": 1791288002500}))

        params_by_token = {
            call.kwargs["headers"]["Authorization"].removeprefix("Bearer "): call.kwargs["params"]
            for call in session.get.call_args_list
        }
        assert params_by_token == {
            "ada-token": {"limit": 50, "after": 1791288002500},
            # Grace connected after the last sync, so she has no position and gets her full window.
            "grace-token": {"limit": 50},
        }

    def test_a_play_without_context_or_track_details_still_produces_a_row(self) -> None:
        local_file = _play("2026-10-06T12:00:00.000Z", context=None, track={"id": None, "name": "Local file"})
        session = _session({"ada-token": _response(200, [local_file])})

        rows, _ = _run([ADA], session)

        assert rows[0] | {"track": None} == {
            "account_id": "ada",
            "played_at": datetime(2026, 10, 6, 12, 0, tzinfo=UTC),
            "track_id": None,
            "track_name": "Local file",
            "primary_artist_id": None,
            "primary_artist_name": None,
            "album_id": None,
            "album_name": None,
            "duration_ms": None,
            "explicit": None,
            "context_type": None,
            "context_uri": None,
            "track": None,
        }
