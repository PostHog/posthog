import json

import pytest
from unittest.mock import MagicMock, patch

from social_django.models import UserSocialAuth

from posthog.constants import AvailableFeature
from posthog.models import Organization, Team, User
from posthog.models.organization import OrganizationMembership
from posthog.ownership.paths import UNOWNED_TEAM, PathOwnership

from products.access_control.backend.models.access_control import AccessControl
from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import PROwnerAssignment, ReviewerCorrections, SuggestedReviewerEntry
from products.signals.backend.models import (
    SignalReport,
    SignalReportArtefact,
    SignalReportAssignment,
    SignalUserAutonomyConfig,
)
from products.signals.backend.report_assignments import (
    claim_report,
    claim_report_for_task,
    sync_task_pull_request_to_assignments,
    update_assignments_for_pull_request,
)
from products.signals.backend.reviewer_pr_assignment import (
    assign_reviewers_to_pull_request,
    opted_in_assignee_logins,
    schedule_reviewer_pr_assignment,
)
from products.signals.backend.task_run_artefacts import record_implementation_task

# Task/TaskRun ORM models needed to build cross-product fixtures; the tasks facade exposes DTOs only.
from products.tasks.backend.models import Task, TaskRun

PR_URL = "https://github.com/PostHog/posthog/pull/123"
_NOT_UNASSIGNED = {"success": True, "unassigned": False}


@pytest.fixture(autouse=True)
def dri_flag():
    # The rule is always on in DEBUG, so DEBUG is pinned off for the flag to decide.
    with (
        patch("products.signals.backend.reviewer_pr_assignment.settings.DEBUG", False),
        patch("products.signals.backend.reviewer_pr_assignment.feature_enabled_or_false", return_value=False) as flag,
    ):
        yield flag


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
    UserSocialAuth.objects.create(user=user, provider="github", uid=str(100_000 + user.id), extra_data={"login": login})
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
    github.get_pull_request.return_value = {
        "success": True,
        "state": "open",
        "draft": False,
        "merged": False,
        "assignees": [],
        "requested_reviewers": [],
        "requested_teams": [],
    }
    github.add_pull_request_assignees.return_value = {"success": True, "assignees": ["opted-in"]}
    github.request_pull_request_reviews.return_value = {
        "success": True,
        "requested_reviewers": ["opted-in"],
    }
    github.list_submitted_pull_request_reviewers.return_value = {"success": True, "reviewed_by": []}
    github.get_removed_pull_request_reviewers.return_value = set()
    return github


class TestOptedInReviewerLogins:
    @pytest.mark.django_db
    def test_only_opted_in_reviewers_are_returned(self, org_and_team):
        org, team = org_and_team
        _make_reviewer(org, "opted-in", opted_in=True)
        _make_reviewer(org, "opted-out", opted_in=False)
        report = _make_report(team, ["opted-in", "opted-out"])

        assert opted_in_assignee_logins(team_id=team.id, report_id=str(report.id)) == ["opted-in"]

    @pytest.mark.django_db
    def test_reviewer_without_a_config_row_is_not_assigned(self, org_and_team):
        org, team = org_and_team
        user = User.objects.create(email="nobody@example.com", first_name="Reviewer")
        OrganizationMembership.objects.create(user=user, organization=org)
        UserSocialAuth.objects.create(user=user, provider="github", uid="gh-nobody", extra_data={"login": "nobody"})
        report = _make_report(team, ["nobody"])

        assert opted_in_assignee_logins(team_id=team.id, report_id=str(report.id)) == []

    @pytest.mark.django_db
    def test_reviewer_dropped_from_the_latest_row_is_not_assigned(self, org_and_team):
        org, team = org_and_team
        _make_reviewer(org, "opted-in", opted_in=True)
        _make_reviewer(org, "removed", opted_in=True)
        # suggested_reviewers is append-only and latest-wins, so only the newest row is live.
        report = _make_report(team, ["opted-in", "removed"], ["opted-in"])

        assert opted_in_assignee_logins(team_id=team.id, report_id=str(report.id)) == ["opted-in"]

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

        assert opted_in_assignee_logins(team_id=team.id, report_id=str(report.id)) == []


class TestAssignReviewersToPullRequest:
    @pytest.mark.django_db
    @pytest.mark.parametrize("disable_during_lookup", [False, True])
    def test_opted_in_reviewers_are_added_as_assignees(self, org_and_team, disable_during_lookup):
        org, team = org_and_team
        _make_reviewer(org, "opted-in", opted_in=True)
        _make_reviewer(org, "opted-out", opted_in=False)
        report = _make_report(team, ["opted-in", "opted-out"])
        github = _open_pr_github()

        with (
            patch(
                "products.signals.backend.reviewer_pr_assignment.assignment_side_effects_allowed", return_value=True
            ) as allowed,
            patch(
                "products.signals.backend.reviewer_pr_assignment.GitHubIntegration.first_for_team_repository",
                return_value=github,
            ),
        ):

            def read_pr(*_args: object) -> dict[str, object]:
                allowed.return_value = not disable_during_lookup
                return github.get_pull_request.return_value

            github.get_pull_request.side_effect = read_pr
            assigned = assign_reviewers_to_pull_request(team_id=team.id, report_id=str(report.id), pr_url=PR_URL)

        if disable_during_lookup:
            assert assigned == []
            github.add_pull_request_assignees.assert_not_called()
            github.request_pull_request_reviews.assert_not_called()
        else:
            assert assigned == ["opted-in"]
            github.add_pull_request_assignees.assert_called_once_with("PostHog/posthog", 123, ["opted-in"])

    @pytest.mark.django_db
    def test_no_reviewers_or_assignment_work_skips_github_entirely(self, org_and_team):
        _, team = org_and_team
        report = _make_report(team)

        with patch(
            "products.signals.backend.reviewer_pr_assignment.GitHubIntegration.first_for_team_repository"
        ) as mock_lookup:
            assert assign_reviewers_to_pull_request(team_id=team.id, report_id=str(report.id), pr_url=PR_URL) == []
        mock_lookup.assert_not_called()

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        ("assignees", "reviewed_by", "expected_reviewer"),
        [
            (["Assigned"], ["Completed"], "assigned"),
            (["Lower-Ranked"], ["Completed"], "lower-ranked"),
            (["Assigned", "Lower-Ranked"], ["Completed", "Assigned"], "new-reviewer"),
            (["outside-report"], ["Completed"], "outside-report"),
            (["Assigned"], ["Assigned"], None),
            ([], ["Completed"], "assigned"),
            (["Author"], [], None),
        ],
        ids=[
            "top-ranked-assignee",
            "lower-ranked-assignee",
            "multiple-assignees",
            "unlisted-assignee",
            "owner-reviewed",
            "no-owner",
            "owner-is-author",
        ],
    )
    def test_suggested_reviewers_receive_review_requests(
        self,
        org_and_team: tuple[Organization, Team],
        assignees: list[str],
        reviewed_by: list[str],
        expected_reviewer: str | None,
    ) -> None:
        org, team = org_and_team
        for login in ("author", "assigned", "completed", "new-reviewer", "lower-ranked"):
            _make_reviewer(org, login, opted_in=False)
        report = _make_report(team, ["author", "assigned", "completed", "new-reviewer", "lower-ranked"])
        github = _open_pr_github()
        github.get_pull_request.return_value.update({"author": "Author", "assignees": assignees})
        github.list_submitted_pull_request_reviewers.return_value = {"success": True, "reviewed_by": reviewed_by}
        github.request_pull_request_reviews.return_value = {
            "success": True,
            "requested_reviewers": [expected_reviewer] if expected_reviewer else [],
        }

        with patch(
            "products.signals.backend.reviewer_pr_assignment.GitHubIntegration.first_for_team_repository",
            return_value=github,
        ):
            assigned = assign_reviewers_to_pull_request(team_id=team.id, report_id=str(report.id), pr_url=PR_URL)

        assert assigned == []
        if expected_reviewer:
            github.request_pull_request_reviews.assert_called_once_with("PostHog/posthog", 123, [expected_reviewer])
        else:
            github.request_pull_request_reviews.assert_not_called()
        github.add_pull_request_assignees.assert_not_called()

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        ("existing_field", "existing_value"),
        [
            ("requested_reviewers", ["human-choice"]),
            ("requested_teams", ["owning-team"]),
            ("requested_reviewers", ["Suggested"]),
        ],
    )
    @pytest.mark.parametrize("owner", [None, "suggested"])
    def test_an_existing_review_request_only_allows_the_owner(
        self, org_and_team: tuple[Organization, Team], existing_field: str, existing_value: list[str], owner: str | None
    ) -> None:
        org, team = org_and_team
        _make_reviewer(org, "suggested", opted_in=False)
        report = _make_report(team, ["suggested"])
        github = _open_pr_github()
        github.get_pull_request.return_value[existing_field] = existing_value
        github.get_pull_request.return_value["assignees"] = [owner] if owner else []

        with patch(
            "products.signals.backend.reviewer_pr_assignment.GitHubIntegration.first_for_team_repository",
            return_value=github,
        ):
            assign_reviewers_to_pull_request(team_id=team.id, report_id=str(report.id), pr_url=PR_URL)

        if owner and existing_value != ["Suggested"]:
            github.request_pull_request_reviews.assert_called_once_with("PostHog/posthog", 123, [owner])
        else:
            github.list_submitted_pull_request_reviewers.assert_not_called()
            github.request_pull_request_reviews.assert_not_called()
        assert github.get_pull_request.return_value[existing_field] == existing_value

    @pytest.mark.django_db
    @pytest.mark.parametrize("owner", [None, "selected"])
    @pytest.mark.parametrize("removed", [{"selected"}, None])
    def test_removed_requests_and_unavailable_history_are_not_overridden(
        self, org_and_team: tuple[Organization, Team], owner: str | None, removed: set[str] | None
    ) -> None:
        org, team = org_and_team
        for login in ["selected", "other"]:
            _make_reviewer(org, login, opted_in=False)
        report = _make_report(team, ["selected", "other"])
        github = _open_pr_github()
        github.get_pull_request.return_value["assignees"] = [owner] if owner else []
        github.get_removed_pull_request_reviewers.return_value = removed

        with patch(
            "products.signals.backend.reviewer_pr_assignment.GitHubIntegration.first_for_team_repository",
            return_value=github,
        ):
            assign_reviewers_to_pull_request(team_id=team.id, report_id=str(report.id), pr_url=PR_URL)

        if owner is None and removed is not None:
            github.request_pull_request_reviews.assert_called_once_with("PostHog/posthog", 123, ["other"])
        else:
            github.request_pull_request_reviews.assert_not_called()

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
        github.request_pull_request_reviews.assert_not_called()

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        ("failing_call", "outcome", "expected"),
        [
            ("get_pull_request", Exception("boom"), []),
            ("get_pull_request", {"success": False, "error": "Failed to fetch pull request"}, []),
            ("list_submitted_pull_request_reviewers", Exception("boom"), ["opted-in"]),
            (
                "list_submitted_pull_request_reviewers",
                {"success": False, "error": "Failed to fetch reviews"},
                ["opted-in"],
            ),
            ("request_pull_request_reviews", Exception("boom"), ["opted-in"]),
            (
                "request_pull_request_reviews",
                {"success": False, "error": "Failed to request pull request reviews"},
                ["opted-in"],
            ),
            ("add_pull_request_assignees", Exception("boom"), []),
            ("add_pull_request_assignees", {"success": False, "error": "Failed to assign pull request"}, []),
        ],
        ids=[
            "pr_read_raises",
            "pr_read_reports_failure",
            "reviews_read_raises",
            "reviews_read_reports_failure",
            "review_request_raises",
            "review_request_reports_failure",
            "assign_raises",
            "assign_reports_failure",
        ],
    )
    def test_a_github_failure_is_swallowed(self, org_and_team, failing_call: str, outcome: object, expected: list[str]):
        org, team = org_and_team
        _make_reviewer(org, "opted-in", opted_in=True)
        reviewer_logins = ["opted-in"]
        if failing_call in {"list_submitted_pull_request_reviewers", "request_pull_request_reviews"}:
            _make_reviewer(org, "opted-out", opted_in=False)
            reviewer_logins.append("opted-out")
        report = _make_report(team, reviewer_logins)
        github = _open_pr_github()
        if isinstance(outcome, Exception):
            getattr(github, failing_call).side_effect = outcome
        else:
            getattr(github, failing_call).return_value = outcome

        with patch(
            "products.signals.backend.reviewer_pr_assignment.GitHubIntegration.first_for_team_repository",
            return_value=github,
        ):
            assert (
                assign_reviewers_to_pull_request(team_id=team.id, report_id=str(report.id), pr_url=PR_URL) == expected
            )

        if failing_call in {"list_submitted_pull_request_reviewers", "request_pull_request_reviews"}:
            github.list_submitted_pull_request_reviewers.assert_called_once_with("PostHog/posthog", 123)
            github.add_pull_request_assignees.assert_called_once_with("PostHog/posthog", 123, ["opted-in"])
        if failing_call == "request_pull_request_reviews":
            github.request_pull_request_reviews.assert_called_once_with("PostHog/posthog", 123, ["opted-in"])

    @pytest.mark.django_db
    def test_a_url_that_is_not_a_pull_request_is_not_assigned(self, org_and_team):
        org, team = org_and_team
        _make_reviewer(org, "opted-in", opted_in=True)
        report = _make_report(team, ["opted-in"])

        with patch(
            "products.signals.backend.reviewer_pr_assignment.GitHubIntegration.first_for_team_repository"
        ) as mock_lookup:
            assigned = assign_reviewers_to_pull_request(
                team_id=team.id, report_id=str(report.id), pr_url="https://example.com/not-a-pr"
            )

        assert assigned == []
        mock_lookup.assert_not_called()

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "lookup",
        [{"return_value": None}, {"side_effect": Exception("boom")}],
        ids=["no_integration", "lookup_raises"],
    )
    def test_an_unavailable_integration_is_not_assigned(self, org_and_team, lookup: dict):
        org, team = org_and_team
        _make_reviewer(org, "opted-in", opted_in=True)
        report = _make_report(team, ["opted-in"])

        with patch(
            "products.signals.backend.reviewer_pr_assignment.GitHubIntegration.first_for_team_repository", **lookup
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
    def test_reclaiming_the_same_pull_request_reassesses_the_owner(self, org_and_team):
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

        assert self.mock_delay.call_count == 2

    @pytest.mark.django_db(transaction=True)
    def test_syncing_a_task_pull_request_reassesses_each_verified_snapshot(self, org_and_team):
        _, team = org_and_team
        report = _make_report(team)
        task = Task.objects.create(team=team, title="Implementation", description="", origin_product="signals")
        record_implementation_task(team_id=team.id, report_id=str(report.id), task_id=str(task.id))

        for _ in range(2):
            sync_task_pull_request_to_assignments(team_id=team.id, task_id=str(task.id), pr_url=PR_URL, pr_state="open")

        assert self.mock_delay.call_count == 2
        self.mock_delay.assert_called_with(team_id=team.id, report_id=str(report.id), pr_url=PR_URL)

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
        SignalReportArtefact.objects.filter(report=report, type="pull_request").delete()
        self.mock_delay.reset_mock()

        update_assignments_for_pull_request(
            team_ids=[team.id],
            repository="PostHog/posthog",
            pr_number=123,
            pr_state=SignalReportAssignment.PrState.OPEN,
        )

        self.mock_delay.assert_called_once_with(team_id=team.id, report_id=str(report.id), pr_url=PR_URL)


class TestDirectlyResponsibleIndividual:
    @pytest.fixture(autouse=True)
    def _flag_on(self, dri_flag):
        dri_flag.return_value = True

    @pytest.fixture(autouse=True)
    def ownership(self):
        with patch(
            "products.signals.backend.pr_owning_team.resolve_path_owners",
            return_value=PathOwnership(team_by_path={}, registry={}, resolved=False),
        ) as resolve:
            yield resolve

    def _setup(self, org, team, reviewers: list[str], *, opted_in: tuple[str, ...] = ()) -> tuple[SignalReport, dict]:
        users = {
            login: _make_reviewer(org, login, opted_in=login in opted_in) for login in ("alice", "bob", "carol", "dave")
        }
        report = _make_report(team)
        rows = [
            {"user_uuid": str(users[entry.removeprefix("uuid:")].uuid), "github_login": None}
            if entry.startswith("uuid:")
            else {"github_login": entry}
            for entry in reviewers
        ]
        SignalReportArtefact.objects.create(
            team=team,
            report=report,
            type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
            content=json.dumps(rows),
        )
        return report, users

    def _assign(self, team, report, github: MagicMock) -> list[list[str]]:
        with patch(
            "products.signals.backend.reviewer_pr_assignment.GitHubIntegration.first_for_team_repository",
            return_value=github,
        ):
            assign_reviewers_to_pull_request(team_id=team.id, report_id=str(report.id), pr_url=PR_URL)
        return [call.args[2] for call in github.add_pull_request_assignees.call_args_list]

    def _github(self, *, existing_assignees: list[str], assignable: set[str] | None) -> MagicMock:
        github = _open_pr_github()
        assignee_state = list(existing_assignees)
        github.assignee_state = assignee_state
        github.get_pull_request.side_effect = lambda *_args: {
            "success": True,
            "state": "open",
            "merged": False,
            "assignees": list(assignee_state),
        }
        github.is_assignable.side_effect = lambda _repo, login: {
            "success": True,
            "assignable": assignable is None or login in assignable,
        }
        github.get_collaborator_permission.side_effect = lambda _repo, login, **_kwargs: (
            "write" if assignable is None or login in assignable else "none"
        )
        github.list_pull_request_files.return_value = {"success": True, "paths": ["posthog/api/a.py"]}
        github.was_ever_unassigned.return_value = {"success": True, "unassigned": False}

        def add_assignees(_repo, _number, logins):
            assignee_state[:] = list(dict.fromkeys([*assignee_state, *logins]))
            return {"success": True, "assignees": list(assignee_state)}

        def remove_assignees(_repo, _number, logins):
            assignee_state[:] = [login for login in assignee_state if login not in logins]
            return {"success": True, "assignees": list(assignee_state)}

        github.add_pull_request_assignees.side_effect = add_assignees
        github.remove_pull_request_assignees.side_effect = remove_assignees
        return github

    def _team_x(self, github: MagicMock) -> None:
        github.list_team_members.return_value = {"success": True, "logins": ["Bob", "dave", "stranger"]}

    def _claim(
        self, team, report, users: dict, *, kind: str, login: str, automation_branch: str | None = "auto"
    ) -> None:
        if kind in ("user", "agent"):
            actor = (
                ArtefactAttribution.from_user(users[login].id)
                if kind == "user"
                else ArtefactAttribution.from_agent(users[login].id, "some-agent")
            )
            claim_report(report=report, actor=actor, user=users[login], was_impersonated=False)
            return
        task = Task.objects.create(
            team=team, title="Implementation", description="", origin_product="signals", created_by=users[login]
        )
        claim_report_for_task(team_id=team.id, report_id=str(report.id), task_id=str(task.id))
        record_implementation_task(
            team_id=team.id,
            report_id=str(report.id),
            task_id=str(task.id),
            automation_branch=automation_branch,
        )

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        ("reviewers", "claimant", "expected_owner"),
        [
            (["alice", "bob"], None, "alice"),
            (["alice"], "user", "carol"),
            (["alice"], "agent", "carol"),
            (["alice"], "task", "alice"),
            (["alice"], "manual-task", "carol"),
            ([], "task", None),
            (["uuid:bob", "alice"], None, "bob"),
            (["stranger", "bob"], None, "bob"),
            ([], None, None),
        ],
        ids=[
            "top_reviewer",
            "a_person_who_chose_the_work_is_the_dri",
            "an_agent_claim_names_the_person_who_ran_it",
            "an_auto_started_task_claim_does_not_rank_its_claimant",
            "a_task_a_person_started_ranks_its_creator",
            "a_task_claim_alone_is_nobody_to_assign",
            "reviewer_stored_by_uuid",
            "non_member_skipped",
            "nobody_to_assign",
        ],
    )
    def test_the_owner_is_the_most_responsible_member(
        self, org_and_team, reviewers: list[str], claimant: str | None, expected_owner: str | None
    ):
        org, team = org_and_team
        report, users = self._setup(org, team, reviewers)
        if claimant:
            self._claim(
                team,
                report,
                users,
                kind="task" if claimant == "manual-task" else claimant,
                login="carol",
                automation_branch=None if claimant == "manual-task" else "auto",
            )

        calls = self._assign(team, report, self._github(existing_assignees=[], assignable=None))

        assert calls == ([[expected_owner]] if expected_owner else [])

    @pytest.mark.django_db
    @pytest.mark.parametrize("claimant", [None, "bob", "carol"])
    def test_assigning_the_dri_requests_their_review(
        self, org_and_team: tuple[Organization, Team], claimant: str | None
    ) -> None:
        org, team = org_and_team
        report, users = self._setup(org, team, ["alice", "bob"])
        if claimant:
            self._claim(team, report, users, kind="user", login=claimant)
        github = self._github(existing_assignees=[], assignable=None)

        assert self._assign(team, report, github) == [[claimant or "alice"]]
        github.request_pull_request_reviews.assert_called_once_with("PostHog/posthog", 123, [claimant or "alice"])

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        ("opted_in", "existing_assignees", "assignable", "expected_calls"),
        [
            ((), [], {"bob"}, [["bob"]]),
            ((), [], set(), []),
            (("bob",), [], None, [["bob"]]),
            ((), ["someone"], None, []),
        ],
        ids=[
            "unassignable_candidate_moves_on",
            "nobody_assignable",
            "opted_in_reviewer_is_enough",
            "already_assigned",
        ],
    )
    def test_a_pull_request_never_gets_a_second_owner(
        self,
        org_and_team,
        opted_in: tuple[str, ...],
        existing_assignees: list[str],
        assignable: set[str] | None,
        expected_calls: list[list[str]],
    ):
        org, team = org_and_team
        report, _ = self._setup(org, team, ["alice", "bob"], opted_in=opted_in)

        calls = self._assign(team, report, self._github(existing_assignees=existing_assignees, assignable=assignable))

        assert calls == expected_calls

    @pytest.mark.django_db
    def test_a_failed_assignee_check_stops_the_walk(self, org_and_team):
        org, team = org_and_team
        report, _ = self._setup(org, team, ["alice", "bob"])
        github = self._github(existing_assignees=[], assignable=None)
        github.get_collaborator_permission.side_effect = RuntimeError("Failed to check assignee")

        assert self._assign(team, report, github) == []
        assert github.get_collaborator_permission.call_count == 1

    @pytest.mark.django_db
    def test_a_linked_login_must_still_name_the_same_github_account(self, org_and_team):
        org, team = org_and_team
        report, users = self._setup(org, team, ["alice"])
        github = self._github(existing_assignees=[], assignable=None)
        github.get_collaborator_permission.return_value = "none"
        github.get_collaborator_permission.side_effect = None

        assert self._assign(team, report, github) == []
        github.get_collaborator_permission.assert_called_once_with(
            "PostHog/posthog",
            "alice",
            expected_user_id=int(users["alice"].social_auth.get(provider="github").uid),
        )
        github.add_pull_request_assignees.assert_not_called()

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        ("live_change", "change_during_remove", "expected_adds", "expected_owner"),
        [
            (None, False, [["alice"], ["bob"]], "bob"),
            ([], False, [["alice"]], "alice"),
            (["alice", "teammate"], False, [["alice"]], "alice"),
            (None, True, [["alice"], ["bob"]], "alice"),
        ],
        ids=[
            "automatic_owner_replaced",
            "manual_unassignment_preserved",
            "additional_assignee_preserved",
            "concurrent_additional_assignee_preserved",
        ],
    )
    def test_only_the_last_automatic_owner_can_be_reassessed(
        self,
        org_and_team,
        live_change: list[str] | None,
        change_during_remove: bool,
        expected_adds: list[list[str]],
        expected_owner: str,
    ):
        org, team = org_and_team
        report, _ = self._setup(org, team, ["alice", "bob"])
        github = self._github(existing_assignees=[], assignable=None)

        self._assign(team, report, github)
        if live_change is not None:
            github.assignee_state[:] = live_change
        SignalReportArtefact.objects.create(
            team=team,
            report=report,
            type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
            content=json.dumps([{"github_login": "bob"}, {"github_login": "alice"}]),
        )
        if change_during_remove:
            original_remove = github.remove_pull_request_assignees.side_effect

            def remove_with_concurrent_assignee(repository: str, number: int, logins: list[str]) -> dict[str, object]:
                if logins == ["alice"]:
                    github.assignee_state.append("teammate")
                return original_remove(repository, number, logins)

            github.remove_pull_request_assignees.side_effect = remove_with_concurrent_assignee
        calls = self._assign(team, report, github)

        assert calls == expected_adds
        assignments = [
            PROwnerAssignment.model_validate_json(content)
            for content in report.artefacts.filter(type="pr_owner_assignment")
            .order_by("created_at", "id")
            .values_list("content", flat=True)
        ]
        assert [owner.login for owner in assignments[-1].owners] == [expected_owner]
        if live_change is None and not change_during_remove:
            assert assignments[-1].replaced_logins == ("alice",)
            assert assignments[-1].owners[0].proof is not None
            assert assignments[-1].owners[0].proof.source == "github_oauth"
            github.remove_pull_request_assignees.assert_called_once_with("PostHog/posthog", 123, ["alice"])
        elif change_during_remove:
            assert len(assignments) == 1
            assert github.assignee_state == ["teammate"]
            assert [call.args[2] for call in github.remove_pull_request_assignees.call_args_list] == [
                ["alice"],
                ["bob"],
            ]
        else:
            assert len(assignments) == 1
            github.remove_pull_request_assignees.assert_not_called()

    @pytest.mark.django_db
    @pytest.mark.parametrize("correction", ["needs-review", "excluded-uuid", "excluded-login"])
    def test_report_corrections_apply_to_owning_team_candidates(
        self, org_and_team: tuple[Organization, Team], ownership: MagicMock, correction: str
    ) -> None:
        org, team = org_and_team
        report, users = self._setup(org, team, ["alice"])
        ownership.return_value = PathOwnership(team_by_path={"posthog/api/a.py": "team-x"}, registry={}, resolved=True)
        github = self._github(existing_assignees=[], assignable=None)
        github.list_team_members.return_value = {"success": True, "logins": ["alice"]}
        rules = ReviewerCorrections(
            needs_review=correction == "needs-review",
            excluded=(SuggestedReviewerEntry(user_uuid=str(users["alice"].uuid)),)
            if correction == "excluded-uuid"
            else (SuggestedReviewerEntry(github_login="alice"),)
            if correction == "excluded-login"
            else (),
        )
        SignalReportArtefact.objects.create(
            team=team, report=report, type="reviewer_corrections", content=rules.model_dump_json()
        )

        assert self._assign(team, report, github) == []

    @pytest.mark.django_db
    @pytest.mark.parametrize("source", ["claimant", "reviewer-uuid", "reviewer-login"])
    @pytest.mark.parametrize("unavailable", ["inactive", "project"])
    def test_ineligible_members_receive_no_assignment_or_review_request(
        self, org_and_team: tuple[Organization, Team], source: str, unavailable: str
    ) -> None:
        org, team = org_and_team
        reviewers = [] if source == "claimant" else ["uuid:alice" if source == "reviewer-uuid" else "alice"]
        report, users = self._setup(org, team, reviewers)
        if source == "claimant":
            self._claim(team, report, users, kind="user", login="alice")
        if unavailable == "inactive":
            User.objects.filter(id=users["alice"].id).update(is_active=False)
        else:
            org.available_product_features = [{"key": AvailableFeature.ACCESS_CONTROL, "name": "Access control"}]
            org.save(update_fields=["available_product_features"])
            AccessControl.objects.create(team=team, resource="project", resource_id=str(team.id), access_level="none")
        github = self._github(existing_assignees=[], assignable=None)

        assert self._assign(team, report, github) == []
        github.request_pull_request_reviews.assert_not_called()

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "change", ["assigned", "unassigned", "closed", "history-unavailable", "report", "claimant"]
    )
    def test_changes_during_github_checks_stop_dri_assignment(
        self, org_and_team: tuple[Organization, Team], change: str
    ) -> None:
        org, team = org_and_team
        report, users = self._setup(org, team, ["alice"])
        github = self._github(existing_assignees=[], assignable=None)

        def check(_repo: str, _login: str) -> dict[str, bool]:
            if change == "assigned":
                github.assignee_state[:] = ["manual-owner"]
            elif change == "unassigned":
                github.was_ever_unassigned.return_value = {"success": True, "unassigned": True}
            elif change == "closed":
                github.get_pull_request.side_effect = None
                github.get_pull_request.return_value = {"success": True, "state": "closed"}
            elif change == "history-unavailable":
                github.was_ever_unassigned.return_value = {"success": False}
            elif change == "report":
                SignalReportArtefact.objects.create(team=team, report=report, type="suggested_reviewers", content="[]")
            elif change == "claimant":
                self._claim(team, report, users, kind="user", login="bob")
            return {"success": True, "assignable": True}

        github.is_assignable.side_effect = check

        assert self._assign(team, report, github) == []

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        ("reviewers", "team_by_path", "members", "claimant", "expected_owner"),
        [
            (["alice"], {"a.py": "team-x", "b.py": "team-x", "c.py": "team-y"}, {"success": True}, None, "stranger"),
            (["bob"], {"a.py": "team-x"}, {"success": True}, None, "stranger"),
            (["alice"], {"a.py": "team-x"}, {"success": True}, ("task", "carol"), "stranger"),
            (["alice"], {"a.py": "team-x"}, {"success": True}, ("task", "bob"), "stranger"),
            (["alice"], {"a.py": "team-x"}, {"success": True}, ("user", "carol"), "carol"),
            (["alice"], None, {"success": True}, None, "alice"),
            (["alice"], {"a.py": UNOWNED_TEAM}, {"success": True}, None, "alice"),
            (["alice"], {"a.py": "team-x"}, {"success": False, "status_code": 403}, None, "alice"),
            (["alice"], {"a.py": "team-z"}, {"success": True}, None, "alice"),
        ],
        ids=[
            "random_member_of_the_majority_team_without_a_posthog_account",
            "a_suggested_member_gets_no_priority_in_the_team",
            "a_task_claim_outside_the_team_does_not_rank",
            "a_task_claim_inside_the_team_does_not_reorder_it",
            "a_person_who_chose_the_work_outranks_the_team",
            "no_owners_files_uses_reviewers",
            "unowned_files_use_reviewers",
            "unreadable_team_uses_reviewers",
            "team_without_members_uses_reviewers",
        ],
    )
    def test_the_owning_team_supplies_the_owner(
        self,
        org_and_team,
        ownership,
        reviewers: list[str],
        team_by_path: dict[str, str] | None,
        members: dict,
        claimant: tuple[str, str] | None,
        expected_owner: str,
    ):
        org, team = org_and_team
        report, users = self._setup(org, team, reviewers)
        if claimant:
            self._claim(team, report, users, kind=claimant[0], login=claimant[1])
        if team_by_path is not None:
            ownership.return_value = PathOwnership(team_by_path=team_by_path, registry={}, resolved=True)
        github = self._github(existing_assignees=[], assignable=None)
        github.list_pull_request_files.return_value = {"success": True, "paths": list(team_by_path or ["a.py"])}
        logins_by_team = {"team-x": ["Bob", "dave", "Stranger"], "team-y": ["stranger"], "team-z": []}
        github.list_team_members.side_effect = lambda _org, slug: {**members, "logins": logins_by_team[slug]}

        with patch(
            "products.signals.backend.pr_owning_team.random.shuffle",
            side_effect=lambda logins: logins.sort(reverse=True),
        ):
            calls = self._assign(team, report, github)

        assert calls == [[expected_owner]]

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        ("opted_in", "existing_assignees", "add_result", "events", "expected_calls"),
        [
            (("alice",), [], None, _NOT_UNASSIGNED, [["alice"]]),
            (("alice", "bob"), [], None, _NOT_UNASSIGNED, [["bob"]]),
            (("alice",), ["alice"], None, _NOT_UNASSIGNED, []),
            (("alice",), [], {"success": True, "assignees": ["alice", "someone"]}, _NOT_UNASSIGNED, [["alice"]]),
            (("bob",), [], None, _NOT_UNASSIGNED, [["bob"]]),
            (("alice",), [], {"success": False, "error": "Network error"}, _NOT_UNASSIGNED, [["alice"]]),
            ((), [], None, {"success": True, "unassigned": True}, []),
            ((), [], None, {"success": False, "error": "Failed to list issue events"}, []),
        ],
        ids=[
            "an_opted_in_person_outside_the_owning_team_is_the_dri",
            "two_opted_in_people_yield_one_dri_preferring_the_owner",
            "a_pull_request_that_already_has_an_assignee_is_left_alone",
            "a_hand_assignment_during_the_call_counts",
            "opted_in_reviewer_in_the_owning_team_is_the_owner",
            "unknown_assignment_outcome_adds_nobody_else",
            "a_hand_unassigned_pull_request_stays_unassigned",
            "unreadable_events_count_as_unassigned",
        ],
    )
    def test_the_dri_respects_what_already_happened(
        self,
        org_and_team,
        ownership,
        opted_in: tuple[str, ...],
        existing_assignees: list[str],
        add_result: dict | None,
        events: dict,
        expected_calls: list[list[str]],
    ):
        org, team = org_and_team
        report, _ = self._setup(org, team, ["alice", "bob"], opted_in=opted_in)
        ownership.return_value = PathOwnership(team_by_path={"posthog/api/a.py": "team-x"}, registry={}, resolved=True)
        github = self._github(existing_assignees=existing_assignees, assignable=None)
        self._team_x(github)
        github.was_ever_unassigned.return_value = events
        if add_result is not None:
            github.add_pull_request_assignees.side_effect = None
            github.add_pull_request_assignees.return_value = add_result

        with patch(
            "products.signals.backend.pr_owning_team.random.shuffle",
            side_effect=lambda logins: logins.sort(reverse=True),
        ):
            calls = self._assign(team, report, github)

        assert calls == expected_calls
