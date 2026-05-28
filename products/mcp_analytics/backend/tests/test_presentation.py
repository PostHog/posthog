from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from products.mcp_analytics.backend import intent_generation
from products.mcp_analytics.backend.models import MCPAnalyticsSubmission, MCPIntentClusterSnapshot, MCPSession
from products.mcp_analytics.backend.tests import _MCPAnalyticsTeamScopedTestMixin


class TestMCPAnalyticsPresentation(_MCPAnalyticsTeamScopedTestMixin, APIBaseTest):
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

    def test_intent_clusters_returns_empty_idle_when_no_snapshot(self) -> None:
        response = self.client.get(f"/api/environments/{self.team.id}/mcp_analytics/intent_clusters/")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "idle"
        assert data["clusters"] == []
        assert data["last_computed_at"] is None
        assert data["computed_with"] is None

    def test_intent_clusters_returns_stored_snapshot(self) -> None:
        MCPIntentClusterSnapshot.objects.create(
            team=self.team,
            status=MCPIntentClusterSnapshot.Status.IDLE,
            clusters={
                "clusters": [
                    {
                        "id": 0,
                        "label": "check feature flag rollout",
                        "intent_count": 2,
                        "call_count": 14,
                        "error_count": 1,
                        "error_rate_pct": 7.1,
                        "routing_entropy": 0.1,
                        "tool_distribution": [
                            {"tool": "feature_flag_get", "count": 12, "pct": 85.7, "errors": 1, "error_rate_pct": 8.3},
                        ],
                        "sample_intents": ["check feature flag rollout"],
                    }
                ],
                "computed_with": {
                    "distance_threshold": 0.2,
                    "embedding_model": "text-embedding-3-small-1536",
                    "n_intents": 2,
                    "n_clusters": 1,
                },
            },
        )

        response = self.client.get(f"/api/environments/{self.team.id}/mcp_analytics/intent_clusters/")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "idle"
        assert len(data["clusters"]) == 1
        assert data["clusters"][0]["label"] == "check feature flag rollout"
        assert data["computed_with"]["n_clusters"] == 1

    def test_intent_clusters_recompute_enqueues_task_and_returns_computing(self) -> None:
        # Mock only the Celery dispatch so the synchronous COMPUTING write
        # still runs. The 202 body should reflect the new state, not the
        # stale pre-trigger state.
        with patch("products.mcp_analytics.backend.tasks.tasks.compute_intent_clusters.delay") as mock_delay:
            response = self.client.post(
                f"/api/environments/{self.team.id}/mcp_analytics/intent_clusters/recompute/", {}, format="json"
            )

        assert response.status_code == status.HTTP_202_ACCEPTED
        assert response.json()["status"] == "computing"
        mock_delay.assert_called_once_with(self.team.id, self.user.id)
        snapshot = MCPIntentClusterSnapshot.objects.get(team=self.team)
        assert snapshot.status == MCPIntentClusterSnapshot.Status.COMPUTING
        assert snapshot.last_computed_by_id == self.user.id

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


class TestMCPSessionIntentEndpoint(_MCPAnalyticsTeamScopedTestMixin, APIBaseTest):
    def _url(self, session_id: str) -> str:
        return f"/api/environments/{self.team.id}/mcp_analytics/sessions/{session_id}/generate_intent/"

    def test_requires_authentication(self) -> None:
        self.client.logout()
        response = self.client.post(self._url("abc"))
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_staff_only_in_cloud(self) -> None:
        with self.is_cloud(True):
            response = self.client.post(self._url("abc"))
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_returns_cached_intent_in_response_shape(self) -> None:
        session_id = "session-123"
        MCPSession.objects.create(team=self.team, session_id=session_id, intent="A persisted summary.")

        response = self.client.post(self._url(session_id))

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"session_id": session_id, "intent": "A persisted summary."}

    def test_generates_and_persists_when_empty(self) -> None:
        session_id = "session-fresh"
        # Mock the two primitives so the endpoint path runs without ClickHouse or a real LLM call.
        with (
            patch.object(intent_generation, "fetch_session_intents", return_value=["check the funnel"]),
            patch.object(intent_generation, "summarize_intents", return_value="Generated summary."),
        ):
            response = self.client.post(self._url(session_id))

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"session_id": session_id, "intent": "Generated summary."}
        assert MCPSession.objects.get(team=self.team, session_id=session_id).intent == "Generated summary."

    def test_returns_503_when_generation_unavailable(self) -> None:
        session_id = "session-unavailable"
        with (
            patch.object(intent_generation, "fetch_session_intents", return_value=["check the funnel"]),
            patch.object(
                intent_generation,
                "summarize_intents",
                side_effect=intent_generation.IntentGenerationUnavailable("LLM down"),
            ),
        ):
            response = self.client.post(self._url(session_id))

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        # Nothing persisted when generation fails.
        assert not MCPSession.objects.filter(team=self.team, session_id=session_id).exists()
