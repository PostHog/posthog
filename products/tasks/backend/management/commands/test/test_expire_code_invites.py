from datetime import UTC, datetime
from io import StringIO

from freezegun import freeze_time
from unittest.mock import patch

from django.core.management import CommandError, call_command
from django.test import TestCase

from parameterized import parameterized

from posthog.models.user import User

from products.tasks.backend.models import CodeInvite

NOW = datetime(2026, 4, 1, 12, 0, tzinfo=UTC)
PAST_EXPIRY = datetime(2026, 1, 15, tzinfo=UTC)
FUTURE_EXPIRY = datetime(2026, 12, 31, tzinfo=UTC)


class TestExpireCodeInvites(TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.alice = User.objects.create_user(email="alice@example.com", first_name="Alice", password=None)
        self.bob = User.objects.create_user(email="bob@example.com", first_name="Bob", password=None)
        with freeze_time("2026-01-01"):
            CodeInvite.objects.create(code="A", created_by=self.alice, redemption_count=1, max_redemptions=0)
            CodeInvite.objects.create(code="EXPIRED", created_by=self.alice, expires_at=PAST_EXPIRY)
        with freeze_time("2026-02-01"):
            CodeInvite.objects.create(code="B", created_by=self.bob, expires_at=FUTURE_EXPIRY)
        with freeze_time("2026-03-01"):
            CodeInvite.objects.create(code="C", created_by=self.alice)

    def _call(self, *args: str) -> str:
        stdout = StringIO()
        with freeze_time(NOW):
            call_command("expire_code_invites", *args, stdout=stdout)
        return stdout.getvalue()

    def _expires_at_by_code(self) -> dict[str, datetime | None]:
        return dict(CodeInvite.objects.values_list("code", "expires_at"))

    @parameterized.expand(
        [
            ("all", ["--all"], {"A", "B", "C"}),
            ("created_before", ["--created-before", "2026-02-15"], {"A", "B"}),
            ("created_after", ["--created-after", "2026-01-15T00:00:00Z"], {"B", "C"}),
            ("date_range", ["--created-after", "2026-01-15", "--created-before", "2026-02-15"], {"B"}),
            ("code_case_insensitive", ["--code", "a", "c"], {"A", "C"}),
            ("created_by", ["--created-by", "Alice@example.com"], {"A", "C"}),
            ("unredeemed", ["--unredeemed"], {"B", "C"}),
            ("created_by_and_unredeemed", ["--created-by", "alice@example.com", "--unredeemed"], {"C"}),
        ]
    )
    def test_expires_only_matching_unexpired_invites(self, _name: str, args: list[str], expected: set[str]) -> None:
        output = self._call(*args, "--yes")

        expires_at = self._expires_at_by_code()
        assert {code for code in ("A", "B", "C") if expires_at[code] == NOW} == expected
        assert expires_at["EXPIRED"] == PAST_EXPIRY
        untouched = {"A", "B", "C"} - expected
        assert all(expires_at[code] in (None, FUTURE_EXPIRY) for code in untouched)
        assert f"Expired {len(expected)} invite(s)." in output

    def test_dry_run_changes_nothing(self) -> None:
        output = self._call("--all", "--dry-run")

        assert "Dry run: 3 invite(s) would be expired." in output
        assert self._expires_at_by_code() == {"A": None, "B": FUTURE_EXPIRY, "C": None, "EXPIRED": PAST_EXPIRY}

    @parameterized.expand(
        [
            ("no_filters", []),
            ("all_with_filter", ["--all", "--unredeemed"]),
            ("inverted_range", ["--created-after", "2026-03-01", "--created-before", "2026-01-01"]),
            ("bad_datetime", ["--created-before", "not-a-date"]),
            ("unknown_code", ["--code", "A", "NOPE"]),
            ("unknown_email", ["--created-by", "nobody@example.com"]),
        ]
    )
    def test_rejects_invalid_arguments(self, _name: str, args: list[str]) -> None:
        with self.assertRaises(CommandError):
            self._call(*args, "--yes")

        assert self._expires_at_by_code() == {"A": None, "B": FUTURE_EXPIRY, "C": None, "EXPIRED": PAST_EXPIRY}

    def test_leaves_invites_created_during_confirmation_alone(self) -> None:
        def confirm(_prompt: str) -> str:
            CodeInvite.objects.create(code="LATE", created_by=self.alice)
            return "yes"

        with patch("sys.stdin") as stdin, patch("builtins.input", side_effect=confirm):
            stdin.isatty.return_value = True
            output = self._call("--all")

        assert self._expires_at_by_code()["LATE"] is None
        assert "Expired 3 invite(s)." in output

    def test_refuses_without_yes_when_not_interactive(self) -> None:
        with patch("sys.stdin") as stdin, self.assertRaises(CommandError):
            stdin.isatty.return_value = False
            self._call("--all")

        assert self._expires_at_by_code()["A"] is None
