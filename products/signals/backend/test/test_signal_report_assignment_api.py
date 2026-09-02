from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.apps import apps

from parameterized import parameterized
from rest_framework import status

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.team.team import Team

from products.signals.backend.models import SignalActorKind, SignalReport, SignalReportAssignment


class TestSignalReportAssignmentAPI(APIBaseTest):
    def _create_report(
        self,
        *,
        team: Team | None = None,
        report_status: str = SignalReport.Status.READY,
        title: str = "Test report",
    ) -> SignalReport:
        return SignalReport.objects.create(
            team=team or self.team,
            status=report_status,
            title=title,
            summary="Test summary",
            signal_count=1,
            total_weight=1,
        )

    def _claim_url(self, report: SignalReport) -> str:
        return f"/api/projects/{self.team.id}/signals/reports/{report.id}/claim/"

    def _list_url(self, **query: str) -> str:
        suffix = "&".join(f"{key}={value}" for key, value in query.items())
        return f"/api/projects/{self.team.id}/signals/reports/{'?' + suffix if suffix else ''}"

    @staticmethod
    def _agent_headers(name: str) -> dict[str, str]:
        return {"X-PostHog-Client": "mcp", "X-Posthog-Mcp-Client-Name": name}

    def test_user_claim_returns_assignment_and_writes_activity(self):
        report = self._create_report()

        response = self.client.post(self._claim_url(report), data={}, format="json")

        assert response.status_code == status.HTTP_200_OK
        assignment = SignalReportAssignment.all_teams.get(report=report)
        assert assignment.actor_kind == SignalActorKind.USER
        assert assignment.actor_user_id == self.user.id
        assert assignment.actor_task_id is None
        assert assignment.actor_agent is None
        assert assignment.claimed_at is not None
        assert response.json()["work_state"] == "working"
        assert response.json()["assignee"]["kind"] == SignalActorKind.USER
        assert response.json()["assignee"]["user"]["id"] == self.user.id

        log = ActivityLog.objects.get(
            team_id=self.team.id,
            scope="SignalReport",
            item_id=str(report.id),
            activity="assignment_changed",
        )
        assert log.detail is not None
        assert log.detail["changes"][0]["field"] == "assignee"
        assert log.detail["changes"][0]["before"] is None
        assert log.detail["changes"][0]["after"]["kind"] == SignalActorKind.USER

    def test_identical_claim_is_idempotent(self):
        report = self._create_report()
        self.client.post(self._claim_url(report), data={}, format="json")
        claimed_at = SignalReportAssignment.all_teams.get(report=report).claimed_at

        response = self.client.post(self._claim_url(report), data={}, format="json")

        assert response.status_code == status.HTTP_200_OK
        assignment = SignalReportAssignment.all_teams.get(report=report)
        assert assignment.claimed_at == claimed_at
        assert (
            ActivityLog.objects.filter(
                team_id=self.team.id,
                scope="SignalReport",
                item_id=str(report.id),
                activity="assignment_changed",
            ).count()
            == 1
        )

    def test_external_agent_silently_takes_over_claim(self):
        report = self._create_report()
        self.client.post(
            self._claim_url(report),
            data={},
            format="json",
            headers=self._agent_headers("claude-code"),
        )

        response = self.client.post(
            self._claim_url(report),
            data={},
            format="json",
            headers=self._agent_headers("codex"),
        )

        assert response.status_code == status.HTTP_200_OK
        assignment = SignalReportAssignment.all_teams.get(report=report)
        assert assignment.actor_kind == SignalActorKind.AGENT
        assert assignment.actor_user_id == self.user.id
        assert assignment.actor_task_id is None
        assert assignment.actor_agent == "codex"
        logs = ActivityLog.objects.filter(
            team_id=self.team.id,
            scope="SignalReport",
            item_id=str(report.id),
            activity="assignment_changed",
        ).order_by("created_at")
        assert logs.count() == 2
        takeover = logs.last()
        assert takeover is not None and takeover.detail is not None
        change = takeover.detail["changes"][0]
        assert change["before"]["agent"] == "claude-code"
        assert change["after"]["agent"] == "codex"

    def test_generic_mcp_client_name_is_used_when_registration_name_is_missing(self):
        report = self._create_report()

        response = self.client.post(
            self._claim_url(report),
            data={},
            format="json",
            headers={"X-PostHog-Client": "mcp"},
        )

        assert response.status_code == status.HTTP_200_OK
        assignment = SignalReportAssignment.all_teams.get(report=report)
        assert assignment.actor_kind == SignalActorKind.AGENT
        assert assignment.actor_agent == "mcp"

    def test_internal_task_claim_uses_task_attribution(self):
        Task = apps.get_model("tasks", "Task")
        task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            title="Signal task",
            description="Implement the report",
            origin_product=Task.OriginProduct.SIGNAL_REPORT,
        )
        report = self._create_report()

        response = self.client.post(
            self._claim_url(report),
            data={},
            format="json",
            headers={"X-PostHog-Task-Id": str(task.id)},
        )

        assert response.status_code == status.HTTP_200_OK
        assignment = SignalReportAssignment.all_teams.get(report=report)
        assert assignment.actor_kind == SignalActorKind.TASK
        assert assignment.actor_user_id is None
        assert assignment.actor_task_id == task.id
        assert assignment.actor_agent is None
        assert response.json()["assignee"]["task_id"] == str(task.id)

    @patch("products.signals.backend.report_assignments.GitHubIntegration.first_for_team_repository")
    def test_connected_pull_request_details_are_fetched(self, mock_first_for_repository):
        github = MagicMock()
        github.get_pull_request.return_value = {
            "success": True,
            "url": "https://github.com/PostHog/posthog/pull/123",
            "state": "open",
            "draft": False,
            "merged": False,
        }
        mock_first_for_repository.return_value = github
        report = self._create_report()

        response = self.client.post(
            self._claim_url(report),
            data={"pr_url": "https://github.com/PostHog/posthog/pull/123"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        mock_first_for_repository.assert_called_once_with(self.team.id, "PostHog/posthog")
        github.get_pull_request.assert_called_once_with("PostHog/posthog", 123)
        assignment = SignalReportAssignment.all_teams.get(report=report)
        assert assignment.repository == "posthog/posthog"
        assert assignment.pr_number == 123
        assert assignment.pr_state == SignalReportAssignment.PrState.OPEN
        assert assignment.pr_merged is False
        assert response.json()["work_state"] == "in_review"

    @patch("products.signals.backend.report_assignments.GitHubIntegration.first_for_team_repository")
    def test_merged_pull_request_resolves_report_on_claim(self, mock_first_for_repository):
        github = MagicMock()
        github.get_pull_request.return_value = {
            "success": True,
            "url": "https://github.com/PostHog/posthog/pull/123",
            "state": "closed",
            "draft": False,
            "merged": True,
        }
        mock_first_for_repository.return_value = github
        report = self._create_report()

        response = self.client.post(
            self._claim_url(report),
            data={"pr_url": "https://github.com/PostHog/posthog/pull/123"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        report.refresh_from_db()
        assignment = SignalReportAssignment.all_teams.get(report=report)
        assert report.status == SignalReport.Status.RESOLVED
        assert assignment.pr_state == SignalReportAssignment.PrState.MERGED
        assert assignment.pr_merged is True
        assert response.json()["work_state"] == "done"

    @patch(
        "products.signals.backend.report_assignments.GitHubIntegration.first_for_team_repository",
        return_value=None,
    )
    def test_unconnected_pull_request_is_allowed_with_unknown_state(self, mock_first_for_repository):
        report = self._create_report()

        response = self.client.post(
            self._claim_url(report),
            data={"pr_url": "https://github.com/PostHog/posthog/pull/123"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        mock_first_for_repository.assert_called_once_with(self.team.id, "PostHog/posthog")
        assignment = SignalReportAssignment.all_teams.get(report=report)
        assert assignment.repository == "posthog/posthog"
        assert assignment.pr_number == 123
        assert assignment.pr_state == SignalReportAssignment.PrState.UNKNOWN
        assert assignment.pr_merged is False

    def test_only_current_actor_can_release_and_pr_is_preserved(self):
        report = self._create_report()
        claim = self.client.post(
            self._claim_url(report),
            data={"pr_url": "https://github.com/PostHog/posthog/pull/123"},
            format="json",
            headers=self._agent_headers("claude-code"),
        )
        assert claim.status_code == status.HTTP_200_OK

        rejected = self.client.post(
            self._claim_url(report),
            data={"release": True},
            format="json",
            headers=self._agent_headers("codex"),
        )
        assert rejected.status_code == status.HTTP_409_CONFLICT

        released = self.client.post(
            self._claim_url(report),
            data={"release": True},
            format="json",
            headers=self._agent_headers("claude-code"),
        )

        assert released.status_code == status.HTTP_200_OK
        assignment = SignalReportAssignment.all_teams.get(report=report)
        assert assignment.actor_kind is None
        assert assignment.actor_user_id is None
        assert assignment.actor_agent is None
        assert assignment.pr_url == "https://github.com/PostHog/posthog/pull/123"
        assert assignment.pr_state == SignalReportAssignment.PrState.UNKNOWN
        assert released.json()["work_state"] == "in_review"
        assert released.json()["assignee"] is None

    def test_release_and_pr_url_cannot_be_combined(self):
        report = self._create_report()

        response = self.client.post(
            self._claim_url(report),
            data={"release": True, "pr_url": "https://github.com/PostHog/posthog/pull/123"},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not SignalReportAssignment.all_teams.filter(report=report).exists()

    @parameterized.expand(
        [
            ("ready", SignalReport.Status.READY),
            ("pending_input", SignalReport.Status.PENDING_INPUT),
            ("potential", SignalReport.Status.POTENTIAL),
            ("suppressed", SignalReport.Status.SUPPRESSED),
        ]
    )
    def test_claimable_report_statuses(self, _name: str, report_status: str):
        report = self._create_report(report_status=report_status)

        response = self.client.post(self._claim_url(report), data={}, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert SignalReportAssignment.all_teams.filter(report=report).exists()

    def test_resolved_report_cannot_be_claimed(self):
        report = self._create_report(report_status=SignalReport.Status.RESOLVED)

        response = self.client.post(self._claim_url(report), data={}, format="json")

        assert response.status_code == status.HTTP_409_CONFLICT
        assert not SignalReportAssignment.all_teams.filter(report=report).exists()

    def test_claim_cannot_cross_team_boundary(self):
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        report = self._create_report(team=other_team)

        response = self.client.post(self._claim_url(report), data={}, format="json")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert not SignalReportAssignment.all_teams.filter(report=report).exists()

    def test_unclaimed_filter_excludes_claims_and_open_prs(self):
        unclaimed = self._create_report(title="Unclaimed")
        claimed = self._create_report(title="Claimed")
        in_review = self._create_report(title="In review")
        self.client.post(self._claim_url(claimed), data={}, format="json")
        SignalReportAssignment.all_teams.create(
            team=self.team,
            report=in_review,
            pr_url="https://github.com/PostHog/posthog/pull/123",
            repository="posthog/posthog",
            pr_number=123,
            pr_state=SignalReportAssignment.PrState.OPEN,
        )

        response = self.client.get(self._list_url(unclaimed="true"))

        assert response.status_code == status.HTTP_200_OK
        ids = {row["id"] for row in response.json()["results"]}
        assert str(unclaimed.id) in ids
        assert str(claimed.id) not in ids
        assert str(in_review.id) not in ids

    def test_assignee_me_matches_exact_external_agent(self):
        mine = self._create_report(title="Mine")
        other = self._create_report(title="Other")
        self.client.post(
            self._claim_url(mine),
            data={},
            format="json",
            headers=self._agent_headers("codex"),
        )
        self.client.post(
            self._claim_url(other),
            data={},
            format="json",
            headers=self._agent_headers("claude-code"),
        )

        response = self.client.get(
            self._list_url(assignee="me"),
            headers=self._agent_headers("codex"),
        )

        assert response.status_code == status.HTTP_200_OK
        assert {row["id"] for row in response.json()["results"]} == {str(mine.id)}

    def test_claimed_report_remains_in_default_actionable_list(self):
        report = self._create_report()
        self.client.post(self._claim_url(report), data={}, format="json")

        response = self.client.get(self._list_url())

        assert response.status_code == status.HTTP_200_OK
        row = next(row for row in response.json()["results"] if row["id"] == str(report.id))
        assert row["work_state"] == "working"
