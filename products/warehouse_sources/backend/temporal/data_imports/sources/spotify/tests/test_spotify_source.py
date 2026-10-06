import json
import time
from collections.abc import Iterable
from typing import Any, cast

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from requests import Response

from posthog.models.integration import Integration

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.spotify import (
    SpotifySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.spotify.source import SpotifySource
from products.warehouse_sources.backend.temporal.data_imports.sources.spotify.spotify import (
    ALL_ACCOUNTS_UNREADABLE,
    SpotifyPlaysCursor,
)

SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.spotify.spotify.make_tracked_session"
TOKEN_POST_PATCH = "posthog.models.integration.oauth.requests.post"


def _no_plays() -> Response:
    response = Response()
    response.status_code = 200
    response._content = json.dumps({"items": []}).encode()
    return response


class TestSpotifyCursor:
    def test_merge_keeps_accounts_the_run_did_not_read_and_never_moves_back(self) -> None:
        stored = SpotifyPlaysCursor(newest_played_at_ms={"ada": 2000, "grace": 5000})
        staged = SpotifyPlaysCursor(newest_played_at_ms={"ada": 1000, "linus": 3000})

        merged = SpotifySource().merge_cursors(stored, staged)

        assert merged.newest_played_at_ms == {"ada": 2000, "grace": 5000, "linus": 3000}

    def test_an_instance_without_the_spotify_app_cannot_create_the_source(self) -> None:
        with override_settings(SPOTIFY_APP_CLIENT_ID="", SPOTIFY_APP_CLIENT_SECRET=""):
            valid, message = SpotifySource().validate_credentials(SpotifySourceConfig(), team_id=1)

        assert valid is False
        assert message == "Spotify is not set up on this PostHog instance."


@override_settings(SPOTIFY_APP_CLIENT_ID="spotify-client-id", SPOTIFY_APP_CLIENT_SECRET="spotify-client-secret")
class TestSpotifySource(BaseTest):
    def _connect(self, account_id: str, *, token_age_seconds: int = 0, display_name: str | None = None) -> Integration:
        return Integration.objects.create(
            team=self.team,
            kind="spotify",
            integration_id=account_id,
            config={
                "display_name": display_name,
                "expires_in": 3600,
                "refreshed_at": int(time.time()) - token_age_seconds,
            },
            sensitive_config={"access_token": f"{account_id}-token", "refresh_token": "REFRESH"},
            created_by=self.user,
        )

    def _inputs(self, schema_name: str) -> MagicMock:
        return MagicMock(team_id=self.team.id, schema_name=schema_name, should_use_incremental_field=True)

    def _refresh_rejected(self) -> MagicMock:
        return MagicMock(status_code=400, text="invalid_grant", json=lambda: {"error": "invalid_grant"})

    def test_an_account_whose_grant_expired_is_left_out_of_the_sync(self) -> None:
        self._connect("ada")
        self._connect("grace", token_age_seconds=7200)
        session = MagicMock()
        session.get.return_value = _no_plays()

        with patch(TOKEN_POST_PATCH, return_value=self._refresh_rejected()), patch(SESSION_PATCH, return_value=session):
            response = SpotifySource().source_for_pipeline(SpotifySourceConfig(), self._inputs("recently_played"))
            list(cast(Iterable[list[dict[str, Any]]], response.items()))

        assert [call.kwargs["headers"]["Authorization"] for call in session.get.call_args_list] == ["Bearer ada-token"]

    def test_the_sync_fails_when_no_connected_account_can_be_refreshed(self) -> None:
        self._connect("grace", token_age_seconds=7200)
        source = SpotifySource()

        with patch(TOKEN_POST_PATCH, return_value=self._refresh_rejected()):
            with pytest.raises(ValueError, match=ALL_ACCOUNTS_UNREADABLE) as error:
                source.source_for_pipeline(SpotifySourceConfig(), self._inputs("recently_played"))

        assert any(pattern in str(error.value) for pattern in source.get_non_retryable_errors())

    def test_accounts_table_names_who_connected_each_account(self) -> None:
        self._connect("ada", display_name="Ada L")
        self._connect("grace")
        other_team = self.organization.teams.create(name="Other project")
        Integration.objects.create(team=other_team, kind="spotify", integration_id="linus", created_by=self.user)

        response = SpotifySource().source_for_pipeline(SpotifySourceConfig(), self._inputs("accounts"))
        rows = [row for batch in cast(Iterable[list[dict[str, Any]]], response.items()) for row in batch]

        assert [(row["account_id"], row["display_name"], row["connected_by_email"]) for row in rows] == [
            ("ada", "Ada L", self.user.email),
            ("grace", "grace", self.user.email),
        ]
