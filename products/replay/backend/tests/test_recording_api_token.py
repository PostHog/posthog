import json
import tempfile
from io import StringIO
from pathlib import Path

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import CommandError, call_command
from django.test import override_settings

import jwt
from parameterized import parameterized

STAFF_SECRET = "s" * 32


@override_settings(RECORDING_API_STAFF_JWT_SECRET=STAFF_SECRET, RECORDING_API_URL="http://recording-api:6738/")
class TestRecordingApiTokenCommand(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        labels_dir = tempfile.TemporaryDirectory()
        self.addCleanup(labels_dir.cleanup)
        self.labels = Path(labels_dir.name) / "labels"
        self.labels.write_text(
            'app.kubernetes.io/name="posthog-toolbox-django"\ntoolbox-claimed="staff_at_example.com"\n'
        )
        labels_path = patch(
            "products.replay.backend.management.commands.recording_api_token.POD_LABELS_PATH", self.labels
        )
        labels_path.start()
        self.addCleanup(labels_path.stop)

    def test_mints_a_read_token_for_the_team_signed_with_the_staff_key(self) -> None:
        out = StringIO()
        call_command(
            "recording_api_token",
            "--team-id",
            str(self.team.pk),
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
        assert claims["actor"] == "staff_at_example.com"
        assert claims["reason"] == "ticket 1"
        assert 15 * 60 <= claims["exp"] - claims["iat"] <= 15 * 60 + 1
        assert printed["url"] == "http://recording-api:6738"

    @parameterized.expand(
        [
            ("unknown_team", {"team_id": 999_999_999}, {}, "No team has ID"),
            ("blank_reason", {"reason": "  "}, {}, "must not be empty"),
            ("no_staff_key", {}, {"RECORDING_API_STAFF_JWT_SECRET": ""}, "RECORDING_API_STAFF_JWT_SECRET is not set"),
            ("short_staff_key", {}, {"RECORDING_API_STAFF_JWT_SECRET": "s" * 31}, "at least 32 bytes"),
        ]
    )
    def test_refuses_to_mint(self, _name: str, args: dict[str, object], settings: dict[str, str], error: str) -> None:
        options = {"team_id": self.team.pk, "reason": "ticket 1", **args}
        with override_settings(**settings), self.assertRaisesMessage(CommandError, error):
            call_command("recording_api_token", **options, stdout=StringIO(), stderr=StringIO())

    @parameterized.expand(
        [
            ("unclaimed_pod", 'app.kubernetes.io/name="posthog-toolbox-django"\n'),
            ("no_labels_file", None),
        ]
    )
    def test_refuses_to_mint_without_a_claim(self, _name: str, labels: str | None) -> None:
        if labels is None:
            self.labels.unlink()
        else:
            self.labels.write_text(labels)
        with self.assertRaisesMessage(CommandError, "no toolbox claim"):
            call_command(
                "recording_api_token", team_id=self.team.pk, reason="ticket 1", stdout=StringIO(), stderr=StringIO()
            )
