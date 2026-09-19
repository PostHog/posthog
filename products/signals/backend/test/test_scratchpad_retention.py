from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import OperationalError, ProgrammingError
from django.test import SimpleTestCase
from django.utils import timezone

import psycopg.errors
from parameterized import parameterized

from posthog.models.scoping import team_scope

from products.signals.backend.models import SignalScratchpad
from products.signals.backend.tasks import (
    SCRATCHPAD_EXPIRY_GRACE_DAYS,
    prune_expired_scratchpad_entries,
    prune_expired_scratchpad_entries_task,
)

TASKS_MODULE = "products.signals.backend.tasks"


class TestPruneExpiredScratchpadEntries(BaseTest):
    def test_prunes_only_entries_whose_expiry_is_past_the_grace(self) -> None:
        now = timezone.now()
        grace = timedelta(days=SCRATCHPAD_EXPIRY_GRACE_DAYS)
        with team_scope(self.team.id):
            SignalScratchpad.objects.create(team=self.team, key="durable", content="x", expires_at=None)
            SignalScratchpad.objects.create(team=self.team, key="live", content="x", expires_at=now + timedelta(days=1))
            SignalScratchpad.objects.create(
                team=self.team, key="within_grace", content="x", expires_at=now - timedelta(days=1)
            )
            SignalScratchpad.objects.create(
                team=self.team, key="past_grace", content="x", expires_at=now - grace - timedelta(days=1)
            )

        deleted = prune_expired_scratchpad_entries()

        assert deleted == 1
        survivors = set(SignalScratchpad.objects.unscoped().values_list("key", flat=True))
        assert survivors == {"durable", "live", "within_grace"}


def programming_error_from(cause: BaseException) -> ProgrammingError:
    error = ProgrammingError(str(cause))
    error.__cause__ = cause
    return error


class TestPruneExpiredScratchpadEntriesTask(SimpleTestCase):
    @parameterized.expand(
        [
            ("missing_table", programming_error_from(psycopg.errors.UndefinedTable("missing table"))),
            ("missing_column", programming_error_from(psycopg.errors.UndefinedColumn("missing column"))),
            ("transient_database_failure", OperationalError("connection unavailable")),
        ]
    )
    def test_expected_database_errors_are_not_reported(
        self, _name: str, database_error: ProgrammingError | OperationalError
    ) -> None:
        with (
            patch(f"{TASKS_MODULE}.prune_expired_scratchpad_entries", side_effect=database_error),
            patch(f"{TASKS_MODULE}.capture_exception") as mock_capture,
        ):
            prune_expired_scratchpad_entries_task()

        mock_capture.assert_not_called()

    def test_unexpected_programming_errors_are_reported(self) -> None:
        database_error = programming_error_from(psycopg.errors.SyntaxError("invalid query"))
        with (
            patch(f"{TASKS_MODULE}.prune_expired_scratchpad_entries", side_effect=database_error),
            patch(f"{TASKS_MODULE}.capture_exception") as mock_capture,
        ):
            prune_expired_scratchpad_entries_task()

        mock_capture.assert_called_once_with(database_error)
