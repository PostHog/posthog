import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from zoneinfo import ZoneInfo

from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.error_tracking.backend.facade.contracts import ErrorTrackingIssueBasics, NewIssueActivity
from products.today.backend.logic.highlight_registry import load_sources
from products.today.backend.logic.highlight_sources import errors
from products.today.backend.logic.highlight_types import Context

NAME = "TypeError: Cannot read properties of undefined"
ISSUE_ID = uuid.UUID("01890000-0000-7000-8000-000000000001")
WEEKLY_EXCEPTIONS = 10_000
CACHED_ACTIVE_USERS = 20_000


def new_issue(client_share: float, users: int, occurrences: int) -> NewIssueActivity:
    return NewIssueActivity(
        id=ISSUE_ID,
        name="TypeError",
        description="Cannot read properties of undefined",
        first_seen=datetime(2026, 10, 9, 15, tzinfo=UTC),
        users=users,
        occurrences=occurrences,
        client_share=client_share,
    )


def basics(name: str) -> ErrorTrackingIssueBasics:
    return ErrorTrackingIssueBasics(id=ISSUE_ID, name=name, description=None, status="active", severity=None)


def guard(_name: str, provider: Callable[[], Any], default: Any) -> Any:
    try:
        return provider()
    except TimeoutError:
        return default


class TestErrors(SimpleTestCase):
    def _find(
        self,
        new: list[NewIssueActivity],
        quiet: list[ErrorTrackingIssueBasics] | Exception,
        *,
        relevant: bool = True,
        active_users: int | Exception = CACHED_ACTIVE_USERS,
        exceptions: int | Exception = WEEKLY_EXCEPTIONS,
    ) -> list[tuple[str, str, str | None]]:
        context = cast(
            Context,
            SimpleNamespace(
                team=SimpleNamespace(id=1, timezone_info=ZoneInfo("UTC")),
                user=SimpleNamespace(id=2),
                daily=Mock(
                    side_effect=active_users if isinstance(active_users, Exception) else None, return_value=active_users
                ),
                guard=guard,
            ),
        )
        registered = next(s for s in load_sources() if s.name == "errors")
        with (
            patch.object(errors, "list_new_unassigned_issue_activity", return_value=new),
            patch.object(
                errors,
                "count_weekly_exceptions",
                side_effect=exceptions if isinstance(exceptions, Exception) else None,
                return_value=exceptions,
            ),
            patch.object(
                errors,
                "list_quiet_issues_assigned_to",
                side_effect=quiet if isinstance(quiet, Exception) else None,
                return_value=quiet,
            ),
            patch.object(errors, "uses_product", return_value=relevant),
        ):
            return [(c.title, c.detail, c.url) for c in registered.find(context).items]

    @parameterized.expand(
        [
            (
                "client error seen by enough people",
                new_issue(1.0, 60, 90),
                True,
                (
                    "60 users saw the new error ‘TypeError: Cannot read properties of undefined’",
                    "Since Oct 9 · 0.3% of active users · No owner",
                ),
            ),
            ("client error seen by too few people", new_issue(1.0, 49, 90), True, None),
            ("client error for someone who does not use error tracking", new_issue(1.0, 60, 90), False, None),
            (
                "client error so wide it shows to everyone",
                new_issue(1.0, 1_000, 2_000),
                False,
                (
                    "1.0k users saw the new error ‘TypeError: Cannot read properties of undefined’",
                    "Since Oct 9 · 5.0% of active users · No owner",
                ),
            ),
            (
                "server error with a large share",
                new_issue(0.0, 3, 500),
                True,
                (
                    "New server error ‘TypeError: Cannot read properties of undefined’ is 5% of all errors",
                    "Since Oct 9 · 500 events in the last 7 days · No owner",
                ),
            ),
            ("server error with a small share", new_issue(0.0, 3, 199), True, None),
            (
                "server error so large it shows to everyone",
                new_issue(0.0, 3, 6_000),
                False,
                (
                    "New server error ‘TypeError: Cannot read properties of undefined’ is 60% of all errors",
                    "Since Oct 9 · 6.0k events in the last 7 days · No owner",
                ),
            ),
            ("mixed client and server error", new_issue(0.5, 60, 500), True, None),
        ]
    )
    def test_a_new_unowned_error_shows_when_it_reaches_enough_people_or_errors(
        self, _name: str, issue: NewIssueActivity, relevant: bool, expected: tuple[str, str] | None
    ) -> None:
        found = self._find([issue], [], relevant=relevant)

        self.assertEqual(found, [(*expected, f"/error_tracking/{ISSUE_ID}")] if expected else [])

    @parameterized.expand(
        [
            (
                "one issue",
                ["ChunkLoadError"],
                (
                    "Your issue ‘ChunkLoadError’ had no events in the last 14 days",
                    "Resolve it if the fix is live",
                    f"/error_tracking/{ISSUE_ID}",
                ),
            ),
            (
                "many issues",
                ["ChunkLoadError", "TimeoutError", "KeyError"],
                (
                    "3 of your issues had no events in the last 14 days",
                    "‘ChunkLoadError’ and 2 more",
                    "/error_tracking?assignee=%7B%22id%22%3A+2%2C+%22type%22%3A+%22user%22%7D&status=active"
                    "&dateRange=%7B%22date_from%22%3A+%22all%22%7D",
                ),
            ),
        ]
    )
    def test_quiet_assigned_issues_become_one_item(
        self, _name: str, names: list[str], expected: tuple[str, str, str]
    ) -> None:
        self.assertEqual(self._find([], [basics(name) for name in names]), [expected])

    def test_a_strong_error_behind_weaker_ones_still_shows(self) -> None:
        ineligible = [new_issue(0.5, 60, 900) for _ in range(5)]
        weaker = [new_issue(1.0, 60, 90) for _ in range(5)]

        found = self._find([*ineligible, *weaker, new_issue(1.0, 1_000, 2_000)], [])

        self.assertEqual(
            [title for title, _, _ in found],
            [*[f"60 users saw the new error ‘{NAME}’"] * 5, f"1.0k users saw the new error ‘{NAME}’"],
        )

    @parameterized.expand(
        [
            (
                "active user total fails",
                TimeoutError("active user query timed out"),
                WEEKLY_EXCEPTIONS,
                f"New server error ‘{NAME}’ is 5% of all errors",
            ),
            (
                "exception total fails",
                CACHED_ACTIVE_USERS,
                TimeoutError("exception total query timed out"),
                f"60 users saw the new error ‘{NAME}’",
            ),
        ]
    )
    def test_a_failed_total_hides_only_the_errors_that_need_it(
        self, _name: str, active_users: int | Exception, exceptions: int | Exception, expected: str
    ) -> None:
        found = self._find(
            [new_issue(1.0, 60, 90), new_issue(0.0, 3, 500)],
            [],
            active_users=active_users,
            exceptions=exceptions,
        )

        self.assertEqual([title for title, _, _ in found], [expected])

    def test_new_errors_survive_when_the_quiet_issue_query_fails(self) -> None:
        found = self._find([new_issue(1.0, 60, 90)], TimeoutError("quiet issue query timed out"))

        self.assertEqual([title for title, _, _ in found], [f"60 users saw the new error ‘{NAME}’"])
