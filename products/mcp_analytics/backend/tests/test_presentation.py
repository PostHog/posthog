from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from products.mcp_analytics.backend.models import MCPAnalyticsSubmission


class TestMCPAnalyticsPresentation(APIBaseTest):
    @parameterized.expand(
        [
            ("feedback_create", "post", "feedback/", {"goal": "understand usage", "feedback": "Need clearer results"}),
            (
                "missing_capability_create",
                "post",
                "missing_capabilities/",
                {"goal": "debug surveys", "missing_capability": "Need an eligibility explainer"},
            ),
            ("feedback_list", "get", "feedback/", None),
            ("missing_capability_list", "get", "missing_capabilities/", None),
        ]
    )
    def test_endpoints_require_authentication(
        self, _name: str, method: str, path: str, payload: dict[str, str] | None
    ) -> None:
        self.client.logout()

        request = getattr(self.client, method)
        response = request(f"/api/environments/{self.team.id}/mcp_analytics/{path}", payload, format="json")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @parameterized.expand(
        [
            ("feedback_create", "post", "feedback/", {"goal": "understand usage", "feedback": "Need clearer results"}),
            (
                "missing_capability_create",
                "post",
                "missing_capabilities/",
                {"goal": "debug surveys", "missing_capability": "Need an eligibility explainer"},
            ),
            ("feedback_list", "get", "feedback/", None),
            ("missing_capability_list", "get", "missing_capabilities/", None),
        ]
    )
    def test_endpoints_are_staff_only_in_cloud(
        self, _name: str, method: str, path: str, payload: dict[str, str] | None
    ) -> None:
        with self.is_cloud(True):
            request = getattr(self.client, method)
            response = request(f"/api/environments/{self.team.id}/mcp_analytics/{path}", payload, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_create_feedback_submission(self) -> None:
        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_analytics/feedback/",
            {
                "goal": "understand why feature flag releases keep failing",
                "feedback": "I need a better explanation of rollout blast radius before changing a flag.",
                "category": "results",
                "attempted_tool": "feature_flag_get_all",
                "mcp_client_name": "Claude Desktop",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()

        assert data["kind"] == MCPAnalyticsSubmission.Kind.FEEDBACK
        assert data["goal"] == "understand why feature flag releases keep failing"
        assert data["summary"] == "I need a better explanation of rollout blast radius before changing a flag."
        assert data["category"] == "results"
        assert data["attempted_tool"] == "feature_flag_get_all"
        assert data["mcp_client_name"] == "Claude Desktop"

    @parameterized.expand(
        [
            ("missing_goal", {"feedback": "Need clearer results"}, "goal"),
            (
                "invalid_category",
                {"goal": "understand usage", "feedback": "Need clearer results", "category": "bad"},
                "category",
            ),
            ("goal_too_long", {"goal": "g" * 501, "feedback": "Need clearer results"}, "goal"),
            ("feedback_too_long", {"goal": "understand usage", "feedback": "f" * 5001}, "feedback"),
        ]
    )
    def test_feedback_validation_errors(self, _name: str, payload: dict[str, str], field: str) -> None:
        response = self.client.post(f"/api/environments/{self.team.id}/mcp_analytics/feedback/", payload, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == field

    def test_create_missing_capability_submission_defaults_blocked(self) -> None:
        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_analytics/missing_capabilities/",
            {
                "goal": "debug why my survey is not showing",
                "missing_capability": "I need a tool that explains survey eligibility for a specific user.",
                "attempted_tool": "survey_get",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()

        assert data["kind"] == MCPAnalyticsSubmission.Kind.MISSING_CAPABILITY
        assert data["blocked"] is True
        assert data["attempted_tool"] == "survey_get"

    @parameterized.expand(
        [
            ("missing_goal", {"missing_capability": "Need an eligibility explainer"}, "goal"),
            ("goal_too_long", {"goal": "g" * 501, "missing_capability": "Need an eligibility explainer"}, "goal"),
            (
                "missing_capability_too_long",
                {"goal": "debug surveys", "missing_capability": "m" * 5001},
                "missing_capability",
            ),
        ]
    )
    def test_missing_capability_validation_errors(self, _name: str, payload: dict[str, str], field: str) -> None:
        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_analytics/missing_capabilities/", payload, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == field

    def test_feedback_list_is_team_scoped(self) -> None:
        MCPAnalyticsSubmission.objects.create(
            team=self.team,
            created_by=self.user,
            kind=MCPAnalyticsSubmission.Kind.FEEDBACK,
            goal="understand usage",
            summary="Feedback for this team",
        )
        other_team = self.organization.teams.create(name="Other Team")
        MCPAnalyticsSubmission.objects.create(
            team=other_team,
            created_by=self.user,
            kind=MCPAnalyticsSubmission.Kind.FEEDBACK,
            goal="other",
            summary="Should not leak",
        )

        response = self.client.get(f"/api/environments/{self.team.id}/mcp_analytics/feedback/")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["results"]) == 1
        assert response.json()["results"][0]["summary"] == "Feedback for this team"

    def test_feedback_and_missing_capability_lists_are_split_by_kind(self) -> None:
        MCPAnalyticsSubmission.objects.create(
            team=self.team,
            created_by=self.user,
            kind=MCPAnalyticsSubmission.Kind.FEEDBACK,
            goal="improve prompts",
            summary="Feedback entry",
        )
        MCPAnalyticsSubmission.objects.create(
            team=self.team,
            created_by=self.user,
            kind=MCPAnalyticsSubmission.Kind.MISSING_CAPABILITY,
            goal="debug tool errors",
            summary="Missing capability entry",
            blocked=False,
        )

        feedback_response = self.client.get(f"/api/environments/{self.team.id}/mcp_analytics/feedback/")
        missing_response = self.client.get(f"/api/environments/{self.team.id}/mcp_analytics/missing_capabilities/")

        assert feedback_response.status_code == status.HTTP_200_OK
        assert missing_response.status_code == status.HTTP_200_OK
        assert [entry["kind"] for entry in feedback_response.json()["results"]] == [
            MCPAnalyticsSubmission.Kind.FEEDBACK
        ]
        assert [entry["kind"] for entry in missing_response.json()["results"]] == [
            MCPAnalyticsSubmission.Kind.MISSING_CAPABILITY
        ]

    def test_feedback_list_is_paginated(self) -> None:
        for index in range(101):
            MCPAnalyticsSubmission.objects.create(
                team=self.team,
                created_by=self.user,
                kind=MCPAnalyticsSubmission.Kind.FEEDBACK,
                goal=f"goal {index}",
                summary=f"Feedback entry {index}",
            )

        response = self.client.get(f"/api/environments/{self.team.id}/mcp_analytics/feedback/")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["count"] == 101
        assert len(data["results"]) == 100
        assert data["next"] is not None
