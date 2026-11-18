from types import SimpleNamespace

from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.utils import timezone

from parameterized import parameterized
from temporalio.client import WorkflowExecutionStatus

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, PersonalAPIKey, Team
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.access_control.backend.models.access_control import AccessControl
from products.review_hog.backend.models import ReviewReport


class TestReviewProjectAccess(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(patch("posthoganalytics.feature_enabled", return_value=True))
        self.membership = OrganizationMembership.objects.get(organization=self.organization, user=self.user)
        self.membership.level = OrganizationMembership.Level.MEMBER
        self.membership.save()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        AccessControl.objects.create(
            team=self.team, resource="project", resource_id=str(self.team.id), access_level="none"
        )
        self.environment = Team.objects.create(organization=self.organization, parent_team=self.team, name="Staging")
        self.url = f"/api/projects/{self.environment.id}/code_review/reviews/"
        self.report = ReviewReport.objects.for_team(self.team.id).create(
            team=self.team,
            repository="example-org/web",
            pr_number=42,
            pr_url="https://github.com/example-org/web/pull/42",
            acting_user=self.user,
            head_branch="feature",
            base_branch="main",
            run_count=1,
            last_run_at=timezone.now(),
            status=ReviewReport.Status.IDLE,
        )
        self.temporal = MagicMock()
        self.temporal.start_workflow = AsyncMock()
        self.temporal.get_workflow_handle.return_value.describe = AsyncMock(
            return_value=SimpleNamespace(status=WorkflowExecutionStatus.COMPLETED)
        )
        self.enterContext(patch("products.review_hog.backend.temporal.client.sync_connect", return_value=self.temporal))
        assert self.client.get(f"/api/projects/{self.environment.id}/").status_code == 200
        assert self.client.get(f"/api/projects/{self.team.id}/code_review/reviews/").status_code == 403

    def _grant_parent_access(self) -> None:
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            organization_member=self.membership,
            access_level="member",
        )

    def _authenticate(self, authentication: str) -> None:
        if authentication == "session":
            return
        scoped_teams = {
            "unrestricted_key": [],
            "both_teams_key": [self.environment.id, self.team.id],
            "child_key": [self.environment.id],
        }[authentication]
        value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="Review access test",
            user=self.user,
            secure_value=hash_key_value(value),
            scopes=["code_review:read", "code_review:write"],
            scoped_teams=scoped_teams,
        )
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {value}")

    @parameterized.expand(
        [
            (authentication, path)
            for authentication in ("session", "unrestricted_key", "both_teams_key")
            for path in ("", "table/", "perspective_stats/", "pr_status/", "{report_id}/")
        ]
    )
    def test_reads_require_parent_membership(self, authentication: str, path: str) -> None:
        self._authenticate(authentication)

        response = self.client.get(
            f"{self.url}{path.format(report_id=self.report.id)}",
            {"scope": "everyone", "pr_url": self.report.pr_url},
        )

        assert response.status_code == 403, response.content

    @parameterized.expand([("session",), ("unrestricted_key",), ("both_teams_key",)])
    def test_authorized_environment_reads_parent_reviews(self, authentication: str) -> None:
        self._grant_parent_access()
        self._authenticate(authentication)

        response = self.client.get(self.url, {"scope": "everyone"})

        assert response.status_code == 200, response.content
        assert [row["id"] for row in response.json()["results"]] == [str(self.report.id)]
        detail = self.client.get(f"{self.url}{self.report.id}/")
        assert detail.status_code == 200, detail.content
        assert detail.json()["id"] == str(self.report.id)

    @parameterized.expand(
        [
            ("session", False, 403),
            ("unrestricted_key", False, 403),
            ("both_teams_key", False, 403),
            ("child_key", True, 403),
            ("session", True, 202),
            ("unrestricted_key", True, 202),
            ("both_teams_key", True, 202),
        ]
    )
    def test_trigger_requires_user_and_key_access_to_parent(
        self, authentication: str, parent_access: bool, expected_status: int
    ) -> None:
        if parent_access:
            self._grant_parent_access()
        self._authenticate(authentication)
        metadata = SimpleNamespace(
            is_fork=False, state="open", head_sha="abc123", author="example-author", head_branch="feature"
        )
        with (
            patch(
                "products.review_hog.backend.requested_reviews.GitHubIntegration.first_for_team_repository",
                return_value=object(),
            ) as github_access,
            patch("products.review_hog.backend.requested_reviews.fetch_pr_metadata", return_value=metadata),
        ):
            response = self.client.post(self.url + "trigger/", {"pr_url": self.report.pr_url}, format="json")

        assert response.status_code == expected_status, response.content
        if expected_status == 403:
            github_access.assert_not_called()
            self.temporal.start_workflow.assert_not_called()
        else:
            self.temporal.start_workflow.assert_awaited_once()
            inputs = self.temporal.start_workflow.call_args.args[1].requests[0]
            assert inputs.team_id == self.team.id
            assert inputs.user_id == self.user.id
            assert inputs.acting_user_id == self.user.id
