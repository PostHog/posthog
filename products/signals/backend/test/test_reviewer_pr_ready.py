import json

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from social_django.models import UserSocialAuth

from posthog.models import Organization, Team, User
from posthog.models.organization import OrganizationMembership

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.models import (
    SignalReport,
    SignalReportArtefact,
    SignalReportAssignment,
    SignalTeamConfig,
    SignalUserAutonomyConfig,
)
from products.signals.backend.report_assignments import (
    claim_report,
    sync_task_pull_request_to_assignments,
    update_assignments_for_pull_request,
)
from products.signals.backend.reviewer_pr_ready import (
    open_pull_request_ready_for_review,
    schedule_open_pull_request_ready,
    should_open_pull_request_ready,
)
from products.signals.backend.task_run_artefacts import record_implementation_task

# Task/TaskRun ORM models needed to build cross-product fixtures; the tasks facade exposes DTOs only.
from products.tasks.backend.models import Task, TaskRun

PR_URL = "https://github.com/PostHog/posthog/pull/123"


@pytest.fixture
def org_and_team():
    org = Organization.objects.create(name="pr-ready-org")
    team = Team.objects.create(organization=org, name="pr-ready-team")
    yield org, team
    team.delete()
    org.delete()


def _make_reviewer(org: Organization, login: str, *, wants_ready: bool | None) -> User:
    user = User.objects.create(email=f"{login}@example.com", first_name="Reviewer")
    OrganizationMembership.objects.create(user=user, organization=org)
    UserSocialAuth.objects.create(user=user, provider="github", uid=f"gh-{login}", extra_data={"login": login})
    SignalUserAutonomyConfig.objects.create(user=user, github_open_pull_request_ready=wants_ready)
    return user


def _make_member_without_github(org: Organization, *, wants_ready: bool | None) -> User:
    user = User.objects.create(email="no-github@example.com", first_name="Reviewer")
    OrganizationMembership.objects.create(user=user, organization=org)
    SignalUserAutonomyConfig.objects.create(user=user, github_open_pull_request_ready=wants_ready)
    return user


def _make_report_with_payloads(team: Team, payloads: list[dict]) -> SignalReport:
    report = SignalReport.objects.create(
        team=team, status=SignalReport.Status.READY, title="Report", summary="Summary", signal_count=1, total_weight=1.0
    )
    SignalReportArtefact.objects.create(
        team=team,
        report=report,
        type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
        content=json.dumps(payloads),
    )
    return report


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


def _set_team_default(team: Team, value: bool) -> None:
    SignalTeamConfig.objects.update_or_create(team=team, defaults={"default_open_pull_request_ready": value})


def _draft_pr_github() -> MagicMock:
    github = MagicMock()
    github.mark_pull_request_ready_for_review.return_value = {"success": True, "changed": True}
    return github


class TestShouldOpenPullRequestReady:
    @pytest.mark.django_db
    @pytest.mark.parametrize(
        ("preferences", "team_default", "expected"),
        [
            ([True], False, True),
            ([False], False, False),
            ([None], False, False),
            ([None], True, True),
            # One reviewer wanting the full CI matrix does not conflict with another's preference.
            ([True, False], False, True),
            ([False], True, False),
            ([True, None], False, True),
        ],
        ids=["opted_in", "opted_out", "inherits_off", "inherits_on", "mixed", "overrides_team_on", "one_of_two"],
    )
    def test_the_reviewer_setting_wins_over_the_team_default(
        self, org_and_team, preferences: list[bool | None], team_default: bool, expected: bool
    ):
        org, team = org_and_team
        _set_team_default(team, team_default)
        logins = []
        for index, preference in enumerate(preferences):
            login = f"reviewer{index}"
            _make_reviewer(org, login, wants_ready=preference)
            logins.append(login)
        report = _make_report(team, logins)

        assert should_open_pull_request_ready(team_id=team.id, report_id=str(report.id)) is expected

    @pytest.mark.django_db
    def test_a_reviewer_without_a_config_row_follows_the_team_default(self, org_and_team):
        org, team = org_and_team
        _set_team_default(team, True)
        user = User.objects.create(email="nobody@example.com", first_name="Reviewer")
        OrganizationMembership.objects.create(user=user, organization=org)
        UserSocialAuth.objects.create(user=user, provider="github", uid="gh-nobody", extra_data={"login": "nobody"})
        report = _make_report(team, ["nobody"])

        assert should_open_pull_request_ready(team_id=team.id, report_id=str(report.id)) is True

    @pytest.mark.django_db
    def test_a_reviewer_dropped_from_the_latest_row_no_longer_decides(self, org_and_team):
        org, team = org_and_team
        _make_reviewer(org, "removed", wants_ready=True)
        _make_reviewer(org, "kept", wants_ready=None)
        # suggested_reviewers is append-only and latest-wins, so only the newest row is live.
        report = _make_report(team, ["removed", "kept"], ["kept"])

        assert should_open_pull_request_ready(team_id=team.id, report_id=str(report.id)) is False

    @pytest.mark.django_db
    @pytest.mark.parametrize("team_default", [True, False])
    def test_a_report_with_no_resolvable_reviewer_follows_the_team_default(self, org_and_team, team_default: bool):
        _, team = org_and_team
        _set_team_default(team, team_default)
        report = _make_report(team, ["nobody-we-know"])

        assert should_open_pull_request_ready(team_id=team.id, report_id=str(report.id)) is team_default

    @pytest.mark.django_db
    def test_a_team_that_never_touched_the_setting_stays_on_draft(self, org_and_team):
        org, team = org_and_team
        _make_reviewer(org, "inheriting", wants_ready=None)
        report = _make_report(team, ["inheriting"])

        assert should_open_pull_request_ready(team_id=team.id, report_id=str(report.id)) is False


class TestReviewersWithoutAGithubAccount:
    @pytest.mark.django_db
    def test_a_reviewer_stored_by_uuid_still_decides(self, org_and_team):
        # An org member who never connected GitHub is stored by uuid with a null login, so resolving
        # logins alone would drop them and silently fall back to the team default.
        org, team = org_and_team
        user = _make_member_without_github(org, wants_ready=True)
        report = _make_report_with_payloads(team, [{"user_uuid": str(user.uuid), "github_login": None}])

        assert should_open_pull_request_ready(team_id=team.id, report_id=str(report.id)) is True

    @pytest.mark.django_db
    def test_a_uuid_entry_does_not_pick_up_the_preference_behind_its_stale_login(self, org_and_team):
        # Reviewer identity gives the uuid precedence, so a login that has since been reassigned to
        # somebody else must not lend that person's preference to this entry.
        org, team = org_and_team
        opted_out = _make_member_without_github(org, wants_ready=False)
        _make_reviewer(org, "reassigned", wants_ready=True)
        report = _make_report_with_payloads(team, [{"user_uuid": str(opted_out.uuid), "github_login": "reassigned"}])

        assert should_open_pull_request_ready(team_id=team.id, report_id=str(report.id)) is False


class TestOpenPullRequestReadyForReview:
    @pytest.mark.django_db
    def test_an_opted_in_reviewer_marks_the_pull_request_ready(self, org_and_team):
        org, team = org_and_team
        _make_reviewer(org, "opted-in", wants_ready=True)
        report = _make_report(team, ["opted-in"])
        github = _draft_pr_github()

        with patch(
            "products.signals.backend.reviewer_pr_ready.GitHubIntegration.first_for_team_repository",
            return_value=github,
        ):
            assert open_pull_request_ready_for_review(team_id=team.id, report_id=str(report.id), pr_url=PR_URL) is True

        # `no-ci` has to reach GitHub as a guard, not be resolved after the PR is out of draft.
        github.mark_pull_request_ready_for_review.assert_called_once_with(
            "PostHog/posthog", 123, skip_labels=frozenset({"no-ci"})
        )

    @pytest.mark.django_db
    def test_no_opted_in_reviewer_skips_github_entirely(self, org_and_team):
        org, team = org_and_team
        _make_reviewer(org, "opted-out", wants_ready=False)
        report = _make_report(team, ["opted-out"])

        with patch(
            "products.signals.backend.reviewer_pr_ready.GitHubIntegration.first_for_team_repository"
        ) as mock_lookup:
            assert open_pull_request_ready_for_review(team_id=team.id, report_id=str(report.id), pr_url=PR_URL) is False
        mock_lookup.assert_not_called()

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "outcome",
        [
            Exception("boom"),
            {"success": False, "error": "Failed to mark pull request ready"},
            {"success": True, "changed": False, "reason": "label"},
        ],
        ids=["raises", "reports_failure", "guard_stopped_it"],
    )
    def test_a_github_failure_or_guard_is_swallowed(self, org_and_team, outcome: object):
        org, team = org_and_team
        _make_reviewer(org, "opted-in", wants_ready=True)
        report = _make_report(team, ["opted-in"])
        github = _draft_pr_github()
        if isinstance(outcome, Exception):
            github.mark_pull_request_ready_for_review.side_effect = outcome
        else:
            github.mark_pull_request_ready_for_review.return_value = outcome

        with patch(
            "products.signals.backend.reviewer_pr_ready.GitHubIntegration.first_for_team_repository",
            return_value=github,
        ):
            assert open_pull_request_ready_for_review(team_id=team.id, report_id=str(report.id), pr_url=PR_URL) is False

    @pytest.mark.django_db
    def test_a_report_from_another_team_is_not_touched(self, org_and_team):
        org, team = org_and_team
        other_team = Team.objects.create(organization=org, name="other-team")
        _make_reviewer(org, "opted-in", wants_ready=True)
        report = _make_report(other_team, ["opted-in"])

        with patch(
            "products.signals.backend.reviewer_pr_ready.GitHubIntegration.first_for_team_repository"
        ) as mock_lookup:
            assert open_pull_request_ready_for_review(team_id=team.id, report_id=str(report.id), pr_url=PR_URL) is False
        mock_lookup.assert_not_called()


class TestScheduleOpenPullRequestReady:
    @pytest.mark.django_db(transaction=True)
    @pytest.mark.parametrize(
        ("pr_url", "pr_state", "expected"),
        [
            (PR_URL, SignalReportAssignment.PrState.DRAFT, True),
            (PR_URL, SignalReportAssignment.PrState.UNKNOWN, True),
            (PR_URL, None, True),
            # Nothing to undraft, so no GitHub round trip is worth queuing.
            (PR_URL, SignalReportAssignment.PrState.OPEN, False),
            (PR_URL, SignalReportAssignment.PrState.CLOSED, False),
            (PR_URL, SignalReportAssignment.PrState.MERGED, False),
            (None, SignalReportAssignment.PrState.DRAFT, False),
        ],
    )
    def test_only_a_pull_request_that_could_be_a_draft_queues_work(
        self, org_and_team, pr_url: str | None, pr_state: str, expected: bool
    ):
        _, team = org_and_team
        report = _make_report(team)

        with patch("products.signals.backend.tasks.open_implementation_pr_for_review.delay") as mock_delay:
            schedule_open_pull_request_ready(
                team_id=team.id, report_id=str(report.id), pr_url=pr_url, pr_state=pr_state
            )

        assert mock_delay.called is expected


class TestPullRequestLinkingQueuesTheReadyTransition:
    """Wiring guards for each path where a PR URL first reaches a report. A hook that silently stops
    firing leaves the feature dead with every unit test above still green. These are also what keeps
    the transition to once per pull request: nothing re-queues it after the link is recorded, so a
    reviewer who converts the pull request back to draft is never overridden."""

    @pytest.fixture(autouse=True)
    def _queued(self):
        with patch("products.signals.backend.tasks.open_implementation_pr_for_review.delay") as mock_delay:
            self.mock_delay = mock_delay
            yield

    @pytest.mark.django_db(transaction=True)
    def test_claiming_a_report_with_a_pull_request_queues_it_once(self, org_and_team):
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

        self.mock_delay.assert_called_once_with(team_id=team.id, report_id=str(report.id), pr_url=PR_URL)

    @pytest.mark.django_db(transaction=True)
    def test_syncing_a_task_pull_request_queues_it_once(self, org_and_team):
        _, team = org_and_team
        report = _make_report(team)
        task = Task.objects.create(team=team, title="Implementation", description="", origin_product="signals")
        record_implementation_task(team_id=team.id, report_id=str(report.id), task_id=str(task.id))

        for _ in range(2):
            sync_task_pull_request_to_assignments(
                team_id=team.id, task_id=str(task.id), pr_url=PR_URL, pr_state="draft"
            )

        self.mock_delay.assert_called_once_with(team_id=team.id, report_id=str(report.id), pr_url=PR_URL)

    @pytest.mark.django_db(transaction=True)
    def test_a_webhook_that_first_links_the_pull_request_queues_it(self, org_and_team):
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
            pr_state=SignalReportAssignment.PrState.DRAFT,
        )

        self.mock_delay.assert_called_once_with(team_id=team.id, report_id=str(report.id), pr_url=PR_URL)


class TestOpenPullRequestReadyAPI(APIBaseTest):
    ENDPOINT = "/api/users/@me/signal_autonomy/"

    def test_the_setting_round_trips_back_to_following_the_project_default(self):
        # The partial update is hand-rolled per field, so clearing the override has to store null
        # rather than false: false opts the reviewer out of a project default they wanted.
        assert self.client.post(self.ENDPOINT, {"github_open_pull_request_ready": True}).status_code == 200
        assert SignalUserAutonomyConfig.objects.get(user=self.user).github_open_pull_request_ready is True

        response = self.client.post(self.ENDPOINT, {"github_open_pull_request_ready": None})

        assert response.status_code == 200
        assert response.json()["github_open_pull_request_ready"] is None
        assert SignalUserAutonomyConfig.objects.get(user=self.user).github_open_pull_request_ready is None

    def test_another_setting_does_not_wipe_it(self):
        self.client.post(self.ENDPOINT, {"github_open_pull_request_ready": True})

        self.client.post(self.ENDPOINT, {"github_assign_on_pull_request": True})

        assert SignalUserAutonomyConfig.objects.get(user=self.user).github_open_pull_request_ready is True
