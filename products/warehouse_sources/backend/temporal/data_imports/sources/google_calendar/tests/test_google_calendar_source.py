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

from products.warehouse_sources.backend.temporal.data_imports.sources.common.member_accounts import (
    ALL_ACCOUNTS_UNREADABLE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.googlecalendar import (
    GoogleCalendarSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_calendar.google_calendar import (
    GoogleCalendarCursor,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_calendar.source import GoogleCalendarSource

REQUEST_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.google_calendar.google_calendar"
    ".google_workspace_request"
)
TOKEN_POST_PATCH = "posthog.models.integration.oauth.requests.post"


def _no_events() -> Response:
    response = Response()
    response.status_code = 200
    response._content = json.dumps({"items": []}).encode()
    return response


class TestGoogleCalendarCursor:
    def test_merge_keeps_accounts_the_run_did_not_read_and_never_moves_back(self) -> None:
        stored = GoogleCalendarCursor(
            updated_at={"ada": "2026-10-05T08:00:00.000Z", "grace": "2026-10-06T08:00:00.000Z"},
            synced_until={"ada": "2026-10-07T06:00:00.000Z", "grace": "2026-10-07T06:00:00.000Z"},
        )
        staged = GoogleCalendarCursor(
            updated_at={"ada": "2026-10-01T08:00:00.000Z", "linus": "2026-10-07T09:00:00.000Z"},
            synced_until={"ada": "2026-10-07T12:00:00.000Z", "linus": "2026-10-07T12:00:00.000Z"},
        )

        merged = GoogleCalendarSource().merge_cursors(stored, staged)

        assert merged.updated_at == {
            "ada": "2026-10-05T08:00:00.000Z",
            "grace": "2026-10-06T08:00:00.000Z",
            "linus": "2026-10-07T09:00:00.000Z",
        }
        assert merged.synced_until["ada"] == "2026-10-07T12:00:00.000Z"
        assert merged.synced_until["grace"] == "2026-10-07T06:00:00.000Z"

    def test_an_instance_without_the_google_calendar_app_cannot_create_the_source(self) -> None:
        with override_settings(GOOGLE_CALENDAR_APP_CLIENT_ID="", GOOGLE_CALENDAR_APP_CLIENT_SECRET=""):
            valid, message = GoogleCalendarSource().validate_credentials(GoogleCalendarSourceConfig(), team_id=1)

        assert valid is False
        assert message == "Google Calendar is not set up on this PostHog instance."


@override_settings(GOOGLE_CALENDAR_APP_CLIENT_ID="client-id", GOOGLE_CALENDAR_APP_CLIENT_SECRET="client-secret")
class TestGoogleCalendarSource(BaseTest):
    def _connect(self, account_id: str, *, token_age_seconds: int = 0) -> Integration:
        return Integration.objects.create(
            team=self.team,
            kind="google-calendar",
            integration_id=account_id,
            config={
                "email": f"{account_id}@example.com",
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
        request = MagicMock(side_effect=lambda *args, **kwargs: _no_events())

        with patch(TOKEN_POST_PATCH, return_value=self._refresh_rejected()), patch(REQUEST_PATCH, request):
            inputs = self._inputs("events")
            inputs.source_cursor.load.return_value = None
            response = GoogleCalendarSource().source_for_pipeline(GoogleCalendarSourceConfig(), inputs)
            list(cast(Iterable[list[dict[str, Any]]], response.items()))

        assert {call.kwargs["access_token"] for call in request.call_args_list} == {"ada-token"}

    def test_the_sync_fails_when_no_connected_account_can_be_refreshed(self) -> None:
        self._connect("grace", token_age_seconds=7200)
        source = GoogleCalendarSource()

        with patch(TOKEN_POST_PATCH, return_value=self._refresh_rejected()):
            with pytest.raises(ValueError, match=ALL_ACCOUNTS_UNREADABLE):
                source.source_for_pipeline(GoogleCalendarSourceConfig(), self._inputs("events"))

    def test_accounts_table_names_who_connected_each_account(self) -> None:
        self._connect("ada")
        other_team = self.organization.teams.create(name="Other project")
        Integration.objects.create(team=other_team, kind="google-calendar", integration_id="linus")

        response = GoogleCalendarSource().source_for_pipeline(GoogleCalendarSourceConfig(), self._inputs("accounts"))
        rows = [row for batch in cast(Iterable[list[dict[str, Any]]], response.items()) for row in batch]

        assert [(row["account_id"], row["display_name"], row["connected_by_email"]) for row in rows] == [
            ("ada", "ada@example.com", self.user.email)
        ]
