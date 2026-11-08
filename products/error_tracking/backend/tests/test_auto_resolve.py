from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized
from prometheus_client import REGISTRY
from temporalio.testing import ActivityEnvironment

from posthog.models import Team
from posthog.models.activity_logging.activity_log import ActivityLog

from products.error_tracking.backend.logic import auto_resolve_sweep, issue_mutations
from products.error_tracking.backend.logic.auto_resolve_sweep import auto_resolve_team, auto_resolve_team_ids
from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueAssignment,
    ErrorTrackingIssueChange,
    ErrorTrackingSettings,
)
from products.error_tracking.backend.temporal.auto_resolve.activities import auto_resolve_teams_activity
from products.error_tracking.backend.temporal.auto_resolve.types import AutoResolveTeamsInputs
from products.error_tracking.backend.tests.auto_resolve_fixtures import create_issue_with_exceptions

AFTER_DAYS = 14
Status = ErrorTrackingIssue.Status
REASON = {"kind": "auto_resolve", "after_days": AFTER_DAYS}
COUNTER_SAMPLE = "error_tracking_issues_auto_resolved_total"


@patch("products.error_tracking.backend.logic.issue_changes.issue_change_log_enabled", return_value=True)
class TestAutoResolveTeam(ClickhouseTestMixin, BaseTest):
    def _enable(self, after_days: int | None = AFTER_DAYS) -> None:
        ErrorTrackingSettings.objects.update_or_create(team=self.team, defaults={"auto_resolve_after_days": after_days})

    @parameterized.expand(
        [
            ("quiet_active", {"exception_days_ago": [[20]]}, AFTER_DAYS, Status.RESOLVED, 1),
            (
                "changed_long_ago",
                {"exception_days_ago": [[20]], "state_updated_days_ago": 20},
                AFTER_DAYS,
                Status.RESOLVED,
                1,
            ),
            ("exceptions_past_retention", {"created_days_ago": 400}, AFTER_DAYS, Status.RESOLVED, 1),
            ("recent_exception", {"exception_days_ago": [[20, 2]]}, AFTER_DAYS, Status.ACTIVE, 0),
            (
                "recent_exception_on_merged_fingerprint",
                {"exception_days_ago": [[20], [2]]},
                AFTER_DAYS,
                Status.ACTIVE,
                0,
            ),
            ("suppressed", {"status": Status.SUPPRESSED}, AFTER_DAYS, Status.SUPPRESSED, 0),
            ("already_resolved", {"status": Status.RESOLVED}, AFTER_DAYS, Status.RESOLVED, 0),
            ("created_recently", {"created_days_ago": 5}, AFTER_DAYS, Status.ACTIVE, 0),
            ("setting_off", {"exception_days_ago": [[20]]}, None, Status.ACTIVE, None),
        ]
    )
    def test_resolves_only_quiet_active_issues(
        self, _flag, _name, issue_kwargs, after_days, expected_status, expected_resolved_count
    ) -> None:
        issue = create_issue_with_exceptions(self.team, **issue_kwargs)
        self._enable(after_days)

        run = auto_resolve_team(self.team.id)

        issue.refresh_from_db()
        assert issue.status == expected_status
        if after_days is None:
            assert run is None
        else:
            assert run is not None
            assert (run.after_days, run.resolved_count) == (after_days, expected_resolved_count)

    def test_keeps_a_reopened_issue_active_for_a_full_quiet_period(self, _flag) -> None:
        issue = create_issue_with_exceptions(self.team, status=Status.RESOLVED, exception_days_ago=[[20]])
        self._enable()
        issue_mutations.update_issue(
            self.team.id, issue.id, fields={"status": Status.ACTIVE}, user=self.user, was_impersonated=False
        )

        run = auto_resolve_team(self.team.id)

        issue.refresh_from_db()
        assert issue.status == Status.ACTIVE
        assert run is not None and run.resolved_count == 0

    def test_leaves_other_teams_issues_alone(self, _flag) -> None:
        other_team = Team.objects.create(organization=self.organization)
        other_issue = create_issue_with_exceptions(other_team, exception_days_ago=[[20]])
        self._enable()

        run = auto_resolve_team(self.team.id)

        other_issue.refresh_from_db()
        assert other_issue.status == Status.ACTIVE
        assert run is not None and run.resolved_count == 0

    @parameterized.expand(
        [
            ("suppressed", {"status": Status.SUPPRESSED}, Status.SUPPRESSED),
            ("edited_while_active", {"name": "Renamed", "state_updated_at": timezone.now()}, Status.ACTIVE),
        ]
    )
    def test_skips_an_issue_changed_after_the_candidate_query(self, _flag, _name, change, expected_status) -> None:
        issue = create_issue_with_exceptions(self.team, exception_days_ago=[[20]])
        self._enable()
        find_candidates = auto_resolve_sweep.find_auto_resolve_candidates

        def find_then_change(team, after_days):
            candidates = find_candidates(team, after_days)
            ErrorTrackingIssue.objects.filter(id=issue.id).update(**change)
            return candidates

        with patch.object(auto_resolve_sweep, "find_auto_resolve_candidates", side_effect=find_then_change):
            run = auto_resolve_team(self.team.id)

        issue.refresh_from_db()
        assert issue.status == expected_status
        assert run is not None and run.resolved_count == 0

    @parameterized.expand([("change_log_on", True), ("change_log_off", False)])
    def test_records_a_system_resolve_with_the_reason(self, change_log_flag, _name, change_log_enabled) -> None:
        change_log_flag.return_value = change_log_enabled
        issue = create_issue_with_exceptions(self.team, exception_days_ago=[[20]], assignee=self.user)
        self._enable()

        with (
            patch("products.error_tracking.backend.logic.lifecycle_events.produce_internal_event") as produce,
            self.captureOnCommitCallbacks(execute=True),
        ):
            auto_resolve_team(self.team.id)

        [entry] = ActivityLog.objects.filter(team_id=self.team.id, scope="ErrorTrackingIssue", item_id=str(issue.id))
        assert entry.user is None
        assert entry.detail is not None
        assert entry.detail["changes"][0]["after"] == Status.RESOLVED
        assert entry.detail["context"] == {"reason": REASON}
        [call] = produce.call_args_list
        assert (call.kwargs["event"].event, call.kwargs["person"]) == ("$error_tracking_issue_resolved", None)
        changes = list(ErrorTrackingIssueChange.objects.for_team(self.team.id))
        if change_log_enabled:
            [change] = changes
            assert (change.actor_type, change.actor_user_id, change.actor_automation_id, change.bulk) == (
                "system",
                None,
                None,
                True,
            )
            assert change.data == {"previous": Status.ACTIVE, "reason": REASON}
        else:
            assert changes == []
        assert ErrorTrackingIssueAssignment.objects.get(issue=issue).user_id == self.user.id

    def test_selects_teams_with_the_setting_the_flag_and_an_active_issue(self, _flag) -> None:
        def team_with(after_days: int | None, *, issue_status: str | None = Status.ACTIVE) -> int:
            team = Team.objects.create(organization=self.organization)
            ErrorTrackingSettings.objects.create(team=team, auto_resolve_after_days=after_days)
            if issue_status is not None:
                ErrorTrackingIssue.objects.create(team=team, status=issue_status)
            return team.id

        due = team_with(AFTER_DAYS)
        flag_off = team_with(AFTER_DAYS)
        team_with(None)
        team_with(AFTER_DAYS, issue_status=Status.RESOLVED)
        team_with(AFTER_DAYS, issue_status=None)

        with patch.object(
            auto_resolve_sweep, "team_flag_enabled", side_effect=lambda _flag, team_id: team_id != flag_off
        ):
            assert auto_resolve_team_ids() == [due]

    def test_activity_sends_one_event_and_counts_resolved_issues_per_team(self, _flag) -> None:
        create_issue_with_exceptions(self.team, exception_days_ago=[[20]])
        create_issue_with_exceptions(self.team, created_days_ago=400)
        self._enable()
        counted_before = REGISTRY.get_sample_value(COUNTER_SAMPLE) or 0
        capture = MagicMock()

        with patch("products.error_tracking.backend.temporal.auto_resolve.activities.ph_scoped_capture") as scoped:
            scoped.return_value.__enter__.return_value = capture
            result = ActivityEnvironment().run(
                auto_resolve_teams_activity, AutoResolveTeamsInputs(team_ids=[self.team.id])
            )

        assert (result.teams_processed, result.issues_resolved) == (1, 2)
        assert (REGISTRY.get_sample_value(COUNTER_SAMPLE) or 0) - counted_before == 2
        [call] = capture.call_args_list
        assert call.kwargs["event"] == "error tracking issues auto resolved"
        assert call.kwargs["distinct_id"] == str(self.team.uuid)
        assert call.kwargs["properties"] == {"resolved_count": 2, "after_days": AFTER_DAYS}

    @parameterized.expand(
        [
            ("sweep_fails", "sweep", (1, 1, 1)),
            ("event_fails", "event", (2, 0, 2)),
        ]
    )
    def test_activity_keeps_the_batch_going_when_one_team_fails(
        self, _flag, _name, failing_step, expected_counts
    ) -> None:
        failing_team = Team.objects.create(organization=self.organization)
        for team in (failing_team, self.team):
            create_issue_with_exceptions(team, exception_days_ago=[[20]])
            ErrorTrackingSettings.objects.update_or_create(team=team, defaults={"auto_resolve_after_days": AFTER_DAYS})
        find_candidates = auto_resolve_sweep.find_auto_resolve_candidates

        def find_or_fail(team, after_days):
            if failing_step == "sweep" and team.id == failing_team.id:
                raise RuntimeError("sweep failed")
            return find_candidates(team, after_days)

        def capture_or_fail(**kwargs):
            if failing_step == "event" and kwargs["distinct_id"] == str(failing_team.uuid):
                raise RuntimeError("capture failed")

        capture = MagicMock(side_effect=capture_or_fail)
        with (
            patch.object(auto_resolve_sweep, "find_auto_resolve_candidates", side_effect=find_or_fail),
            patch("products.error_tracking.backend.temporal.auto_resolve.activities.ph_scoped_capture") as scoped,
        ):
            scoped.return_value.__enter__.return_value = capture
            result = ActivityEnvironment().run(
                auto_resolve_teams_activity, AutoResolveTeamsInputs(team_ids=[failing_team.id, self.team.id])
            )

        assert (result.teams_processed, result.teams_failed, result.issues_resolved) == expected_counts
        assert str(self.team.uuid) in [call.kwargs["distinct_id"] for call in capture.call_args_list]
