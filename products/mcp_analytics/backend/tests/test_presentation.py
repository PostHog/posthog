from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization, Team
from posthog.models.utils import uuid7

from products.mcp_analytics.backend import intent_generation
from products.mcp_analytics.backend.models import MCPAnalyticsSubmission, MCPIntentClusterSnapshot, MCPSession
from products.mcp_analytics.backend.presentation.serializers import (
    MCP_SESSION_LIST_DEFAULT_LIMIT,
    MCP_SESSION_LIST_MAX_LIMIT,
    MCPSessionListQuerySerializer,
)
from products.mcp_analytics.backend.tests import _MCPAnalyticsTeamScopedTestMixin


class TestMCPAnalyticsPresentation(_MCPAnalyticsTeamScopedTestMixin, APIBaseTest):
    # The mcp-analytics feature flag is enabled for the whole test by the mixin's setUp.
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
    def test_endpoints_require_feature_flag(
        self, _name: str, method: str, path: str, payload: dict[str, str] | None
    ) -> None:
        with patch("posthoganalytics.feature_enabled", return_value=False):
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
        with patch("posthoganalytics.feature_enabled", return_value=True):
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

        with patch("posthoganalytics.feature_enabled", return_value=True):
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
        with (
            patch("products.mcp_analytics.backend.tasks.tasks.compute_intent_clusters.delay") as mock_delay,
            patch("posthoganalytics.feature_enabled", return_value=True),
        ):
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
    # The mcp-analytics feature flag is enabled for the whole test by the mixin's setUp.
    def _url(self, session_id: str) -> str:
        return f"/api/environments/{self.team.id}/mcp_analytics/sessions/{session_id}/generate_intent/"

    def test_requires_authentication(self) -> None:
        self.client.logout()
        response = self.client.post(self._url("abc"))
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_requires_feature_flag(self) -> None:
        with patch("posthoganalytics.feature_enabled", return_value=False):
            response = self.client.post(self._url("abc"))
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_returns_cached_intent_in_response_shape(self) -> None:
        session_id = "session-123"
        MCPSession.objects.create(team=self.team, session_id=session_id, intent="A persisted summary.")

        with patch("posthoganalytics.feature_enabled", return_value=True):
            response = self.client.post(self._url(session_id))

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"session_id": session_id, "intent": "A persisted summary."}

    def test_generates_and_persists_when_empty(self) -> None:
        session_id = "session-fresh"
        # Mock the two primitives so the endpoint path runs without ClickHouse or a real LLM call.
        with (
            patch("posthoganalytics.feature_enabled", return_value=True),
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
            patch("posthoganalytics.feature_enabled", return_value=True),
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


class TestMCPSessionToolCallsEndpoint(_MCPAnalyticsTeamScopedTestMixin, ClickhouseTestMixin, APIBaseTest):
    """The detail event list is bounded by the session's aggregated session_start. Listing *all*
    events hinges on that bound surviving the serialize -> query-param -> parse round-trip without
    dropping the first event (the one at exactly session_start)."""

    def setUp(self) -> None:
        super().setUp()
        cache.clear()

    def test_tool_calls_bounded_by_session_start_returns_every_event(self) -> None:
        session_id = str(uuid7())
        now = datetime.now(tz=UTC)
        events = [(now - timedelta(hours=2), "first_tool"), (now - timedelta(minutes=5), "last_tool")]
        for timestamp, tool in events:
            _create_event(
                team=self.team,
                event="$mcp_tool_call",
                distinct_id="seed",
                timestamp=timestamp,
                properties={"$session_id": session_id, "$mcp_tool_name": tool},
            )

        with patch("posthoganalytics.feature_enabled", return_value=True):
            listed = self.client.get(f"/api/environments/{self.team.id}/mcp_analytics/sessions/", {"date_from": "-7d"})
            assert listed.status_code == status.HTTP_200_OK
            session = next(s for s in listed.json()["results"] if s["session_id"] == session_id)
            # Hand the serialized session_start straight back, exactly as the UI does.
            response = self.client.get(
                f"/api/environments/{self.team.id}/mcp_analytics/sessions/{session_id}/tool_calls/",
                {"date_from": session["session_start"]},
            )

        assert response.status_code == status.HTTP_200_OK
        # The first event sits at exactly session_start; a `timestamp >= session_start` bound must
        # still include it after the round-trip — otherwise we'd get just ["last_tool"].
        assert [c["tool_name"] for c in response.json()["results"]] == ["first_tool", "last_tool"]


class TestMCPSessionListQuerySerializer(SimpleTestCase):
    def test_defaults_when_pagination_params_omitted(self) -> None:
        serializer = MCPSessionListQuerySerializer(data={})
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["limit"] == MCP_SESSION_LIST_DEFAULT_LIMIT
        assert serializer.validated_data["offset"] == 0

    @parameterized.expand(
        [
            ("limit_at_cap", {"limit": MCP_SESSION_LIST_MAX_LIMIT}, True, None),
            ("limit_over_cap", {"limit": MCP_SESSION_LIST_MAX_LIMIT + 1}, False, "limit"),
            ("limit_below_min", {"limit": 0}, False, "limit"),
            ("offset_at_min", {"offset": 0}, True, None),
            ("offset_negative", {"offset": -1}, False, "offset"),
        ]
    )
    def test_pagination_bounds(
        self, _name: str, data: dict[str, int], expected_valid: bool, error_field: str | None
    ) -> None:
        serializer = MCPSessionListQuerySerializer(data=data)
        assert serializer.is_valid() is expected_valid, serializer.errors
        if error_field is not None:
            assert error_field in serializer.errors


class TestMCPAnalyticsCrossTeamIsolation(_MCPAnalyticsTeamScopedTestMixin, APIBaseTest):
    """Team A must never reach Team B's submissions. Now that the submission endpoints are
    reachable by anyone inside the mcp-analytics flag (no longer staff-only), pin the tenant
    boundary: another team's rows never appear in this team's list, and a user who is not a
    member of another team's org is denied when hitting that team's URL.
    """

    def setUp(self) -> None:
        super().setUp()
        # The mcp-analytics feature flag is enabled for the whole test by the mixin's setUp.
        # A team in a different organization that self.user is NOT a member of.
        self.other_org = Organization.objects.create(name="other-org")
        self.other_team = Team.objects.create(organization=self.other_org, name="other-team")

        self.other_feedback = MCPAnalyticsSubmission.objects.create(
            team=self.other_team,
            created_by=self.user,
            kind=MCPAnalyticsSubmission.Kind.FEEDBACK,
            goal="team B goal",
            summary="Team B feedback — must not leak",
        )
        self.other_missing_capability = MCPAnalyticsSubmission.objects.create(
            team=self.other_team,
            created_by=self.user,
            kind=MCPAnalyticsSubmission.Kind.MISSING_CAPABILITY,
            goal="team B goal",
            summary="Team B missing capability — must not leak",
            blocked=False,
        )

    @parameterized.expand(
        [
            ("feedback", "feedback/", "Team B feedback — must not leak"),
            ("missing_capabilities", "missing_capabilities/", "Team B missing capability — must not leak"),
        ]
    )
    def test_other_teams_submissions_never_appear_in_own_list(self, _name: str, path: str, leaked: str) -> None:
        response = self.client.get(f"/api/environments/{self.team.id}/mcp_analytics/{path}")

        assert response.status_code == status.HTTP_200_OK
        summaries = [entry["summary"] for entry in response.json()["results"]]
        assert leaked not in summaries
        assert summaries == []

    @parameterized.expand(
        [
            ("feedback_list", "get", "feedback/", None),
            ("missing_capability_list", "get", "missing_capabilities/", None),
            (
                "feedback_create",
                "post",
                "feedback/",
                {"goal": "understand usage", "feedback": "Need clearer results"},
            ),
            (
                "missing_capability_create",
                "post",
                "missing_capabilities/",
                {"goal": "debug surveys", "missing_capability": "Need an eligibility explainer"},
            ),
        ]
    )
    def test_cannot_reach_another_orgs_team_endpoint(
        self, _name: str, method: str, path: str, payload: dict[str, str] | None
    ) -> None:
        request = getattr(self.client, method)
        response = request(f"/api/environments/{self.other_team.id}/mcp_analytics/{path}", payload, format="json")

        # Not a member of the other org's team: the request is rejected before any data is read.
        assert response.status_code in (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND)

    def test_creating_in_own_team_does_not_touch_other_team(self) -> None:
        self.client.post(
            f"/api/environments/{self.team.id}/mcp_analytics/feedback/",
            {"goal": "understand usage", "feedback": "My team's feedback"},
            format="json",
        )

        # The other team's submission count is untouched by writes to this team.
        assert MCPAnalyticsSubmission.objects.filter(team=self.other_team).count() == 2
        assert MCPAnalyticsSubmission.objects.filter(team=self.team).count() == 1


class TestMCPAnalyticsPersonalAPIKeyAccess(_MCPAnalyticsTeamScopedTestMixin, APIBaseTest):
    """The submission endpoints are now reachable by programmatic callers (Personal API
    Keys / OAuth) via the mcp_analytics scope — the previous INTERNAL lock blocked that
    entirely. Pin the scope mapping: the right scope works, the wrong/missing scope 403s.
    The default test client uses force_login and skips the scope check, so this must drive
    a real PAK to exercise the production auth path.
    """

    def _auth_with_pak(self, scopes: list[str]) -> None:
        key = self.create_personal_api_key_with_scopes(scopes)
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {key}")

    def test_read_scope_can_list_submissions(self) -> None:
        self._auth_with_pak(["mcp_analytics:read"])
        response = self.client.get(f"/api/environments/{self.team.id}/mcp_analytics/feedback/")
        assert response.status_code == status.HTTP_200_OK, response.content

    def test_write_scope_can_create_submission(self) -> None:
        self._auth_with_pak(["mcp_analytics:write"])
        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_analytics/feedback/",
            {"goal": "understand usage", "feedback": "Need clearer results"},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.content

    def test_read_scope_cannot_create_submission(self) -> None:
        self._auth_with_pak(["mcp_analytics:read"])
        response = self.client.post(
            f"/api/environments/{self.team.id}/mcp_analytics/feedback/",
            {"goal": "understand usage", "feedback": "Need clearer results"},
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content

    @parameterized.expand(
        [
            ("list", "get", "feedback/", None),
            (
                "create",
                "post",
                "feedback/",
                {"goal": "understand usage", "feedback": "Need clearer results"},
            ),
        ]
    )
    def test_missing_scope_is_forbidden(
        self, _name: str, method: str, path: str, payload: dict[str, str] | None
    ) -> None:
        self._auth_with_pak(["insight:read"])
        request = getattr(self.client, method)
        response = request(f"/api/environments/{self.team.id}/mcp_analytics/{path}", payload, format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
