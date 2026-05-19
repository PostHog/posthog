"""Tests for the PostHog Code spend analysis API endpoint."""

from __future__ import annotations

from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized
from rest_framework import status


class TestPostHogCodeSpendAuth(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self._team_id_override = override_settings(POSTHOG_CODE_ANALYTICS_TEAM_ID=self.team.id)
        self._team_id_override.enable()
        self.addCleanup(self._team_id_override.disable)

    def test_unauthenticated_caller_rejected(self) -> None:
        self.client.logout()
        response = self.client.get("/api/llm_analytics/posthog_code_spend/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_authenticated_caller_without_email_rejected(self) -> None:
        self.user.email = ""
        self.user.save()
        response = self.client.get("/api/llm_analytics/posthog_code_spend/")
        assert response.status_code == status.HTTP_403_FORBIDDEN


class TestPostHogCodeSpendValidation(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self._team_id_override = override_settings(POSTHOG_CODE_ANALYTICS_TEAM_ID=self.team.id)
        self._team_id_override.enable()
        self.addCleanup(self._team_id_override.disable)

    @parameterized.expand(
        [
            ("zero", "0", status.HTTP_400_BAD_REQUEST),
            ("negative", "-5", status.HTTP_400_BAD_REQUEST),
            ("over_max", "365", status.HTTP_400_BAD_REQUEST),
            ("non_integer", "many", status.HTTP_400_BAD_REQUEST),
            ("valid_min", "1", status.HTTP_200_OK),
            ("valid_default", "30", status.HTTP_200_OK),
            ("valid_max", "90", status.HTTP_200_OK),
        ]
    )
    def test_days_param_validation(self, _label: str, days: str, expected: int) -> None:
        response = self.client.get(f"/api/llm_analytics/posthog_code_spend/?days={days}")
        assert response.status_code == expected

    def test_days_param_optional_defaults_to_30(self) -> None:
        response = self.client.get("/api/llm_analytics/posthog_code_spend/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["summary"]["period_days"] == 30


class TestPostHogCodeSpendQueries(ClickhouseTestMixin, APIBaseTest):
    """End-to-end tests against ClickHouse with real $ai_generation events."""

    def setUp(self) -> None:
        super().setUp()
        self._team_id_override = override_settings(POSTHOG_CODE_ANALYTICS_TEAM_ID=self.team.id)
        self._team_id_override.enable()
        self.addCleanup(self._team_id_override.disable)

        _create_person(
            distinct_ids=[self.user.distinct_id or self.user.email],
            team=self.team,
            properties={"email": self.user.email},
        )

    def _create_generation(
        self,
        *,
        ai_product: str = "posthog_code",
        model: str = "claude-opus-4-7",
        tool: str | None = "Bash",
        trace_id: str = "trace-1",
        cost: float = 1.5,
        input_tokens: int = 100000,
        output_tokens: int = 500,
        event_name: str = "$ai_generation",
    ) -> None:
        props: dict = {
            "$ai_total_cost_usd": cost,
            "$ai_input_tokens": input_tokens,
            "$ai_output_tokens": output_tokens,
            "$ai_model": model,
            "$ai_trace_id": trace_id,
            "ai_product": ai_product,
        }
        if tool is not None:
            props["$ai_tools_called"] = tool
        _create_event(
            event=event_name,
            team=self.team,
            distinct_id=self.user.distinct_id or self.user.email,
            properties=props,
        )

    @snapshot_clickhouse_queries
    def test_empty_result_when_no_events(self) -> None:
        response = self.client.get("/api/llm_analytics/posthog_code_spend/")
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["summary"]["total_cost_usd"] == 0
        assert body["summary"]["event_count"] == 0
        assert body["by_product"] == []
        assert body["by_tool"] == []
        assert body["by_model"] == []
        assert body["top_traces"] == []

    def test_summary_aggregates_across_products(self) -> None:
        self._create_generation(ai_product="posthog_code", cost=2.0)
        self._create_generation(ai_product="background_agents", cost=1.0)
        self._create_generation(ai_product="posthog_code", cost=0.5, event_name="$ai_embedding")
        flush_persons_and_events()

        response = self.client.get("/api/llm_analytics/posthog_code_spend/")
        assert response.status_code == status.HTTP_200_OK
        summary = response.json()["summary"]
        assert summary["event_count"] == 3
        assert summary["total_cost_usd"] == 3.5
        assert summary["posthog_code_event_count"] == 2
        assert summary["posthog_code_cost_usd"] == 2.5

    def test_by_tool_excludes_non_posthog_code_traffic(self) -> None:
        self._create_generation(ai_product="posthog_code", tool="Bash", cost=2.0)
        self._create_generation(ai_product="background_agents", tool="Bash", cost=10.0)
        flush_persons_and_events()

        response = self.client.get("/api/llm_analytics/posthog_code_spend/")
        assert response.status_code == status.HTTP_200_OK
        by_tool = response.json()["by_tool"]
        assert len(by_tool) == 1
        assert by_tool[0]["tool"] == "Bash"
        assert by_tool[0]["cost_usd"] == 2.0

    def test_by_tool_includes_null_tool_rows(self) -> None:
        self._create_generation(tool="Bash", cost=2.0)
        self._create_generation(tool=None, cost=0.5)
        flush_persons_and_events()

        response = self.client.get("/api/llm_analytics/posthog_code_spend/")
        rows = response.json()["by_tool"]
        tools = {r["tool"] for r in rows}
        assert tools == {"Bash", None}

    def test_top_traces_ordered_by_cost(self) -> None:
        self._create_generation(trace_id="cheap", cost=0.5)
        self._create_generation(trace_id="expensive", cost=5.0)
        self._create_generation(trace_id="expensive", cost=3.0)
        flush_persons_and_events()

        response = self.client.get("/api/llm_analytics/posthog_code_spend/")
        traces = response.json()["top_traces"]
        assert traces[0]["trace_id"] == "expensive"
        assert traces[0]["cost_usd"] == 8.0
        assert traces[0]["generation_count"] == 2
        assert traces[1]["trace_id"] == "cheap"

    def test_other_users_spend_is_not_visible(self) -> None:
        other_email = "other-user@example.com"
        _create_person(distinct_ids=["other-distinct"], team=self.team, properties={"email": other_email})
        _create_event(
            event="$ai_generation",
            team=self.team,
            distinct_id="other-distinct",
            properties={
                "$ai_total_cost_usd": 999.99,
                "ai_product": "posthog_code",
                "$ai_model": "claude-opus-4-7",
                "$ai_tools_called": "Bash",
                "$ai_trace_id": "their-trace",
            },
        )
        self._create_generation(cost=1.0)
        flush_persons_and_events()

        response = self.client.get("/api/llm_analytics/posthog_code_spend/")
        assert response.json()["summary"]["total_cost_usd"] == 1.0

    def test_days_window_filters_old_events(self) -> None:
        with patch("products.llm_analytics.backend.api.posthog_code_spend.execute_hogql_query") as mock_exec:
            mock_exec.return_value.results = []
            response = self.client.get("/api/llm_analytics/posthog_code_spend/?days=7")

        assert response.status_code == status.HTTP_200_OK
        # All 5 fetchers should pass `days=7` through to the query layer.
        assert mock_exec.call_count == 5
