from datetime import datetime, timedelta

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events

from django.utils import timezone

from products.error_tracking.backend.facade.api import sync_issues_to_clickhouse
from products.error_tracking.backend.facade.testing import create_issue, create_issue_fingerprint
from products.web_analytics.backend.facade.rage_pages import (
    ErrorsBeforeRage,
    RagePage,
    find_errors_before_rage,
    find_top_rage_element,
    find_top_rage_page,
)


class TestRagePages(ClickhouseTestMixin, BaseTest):
    def _ago(self, hours: float) -> datetime:
        return timezone.now() - timedelta(hours=hours)

    def _rage_clicks(
        self, distinct_id: str, path: str, count: int, *, session_id: str = "", at: datetime | None = None
    ) -> None:
        start = at or self._ago(24)
        for i in range(count):
            _create_event(
                team=self.team,
                event="$rageclick",
                distinct_id=distinct_id,
                properties={"$pathname": path, "$session_id": session_id},
                elements_chain='button:text="Pay now"nth-child="0"nth-of-type="0"',
                timestamp=start + timedelta(seconds=i),
            )

    def test_the_top_page_needs_three_people_with_ten_rage_clicks_each_and_ignores_ids_in_the_path(self) -> None:
        for i, path in enumerate(["/checkout/123", "/checkout/456", "/checkout/789"]):
            _create_person(team=self.team, distinct_ids=[f"buyer-{i}"])
            self._rage_clicks(f"buyer-{i}", path, 10)
        _create_person(team=self.team, distinct_ids=["light"])
        self._rage_clicks("light", "/checkout/1", 9)
        for i in range(2):
            _create_person(team=self.team, distinct_ids=[f"home-{i}"])
            self._rage_clicks(f"home-{i}", "/home", 20)
        flush_persons_and_events()

        page = find_top_rage_page(self.team, self.user)

        self.assertEqual(
            (page, find_top_rage_element(self.team, self.user, "/checkout/…")),
            (RagePage(path="/checkout/…", people=3, clicks=30), "Pay now"),
        )

    def _exception(self, distinct_id: str, session: str, fingerprint: str, at: datetime) -> None:
        _create_event(
            team=self.team,
            event="$exception",
            distinct_id=distinct_id,
            properties={"$session_id": session, "$exception_fingerprint": fingerprint},
            timestamp=at,
        )

    def _issue(self, name: str, fingerprint: str) -> str:
        issue_id = create_issue(team_id=self.team.id, name=name)
        create_issue_fingerprint(team_id=self.team.id, issue_id=issue_id, fingerprint=fingerprint)
        sync_issues_to_clickhouse(issue_ids=[issue_id], team_id=self.team.pk)
        return str(issue_id)

    def test_errors_before_rage_count_each_issue_once_per_session_of_the_qualifying_people(self) -> None:
        shared = self._issue("TypeError", "fp-shared")
        self._issue("KeyError", "fp-other")
        first_click = self._ago(24)
        sessions = [
            ("buyer-1", "s1", 10, [("fp-shared", 20), ("fp-other", 5)]),
            ("buyer-2", "s2", 10, [("fp-shared", 20)]),
            ("buyer-3", "s3", 10, [("fp-shared", 60)]),
            ("buyer-4", "s4a", 5, [("fp-shared", 10)]),
            ("buyer-4", "s4b", 5, []),
            ("browser", "s5", 9, [("fp-shared", 10)]),
        ]
        for distinct_id in {distinct_id for distinct_id, *_ in sessions}:
            _create_person(team=self.team, distinct_ids=[distinct_id])
        for distinct_id, session, clicks, exceptions in sessions:
            for fingerprint, seconds_before in exceptions:
                self._exception(distinct_id, session, fingerprint, first_click - timedelta(seconds=seconds_before))
            self._rage_clicks(distinct_id, "/checkout", clicks, session_id=session, at=first_click)
        flush_persons_and_events()

        errors = find_errors_before_rage(self.team, self.user, "/checkout")

        self.assertEqual(errors, ErrorsBeforeRage(sessions=5, issue_id=shared, issue_sessions=3))
