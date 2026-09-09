import json

import pytest
from unittest.mock import MagicMock, patch

from social_django.models import UserSocialAuth

from posthog.models import Organization, Team, User
from posthog.models.organization import OrganizationMembership

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.models import (
    SignalReport,
    SignalReportArtefact,
    SignalReportAssignment,
    SignalUserAutonomyConfig,
)
from products.signals.backend.report_assignments import (
    claim_report,
    sync_task_pull_request_to_assignments,
    update_assignments_for_pull_request,
)
from products.signals.backend.reviewer_pr_assignment import (
    assign_reviewers_to_pull_request,
    opted_in_reviewer_logins,
    schedule_reviewer_pr_assignment,
)
from products.signals.backend.task_run_artefacts import record_implementation_task

# Task/TaskRun ORM models needed to build cross-product fixtures; the tasks facade exposes DTOs only.
from products.tasks.backend.models import Task, TaskRun

PR_URL = "https://github.com/PostHog/posthog/pull/123"


@pytest.fixture
def org_and_team():
    org = Organization.objects.create(name="pr-assign-org")
    team = Team.objects.create(organization=org, name="pr-assign-team")
    yield org, team
    team.delete()
    org.delete()


def _make_reviewer(org: Organization, login: str, *, opted_in: bool) -> User:
    user = User.objects.create(email=f"{login}@example.com", first_name="Reviewer")
    OrganizationMembership.objects.create(user=user, organization=org)
    UserSocialAuth.objects.create(user=user, provider="github", uid=f"gh-{login}", extra_data={"login": login})
    SignalUserAutonomyConfig.objects.create(user=user, github_assign_on_pull_request=opted_in)
    return user


def _make_report(team: Team, *reviewer_rows: list[str]) -> SignalReport:
    report = SignalReport.objects.create(
        team=team, status=SignalReport.Status.READY, title="Report", summary="Summary", signal_count=1, total_weight=1.0
    )
    for logins in reviewer_rows:
        SignalReportArtefact.objects.create(
            team=team,
            report=report,
            type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
            content=json.dumps([{"github_login": login} for login in logins]),
        )
    return report


def _open_pr_github() -> MagicMock:
    github = MagicMock()
    github.get_pull_request.return_value = {"success": True, "state": "open", "draft": False, "merged": False}
    github.add_pull_request_assignees.return_value = {"success": True, "assignees": ["opted-in"]}
    return github


class TestOptedInReviewerLogins:
    @pytest.mark.django_db
    def test_only_opted_in_reviewers_are_returned(self, org_and_team):
        org, team = org_and_team
        _make_reviewer(org, "opted-in", opted_in=True)
        _make_reviewer(org, "opted-out", opted_in=False)
        report = _make_report(team, ["opted-in", "opted-out"])

        assert opted_in_reviewer_logins(team_id=team.id, report_id=str(report.id)) == ["opted-in"]

    @pytest.mark.django_db
    def test_reviewer_without_a_config_row_is_not_assigned(self, org_and_team):
        org, team = org_and_team
        user = User.objects.create(email="nobody@example.com", first_name="Reviewer")
        OrganizationMembership.objects.create(user=user, organization=org)
        UserSocialAuth.objects.create(user=user, provider="github", uid="gh-nobody", extra_data={"login": "nobody"})
        report = _make_report(team, ["nobody"])

        assert opted_in_reviewer_logins(team_id=team.id, report_id=str(report.id)) == []

    @pytest.mark.django_db
    def test_reviewer_dropped_from_the_latest_row_is_not_assigned(self, org_and_team):
        org, team = org_and_team
        _make_reviewer(org, "opted-in", opted_in=True)
        _make_reviewer(org, "removed", opted_in=True)
        # suggested_reviewers is append-only and latest-wins, so only the newest row is live.
        report = _make_report(team, ["opted-in", "removed"], ["opted-in"])

        assert opted_in_reviewer_logins(team_id=team.id, report_id=str(report.id)) == ["opted-in"]

    @pytest.mark.django_db
    @pytest.mark.parametrize("content", ["not json", '{"github_login": "opted-in"}'])
    def test_unreadable_reviewers_row_yields_nothing(self, org_and_team, content: str):
        org, team = org_and_team
        _make_reviewer(org, "opted-in", opted_in=True)
        report = _make_report(team)
        SignalReportArtefact.objects.create(
            team=team,
            report=report,
            type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
            content=content,
        )

        assert opted_in_reviewer_logins(team_id=team.id, report_id=str(report.id)) == []


class TestAssignReviewersToPullRequest:
    @pytest.mark.django_db
    def test_opted_in_reviewers_are_added_as_assignees(self, org_and_team):
        org, team = org_and_team
        _make_reviewer(org, "opted-in", opted_in=True)
        _make_reviewer(org, "opted-out", opted_in=False)
        report = _make_report(team, ["opted-in", "opted-out"])
        github = _open_pr_github()

        with patch(
            "products.signals.backend.reviewer_pr_assignment.GitHubIntegration.first_for_team_repository",
            return_value=github,
        ):
            assigned = assign_reviewers_to_pull_request(team_id=team.id, report_id=str(report.id), pr_url=PR_URL)

        assert assigned == ["opted-in"]
        github.add_pull_request_assignees.assert_called_once_with("PostHog/posthog", 123, ["opted-in"])

    @pytest.mark.django_db
    def test_no_opted_in_reviewers_skips_github_entirely(self, org_and_team):
        org, team = org_and_team
        _make_reviewer(org, "opted-out", opted_in=False)
        report = _make_report(team, ["opted-out"])

        with patch(
            "products.signals.backend.reviewer_pr_assignment.GitHubIntegration.first_for_team_repository"
        ) as mock_lookup:
            assert assign_reviewers_to_pull_request(team_id=team.id, report_id=str(report.id), pr_url=PR_URL) == []
        mock_lookup.assert_not_called()

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "pr",
        [
            {"success": True, "state": "closed", "draft": False, "merged": False},
            {"success": True, "state": "closed", "draft": False, "merged": True},
        ],
        ids=["closed", "merged"],
    )
    def test_a_closed_pull_request_is_not_assigned(self, org_and_team, pr: dict):
        org, team = org_and_team
        _make_reviewer(org, "opted-in", opted_in=True)
        report = _make_report(team, ["opted-in"])
        github = _open_pr_github()
        github.get_pull_request.return_value = pr

        with patch(
            "products.signals.backend.reviewer_pr_assignment.GitHubIntegration.first_for_team_repository",
            return_value=github,
        ):
            assert assign_reviewers_to_pull_request(team_id=team.id, report_id=str(report.id), pr_url=PR_URL) == []
        github.add_pull_request_assignees.assert_not_called()

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        ("failing_call", "outcome"),
        [
            ("get_pull_request", Exception("boom")),
            ("add_pull_request_assignees", Exception("boom")),
            ("add_pull_request_assignees", {"success": False, "error": "Failed to assign pull request"}),
        ],
        ids=["pr_read_raises", "assign_raises", "assign_reports_failure"],
    )
    def test_a_github_failure_is_swallowed(self, org_and_team, failing_call: str, outcome: object):
        org, team = org_and_team
        _make_reviewer(org, "opted-in", opted_in=True)
        report = _make_report(team, ["opted-in"])
        github = _open_pr_github()
        if isinstance(outcome, Exception):
            getattr(github, failing_call).side_effect = outcome
        else:
            getattr(github, failing_call).return_value = outcome

        with patch(
            "products.signals.backend.reviewer_pr_assignment.GitHubIntegration.first_for_team_repository",
            return_value=github,
        ):
            assert assign_reviewers_to_pull_request(team_id=team.id, report_id=str(report.id), pr_url=PR_URL) == []

    @pytest.mark.django_db
    def test_a_report_from_another_team_is_not_assigned(self, org_and_team):
        org, team = org_and_team
        other_team = Team.objects.create(organization=org, name="other-team")
        _make_reviewer(org, "opted-in", opted_in=True)
        report = _make_report(other_team, ["opted-in"])

        with patch(
            "products.signals.backend.reviewer_pr_assignment.GitHubIntegration.first_for_team_repository"
        ) as mock_lookup:
            assert assign_reviewers_to_pull_request(team_id=team.id, report_id=str(report.id), pr_url=PR_URL) == []
        mock_lookup.assert_not_called()


class TestScheduleReviewerPrAssignment:
    @pytest.mark.django_db(transaction=True)
    @pytest.mark.parametrize(
        ("pr_url", "pr_state", "expected"),
        [
            (PR_URL, SignalReportAssignment.PrState.OPEN, True),
            (PR_URL, SignalReportAssignment.PrState.DRAFT, True),
            (PR_URL, SignalReportAssignment.PrState.UNKNOWN, True),
            (PR_URL, SignalReportAssignment.PrState.CLOSED, False),
            (PR_URL, SignalReportAssignment.PrState.MERGED, False),
            (PR_URL, None, True),
            (None, SignalReportAssignment.PrState.OPEN, False),
        ],
    )
    def test_only_a_reviewable_pull_request_queues_work(
        self, org_and_team, pr_url: str | None, pr_state: str, expected: bool
    ):
        _, team = org_and_team
        report = _make_report(team)

        with patch("products.signals.backend.tasks.assign_reviewers_on_implementation_pr.delay") as mock_delay:
            schedule_reviewer_pr_assignment(team_id=team.id, report_id=str(report.id), pr_url=pr_url, pr_state=pr_state)

        assert mock_delay.called is expected


class TestPullRequestLinkingQueuesAssignment:
    """Wiring guards for each path where a PR URL first reaches a report. A hook that silently
    stops firing leaves the feature dead with every unit test above still green."""

    @pytest.fixture(autouse=True)
    def _queued(self):
        with patch("products.signals.backend.tasks.assign_reviewers_on_implementation_pr.delay") as mock_delay:
            self.mock_delay = mock_delay
            yield

    @pytest.mark.django_db(transaction=True)
    def test_claiming_a_report_with_a_pull_request_queues_assignment(self, org_and_team):
        _, team = org_and_team
        report = _make_report(team)
        user = User.objects.create(email="claimer@example.com")

        with patch(
            "products.signals.backend.report_assignments.GitHubIntegration.first_for_team_repository",
            return_value=None,
        ):
            claim_report(
                report=report,
                actor=ArtefactAttribution.from_user(user.id),
                user=user,
                was_impersonated=False,
                pr_url=PR_URL,
                release=False,
            )

        self.mock_delay.assert_called_once_with(team_id=team.id, report_id=str(report.id), pr_url=PR_URL)

    @pytest.mark.django_db(transaction=True)
    def test_reclaiming_the_same_pull_request_does_not_requeue(self, org_and_team):
        _, team = org_and_team
        report = _make_report(team)
        user = User.objects.create(email="claimer@example.com")

        with patch(
            "products.signals.backend.report_assignments.GitHubIntegration.first_for_team_repository",
            return_value=None,
        ):
            for _ in range(2):
                claim_report(
                    report=report,
                    actor=ArtefactAttribution.from_user(user.id),
                    user=user,
                    was_impersonated=False,
                    pr_url=PR_URL,
                    release=False,
                )

        assert self.mock_delay.call_count == 1

    @pytest.mark.django_db(transaction=True)
    def test_syncing_a_task_pull_request_queues_assignment_once(self, org_and_team):
        _, team = org_and_team
        report = _make_report(team)
        task = Task.objects.create(team=team, title="Implementation", description="", origin_product="signals")
        record_implementation_task(team_id=team.id, report_id=str(report.id), task_id=str(task.id))

        for _ in range(2):
            sync_task_pull_request_to_assignments(team_id=team.id, task_id=str(task.id), pr_url=PR_URL, pr_state="open")

        self.mock_delay.assert_called_once_with(team_id=team.id, report_id=str(report.id), pr_url=PR_URL)

    @pytest.mark.django_db(transaction=True)
    def test_a_merged_task_pull_request_is_not_queued(self, org_and_team):
        _, team = org_and_team
        report = _make_report(team)
        task = Task.objects.create(team=team, title="Implementation", description="", origin_product="signals")
        record_implementation_task(team_id=team.id, report_id=str(report.id), task_id=str(task.id))

        sync_task_pull_request_to_assignments(
            team_id=team.id, task_id=str(task.id), pr_url=PR_URL, pr_state="merged", pr_merged=True
        )

        self.mock_delay.assert_not_called()

    @pytest.mark.django_db(transaction=True)
    def test_a_webhook_that_first_links_the_pull_request_queues_assignment(self, org_and_team):
        _, team = org_and_team
        report = _make_report(team)
        task = Task.objects.create(team=team, title="Implementation", description="", origin_product="signals")
        record_implementation_task(team_id=team.id, report_id=str(report.id), task_id=str(task.id))
        # A task run carries the PR while the assignment row does not, which is the state the
        # webhook resolves the link from.
        TaskRun.objects.create(
            team=team,
            task=task,
            status=TaskRun.Status.COMPLETED,
            output={"pr_url": PR_URL},
        )
        SignalReportAssignment.all_teams.filter(report=report).update(
            pr_url=None, repository=None, pr_number=None, pr_state=SignalReportAssignment.PrState.UNKNOWN
        )
        self.mock_delay.reset_mock()

        update_assignments_for_pull_request(
            team_ids=[team.id],
            repository="PostHog/posthog",
            pr_number=123,
            pr_state=SignalReportAssignment.PrState.OPEN,
        )

        self.mock_delay.assert_called_once_with(team_id=team.id, report_id=str(report.id), pr_url=PR_URL)
