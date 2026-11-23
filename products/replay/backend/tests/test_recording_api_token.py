import json
from io import StringIO

from posthog.test.base import BaseTest

from django.core.management import CommandError, call_command
from django.test import override_settings

import jwt
from parameterized import parameterized

STAFF_SECRET = "staff-secret"


@override_settings(RECORDING_API_STAFF_JWT_SECRET=STAFF_SECRET, RECORDING_API_URL="http://recording-api:6738/")
class TestRecordingApiTokenCommand(BaseTest):
    def test_mints_a_read_token_for_the_team_signed_with_the_staff_key(self) -> None:
        out = StringIO()
        call_command(
            "recording_api_token",
            "--team-id",
            str(self.team.pk),
            "--actor",
            "staff@example.com",
            "--reason",
            "ticket 1",
            stdout=out,
            stderr=StringIO(),
        )

        printed = json.loads(out.getvalue())
        claims = jwt.decode(
            printed["token"], STAFF_SECRET, algorithms=["HS256"], audience="posthog:recording_api:staff"
        )
        assert claims["team_id"] == self.team.pk
        assert claims["op"] == "read"
        assert claims["actor"] == "staff@example.com"
        assert claims["reason"] == "ticket 1"
        assert 15 * 60 <= claims["exp"] - claims["iat"] <= 15 * 60 + 1
        assert printed["url"] == "http://recording-api:6738"

    @parameterized.expand(
        [
            ("unknown_team", {"team_id": 999_999_999}, {}, "No team has ID"),
            ("blank_reason", {"reason": "  "}, {}, "must not be empty"),
            ("blank_actor", {"actor": ""}, {}, "must not be empty"),
            ("no_staff_key", {}, {"RECORDING_API_STAFF_JWT_SECRET": ""}, "RECORDING_API_STAFF_JWT_SECRET is not set"),
        ]
    )
    def test_refuses_to_mint(self, _name: str, args: dict[str, object], settings: dict[str, str], error: str) -> None:
        options = {"team_id": self.team.pk, "actor": "staff@example.com", "reason": "ticket 1", **args}
        with override_settings(**settings), self.assertRaisesMessage(CommandError, error):
            call_command("recording_api_token", **options, stdout=StringIO(), stderr=StringIO())
