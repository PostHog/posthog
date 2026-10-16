from datetime import datetime, timedelta
from typing import Any

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from django.utils import timezone

from posthog.models import Team
from posthog.models.utils import uuid7

from products.error_tracking.backend.logic.recommendations.known_patterns import (
    KnownPatternsRecommendation,
    issue_patterns,
    noise_issue_ids,
)
from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueFingerprintV2,
    sync_issues_to_clickhouse,
)


def _frame(source: str, in_app: bool) -> dict[str, Any]:
    return {"source": source, "in_app": in_app, "resolved": in_app}


class TestKnownPatternsLens(ClickhouseTestMixin, BaseTest):
    def _create_issue(
        self,
        name: str,
        team: Team | None = None,
        fingerprint: str | None = None,
        description: str | None = None,
    ) -> ErrorTrackingIssue:
        team = team or self.team
        issue = ErrorTrackingIssue.objects.create(
            id=uuid7(), team=team, status=ErrorTrackingIssue.Status.ACTIVE, name=name, description=description
        )
        ErrorTrackingIssueFingerprintV2.objects.create(
            team=team, issue=issue, fingerprint=fingerprint or f"fp::{issue.id}"
        )
        sync_issues_to_clickhouse(issue_ids=[issue.id], team_id=team.pk)
        return issue

    def _create_exceptions(
        self,
        issue: ErrorTrackingIssue,
        count: int,
        exc_type: str,
        value: str,
        frames: list[dict[str, Any]],
        lib: str = "web",
        handled: bool = False,
        at: datetime | None = None,
    ) -> None:
        recent = at or timezone.now() - timedelta(hours=2)
        fingerprint = ErrorTrackingIssueFingerprintV2.objects.get(issue=issue).fingerprint
        for _ in range(count):
            session_id = str(uuid7())
            _create_event(
                distinct_id=session_id,
                event="$exception",
                team=issue.team,
                properties={
                    "$session_id": session_id,
                    "$host": "app.example.com",
                    "$lib": lib,
                    "$exception_fingerprint": fingerprint,
                    "$exception_types": [exc_type],
                    "$exception_values": [value],
                    "$exception_list": [
                        {
                            "type": exc_type,
                            "value": value,
                            "mechanism": {"handled": handled, "type": "generic"},
                            "stacktrace": {"type": "resolved", "frames": frames},
                        }
                    ],
                },
                timestamp=recent.isoformat(),
            )

    def test_flags_issues_that_are_likely_noise(self) -> None:
        app_frame = _frame("https://app.example.com/static/app.js", in_app=True)
        resize = self._create_issue("ResizeLoop")
        vendor = self._create_issue("VendorBug")
        app_bug = self._create_issue("AppBug")
        self._create_exceptions(
            resize, 30, "Error", "ResizeObserver loop completed with undelivered notifications.", []
        )
        self._create_exceptions(
            vendor,
            25,
            "TypeError",
            "u.init is not a function",
            [app_frame, _frame("https://widgets.example.org/embed.js", in_app=False)],
        )
        # Caught and reported by the app, a code bug still names code, so it is not an expected failure.
        self._create_exceptions(
            app_bug, 20, "TypeError", "Cannot read properties of undefined (reading 'id')", [app_frame], handled=True
        )
        app_reported = self._create_issue("NoAccess")
        self._create_exceptions(
            app_reported, 22, "Error", "You do not have access to this project.", [app_frame], handled=True
        )
        dependency = self._create_issue("DependencyBug")
        self._create_exceptions(
            dependency,
            21,
            "TypeError",
            "t.render is not a function",
            [_frame("https://app.example.com/static/vendor.js", in_app=False)],
        )
        # The app's own bundle served from a CDN, resolved through its source maps, is first-party code.
        cdn_bundle = self._create_issue("CdnBundle")
        self._create_exceptions(
            cdn_bundle,
            20,
            "TypeError",
            "Cannot read properties of null (reading 'items')",
            [_frame("https://cdn.example-static.net/app.js", in_app=True)],
        )
        # Backend errors follow other conventions, so the lens leaves them out.
        backend = self._create_issue("BackendAbort")
        self._create_exceptions(
            backend, 20, "InFailedSqlTransaction", "current transaction is aborted", [], lib="posthog-python"
        )
        flush_persons_and_events()

        meta = KnownPatternsRecommendation().compute(self.team)

        self.assertEqual(
            [(issue["name"], issue["pattern"], issue["reasons"]) for issue in meta["issues"]],
            [
                ("ResizeLoop", "resize_observer", ["known_pattern", "no_own_code"]),
                ("VendorBug", "code_bug", ["third_party"]),
                ("NoAccess", "other", ["app_reported"]),
                ("DependencyBug", "code_bug", ["no_own_code"]),
            ],
        )
        self.assertEqual((meta["total_events"], meta["pattern_events"]), (138, 30))
        self.assertEqual(
            meta["classes"],
            [
                {"pattern": "code_bug", "events": 86},
                {"pattern": "resize_observer", "events": 30},
                {"pattern": "other", "events": 22},
            ],
        )

    def test_classifies_environment_noise_that_message_words_used_to_mislabel(self) -> None:
        messages = {
            "Error: Translation file not found": "other",
            "Error: Object Not Found Matching Id:2, MethodName:update, ParamCount:4": "environment",
            "Error: Java object is gone": "environment",
            "TypeError: Cannot redefine property: ethereum": "extension",
            "Error: Non-Error promise rejection captured with value: CustomEvent": "non_error_rejection",
            "AxiosError: Request failed with status code 404": "http_status",
            # A noise word inside a code bug's message does not make it noise.
            "TypeError: Cannot read properties of null (reading 'clearTimeout')": "code_bug",
            "TypeError: Cannot read properties of null (reading 'isCancelled')": "code_bug",
            "Error: Failed to rehydrate the store": "other",
            "AbortError: The user aborted a request.": "abort",
            "TimeoutError: signal timed out": "network",
        }
        issues = {}
        for message in messages:
            exc_type, value = message.split(": ", 1)
            issue = self._create_issue(exc_type)
            self._create_exceptions(issue, 1, exc_type, value, [])
            issues[str(issue.id)] = message
        flush_persons_and_events()

        patterns = issue_patterns(
            [self.team.pk], list(issues), timezone.now() - timedelta(days=1), timezone.now() + timedelta(minutes=1)
        )

        self.assertEqual({issues[issue_id]: pattern for issue_id, pattern in patterns.items()}, messages)

    def test_judges_issues_quiet_in_the_last_day_on_earlier_events_then_on_their_stored_message(self) -> None:
        three_days_ago = timezone.now() - timedelta(days=3)
        dependency = self._create_issue("DependencyBug")
        self._create_exceptions(
            dependency,
            5,
            "TypeError",
            "t.render is not a function",
            [_frame("https://app.example.com/static/vendor.js", in_app=False)],
            at=three_days_ago,
        )
        app_bug = self._create_issue("AppBug")
        self._create_exceptions(
            app_bug,
            5,
            "TypeError",
            "t.render is not a function",
            [_frame("https://app.example.com/static/app.js", in_app=True)],
            at=three_days_ago,
        )
        # Without events in the last week, only the stored type and message from the first event are left.
        stale_request = self._create_issue("TypeError", description="Failed to fetch")
        stale_bug = self._create_issue("TypeError", description="Cannot read properties of undefined (reading 'id')")
        # A quoted name and a brand name are not code, so this is still a plain sentence.
        stale_api_failure = self._create_issue("Error", description="No GitHub integration can access 'example/repo'.")
        flush_persons_and_events()
        issues = [dependency, app_bug, stale_request, stale_bug, stale_api_failure]

        noise = noise_issue_ids(
            [self.team.pk],
            {self.team.pk: {str(issue.id) for issue in issues}},
            timezone.now() - timedelta(days=30),
        )

        self.assertEqual(noise[self.team.pk], {str(dependency.id), str(stale_request.id), str(stale_api_failure.id)})

    def test_a_batch_of_teams_gives_each_team_its_own_result(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        # Both teams use the same fingerprint, so a lookup that ignored the team would give one team the other's issue.
        resize = self._create_issue("ResizeLoop", fingerprint="fp::shared")
        app_bug = self._create_issue("AppBug", team=other_team, fingerprint="fp::shared")
        self._create_exceptions(
            resize, 30, "Error", "ResizeObserver loop completed with undelivered notifications.", []
        )
        self._create_exceptions(app_bug, 25, "TypeError", "Cannot read properties of undefined (reading 'id')", [])
        flush_persons_and_events()

        lens = KnownPatternsRecommendation()
        batch = lens.compute_batch([self.team.pk, other_team.pk])

        self.assertEqual([issue["name"] for issue in batch[self.team.pk]["issues"]], ["ResizeLoop"])
        self.assertEqual(batch, {self.team.pk: lens.compute(self.team), other_team.pk: lens.compute(other_team)})
