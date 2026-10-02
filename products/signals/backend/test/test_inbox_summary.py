from datetime import UTC, datetime, timedelta
from io import StringIO

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.models.github_integration_base import GitHubIntegrationError
from posthog.models.integration import GitHubIntegration

from products.access_control.backend.models.access_control import AccessControl
from products.signals.backend.inbox_summary import sync_pull_request_participants
from products.signals.backend.models import SignalReport, SignalReportPullRequest, SignalReportTask
from products.signals.backend.pull_requests import update_pull_request_state
from products.tasks.backend.models import Task, TaskRun

NOW = datetime(2026, 9, 20, 12, tzinfo=UTC)
MERGED_AT = NOW - timedelta(days=1)


@time_machine.travel(NOW, tick=False)
class TestInboxSummary(APIBaseTest):
    def make_pr(
        self,
        number: int = 1,
        *,
        team: Team | None = None,
        merged_at: datetime | None = MERGED_AT,
        participant_ids: list[int] | None = None,
        verified: bool = True,
        relationship: str = "implementation",
        state: str = "merged",
    ) -> SignalReportPullRequest:
        team = team or self.team
        pr = SignalReportPullRequest.objects.for_team(team.id).create(
            team=team,
            repository="example/app",
            number=number,
            url=f"https://github.com/example/app/pull/{number}",
            state=state,
            merged_at=merged_at,
            participant_ids=participant_ids,
            participants_synced_at=NOW if participant_ids is not None else None,
        )
        report = SignalReport.objects.create(team=team, title="Example report", summary="Example finding")
        task = Task.objects.create(team=team, title="Example task", description="", origin_product="signals")
        SignalReportTask.objects.create(team=team, report=report, task=task, relationship=relationship)
        run = TaskRun.objects.create(team=team, task=task, status=TaskRun.Status.COMPLETED)
        TaskRun.objects.filter(id=run.id).update(
            output={"pr_url": pr.url}, state={"verified_pr_urls": [pr.url] if verified else []}
        )
        return pr

    def summary(self, query: str = "") -> dict:
        response = self.client.get(f"/api/projects/{self.team.id}/signals/inbox-summary/{query}")
        assert response.status_code == 200, response.data
        return response.json()

    def test_counts_verified_implementation_prs_and_distinct_people(self) -> None:
        self.make_pr(1, participant_ids=[10, 20])
        self.make_pr(2, participant_ids=[20, 30])
        self.make_pr(3, participant_ids=[40], verified=False)
        self.make_pr(4, participant_ids=[50], relationship="research")
        self.make_pr(5, participant_ids=[60], relationship="discussion")
        self.make_pr(6, participant_ids=[70], state="open")
        foreign_team = Team.objects.create(organization=self.organization)
        self.make_pr(7, team=foreign_team, participant_ids=[80])
        with patch("products.signals.backend.inbox_summary.GitHubIntegration.first_for_team_repository") as github:
            result = self.summary("?scope=for-you&reviewer=123")
        github.assert_not_called()
        assert result == {
            "period_start": "2026-09-13T12:00:00Z",
            "period_end": "2026-09-20T12:00:00Z",
            "merged_pr_count": 2,
            "people_count": 3,
            "participation_complete": True,
        }

    def test_a_pr_with_multiple_task_associations_counts_once(self) -> None:
        self.make_pr(participant_ids=[10])
        gate = SignalReportTask.objects.get(team=self.team)
        report = SignalReport.objects.create(team=self.team, title="Second report", summary="Example")
        SignalReportTask.objects.create(
            team=self.team, report=report, task_id=gate.task_id, relationship="implementation"
        )
        assert self.summary()["merged_pr_count"] == 1

    def test_attribution_uses_repository_and_number_not_the_first_attached_url(self) -> None:
        pr = self.make_pr(1, participant_ids=[10])
        SignalReportPullRequest.objects.for_team(self.team.id).filter(id=pr.id).update(
            url="https://github.com/EXAMPLE/APP/pull/1/files"
        )
        TaskRun.objects.filter(team=self.team).update(
            state={"verified_pr_urls": ["https://github.com/Example/App/pull/1"]}
        )
        self.make_pr(10, verified=False, participant_ids=[20])
        assert self.summary()["merged_pr_count"] == 1

    def test_window_is_half_open_and_uses_merge_time(self) -> None:
        self.make_pr(1, merged_at=NOW - timedelta(days=7), participant_ids=[])
        self.make_pr(2, merged_at=NOW - timedelta(days=7, microseconds=1), participant_ids=[])
        self.make_pr(3, merged_at=NOW, participant_ids=[])
        self.make_pr(4, merged_at=None, participant_ids=[])
        assert self.summary()["merged_pr_count"] == 1

    def test_missing_participation_is_unknown_not_a_partial_count(self) -> None:
        self.make_pr(1, participant_ids=[10])
        self.make_pr(2)
        result = self.summary()
        assert result["merged_pr_count"] == 2
        assert result["people_count"] is None
        assert result["participation_complete"] is False

    def test_no_merges_returns_zero(self) -> None:
        result = self.summary()
        assert result["merged_pr_count"] == 0
        assert result["people_count"] == 0
        assert result["participation_complete"] is True

    def test_another_project_is_not_accessible(self) -> None:
        other_team = Team.objects.create(organization=Organization.objects.create(name="Other organization"))
        self.make_pr(team=other_team, participant_ids=[10])
        assert self.client.get(f"/api/projects/{other_team.id}/signals/inbox-summary/").status_code in (403, 404)

    def test_access_to_one_task_does_not_grant_access_to_project_totals(self) -> None:
        self.make_pr(participant_ids=[10])
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        member = User.objects.create_and_join(self.organization, "restricted@example.com", "test-password")
        membership = OrganizationMembership.objects.get(user=member, organization=self.organization)
        AccessControl.objects.create(
            team=self.team, resource="task", access_level="none", organization_member=membership
        )
        AccessControl.objects.create(
            team=self.team,
            resource="task",
            resource_id=str(Task.objects.get(team=self.team).id),
            access_level="editor",
            organization_member=membership,
        )
        self.client.force_login(member)
        assert self.client.get(f"/api/projects/{self.team.id}/signals/inbox-summary/").status_code == 403

    def test_authentication_is_required(self) -> None:
        self.client.logout()
        assert self.client.get(f"/api/projects/{self.team.id}/signals/inbox-summary/").status_code in (401, 403)

    def github(self) -> MagicMock:
        github = MagicMock()
        github.get_pull_request.return_value = {
            "success": True,
            "merged": True,
            "merged_at": MERGED_AT.isoformat(),
            "merged_by": {"id": 10, "type": "User", "login": "example-merger"},
        }
        github.get_pull_request_reviews.return_value = []
        return github

    def sync(self, github: MagicMock) -> None:
        with patch(
            "products.signals.backend.inbox_summary.GitHubIntegration.first_for_team_repository", return_value=github
        ):
            sync_pull_request_participants(team_id=self.team.id, repository="example/app", pr_number=1)

    def test_sync_keeps_human_approvals_before_merge_and_deduplicates(self) -> None:
        pr = self.make_pr(merged_at=None)
        github = self.github()
        github.get_pull_request_reviews.return_value = [
            {
                "state": state,
                "submitted_at": submitted_at.isoformat(),
                "user": {"id": user_id, "type": user_type, "login": login},
            }
            for state, submitted_at, user_id, user_type, login in [
                ("APPROVED", NOW - timedelta(days=10), 20, "User", "example-approver"),
                ("APPROVED", MERGED_AT, 10, "User", "example-merger"),
                ("APPROVED", MERGED_AT, 20, "User", "renamed-approver"),
                ("DISMISSED", MERGED_AT, 30, "User", "dismissed-approver"),
                ("CHANGES_REQUESTED", MERGED_AT, 40, "User", "example-reviewer"),
                ("APPROVED", NOW, 50, "User", "late-approver"),
                ("APPROVED", MERGED_AT, 60, "Bot", "example-app"),
                ("APPROVED", MERGED_AT, 70, "User", "example[bot]"),
            ]
        ]
        self.sync(github)
        self.sync(github)
        pr.refresh_from_db()
        assert pr.merged_at == MERGED_AT
        assert pr.participant_ids == [10, 20]
        assert pr.participants_synced_at == NOW

    @parameterized.expand([("missing_merger",), ("missing_review_page",), ("invalid_approval_time",)])
    def test_incomplete_github_data_does_not_store_partial_people(self, failure: str) -> None:
        pr = self.make_pr(merged_at=None)
        github = self.github()
        if failure == "missing_merger":
            github.get_pull_request.return_value["merged_by"] = None
        elif failure == "missing_review_page":
            github.get_pull_request_reviews.side_effect = GitHubIntegrationError("Missing page")
        else:
            github.get_pull_request_reviews.return_value = [{"state": "APPROVED", "submitted_at": "invalid"}]
        with self.assertRaises(GitHubIntegrationError):
            self.sync(github)
        pr.refresh_from_db()
        assert pr.merged_at == MERGED_AT
        assert pr.participant_ids is None
        assert pr.participants_synced_at is None

    def test_an_old_missing_merge_time_is_repaired_without_fetching_reviews(self) -> None:
        pr = self.make_pr(merged_at=None)
        github = self.github()
        github.get_pull_request.return_value["merged_at"] = (NOW - timedelta(days=30)).isoformat()
        self.sync(github)
        github.get_pull_request_reviews.assert_not_called()
        pr.refresh_from_db()
        assert pr.merged_at == NOW - timedelta(days=30)

    def test_a_failed_refresh_does_not_leave_outdated_participants_complete(self) -> None:
        pr = self.make_pr(participant_ids=[10, 20])
        github = self.github()
        github.get_pull_request_reviews.side_effect = GitHubIntegrationError("Reviews not available")
        with self.assertRaises(GitHubIntegrationError):
            self.sync(github)
        pr.refresh_from_db()
        assert pr.participant_ids is None
        assert pr.participants_synced_at is None

    @parameterized.expand([("manual", False, "implementation"), ("research", True, "research")])
    def test_sync_skips_unattributed_prs(self, _name: str, verified: bool, relationship: str) -> None:
        self.make_pr(verified=verified, relationship=relationship)
        github = self.github()
        self.sync(github)
        github.get_pull_request.assert_not_called()

    def test_merge_schedules_refresh_after_commit(self) -> None:
        self.make_pr(state="open", merged_at=None)
        with patch("products.signals.backend.tasks.refresh_pull_request_participants.delay") as enqueue:
            with self.captureOnCommitCallbacks(execute=True):
                update_pull_request_state(
                    team_id=self.team.id, repository="example/app", number=1, state="merged", merged_at=MERGED_AT
                )
                enqueue.assert_not_called()
            enqueue.assert_called_once_with(team_id=self.team.id, repository="example/app", pr_number=1)

    def test_backfill_is_bounded_resumable_and_includes_missing_merge_times(self) -> None:
        self.make_pr(1, merged_at=None)
        self.make_pr(2)
        self.make_pr(3, merged_at=NOW - timedelta(days=30))
        self.make_pr(4, participant_ids=[10])
        output = StringIO()
        with patch("products.signals.backend.tasks.refresh_pull_request_participants.delay") as enqueue:
            call_command("backfill_inbox_summary", team_id=self.team.id, limit=1, dry_run=True, stdout=output)
            enqueue.assert_not_called()
            output = StringIO()
            call_command("backfill_inbox_summary", team_id=self.team.id, limit=1, stdout=output)
            assert enqueue.call_count == 1
            cursor = output.getvalue().split("--after ")[1].strip()
            call_command("backfill_inbox_summary", team_id=self.team.id, after=cursor, stdout=StringIO())
            assert enqueue.call_count == 2
            assert {call.kwargs["pr_number"] for call in enqueue.call_args_list} == {1, 2}


class TestPullRequestReviewPagination(SimpleTestCase):
    @parameterized.expand([("../example/app", 1), ("example/app?path=other", 1), ("example/app", 0)])
    def test_rejects_invalid_identity_before_network_access(self, repository: str, number: int) -> None:
        github = GitHubIntegration(MagicMock(kind="github"))
        with patch.object(github, "_installation_authenticated_get_pages") as fetch:
            with self.assertRaises(GitHubIntegrationError):
                github.get_pull_request_reviews(repository, number)
            fetch.assert_not_called()

    def test_reads_every_page(self) -> None:
        github = GitHubIntegration(MagicMock(kind="github"))
        first = MagicMock(
            status_code=200, links={"next": {"url": "https://api.github.com/repos/example/app/pulls/1/reviews?page=2"}}
        )
        first.json.return_value = [{"id": index} for index in range(100)]
        second = MagicMock(status_code=200, links={})
        second.json.return_value = [{"id": 100}]
        with patch.object(github, "_installation_authenticated_get", side_effect=[first, second]):
            assert len(github.get_pull_request_reviews("example/app", 1)) == 101

    def test_rejects_partial_pages(self) -> None:
        github = GitHubIntegration(MagicMock(kind="github"))
        with patch.object(github, "_installation_authenticated_get_pages", return_value=([MagicMock()], False)):
            with self.assertRaises(GitHubIntegrationError):
                github.get_pull_request_reviews("example/app", 1)
