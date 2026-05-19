"""Tests for the personal LLM spend analysis API endpoint."""

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

ENDPOINT = "/api/llm_analytics/personal_spend/"


def _by_product(rows: list[dict], product: str | None) -> dict | None:
    return next((r for r in rows if r["product"] == product), None)


class TestPersonalSpendAuth(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self._team_id_override = override_settings(LLM_ANALYTICS_INTERNAL_TEAM_ID=self.team.id)
        self._team_id_override.enable()
        self.addCleanup(self._team_id_override.disable)

    def test_unauthenticated_caller_rejected(self) -> None:
        self.client.logout()
        response = self.client.get(ENDPOINT)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_authenticated_caller_without_email_rejected(self) -> None:
        self.user.email = ""
        self.user.save()
        response = self.client.get(ENDPOINT)
        assert response.status_code == status.HTTP_403_FORBIDDEN


class TestPersonalSpendValidation(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self._team_id_override = override_settings(LLM_ANALYTICS_INTERNAL_TEAM_ID=self.team.id)
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
        response = self.client.get(f"{ENDPOINT}?days={days}")
        assert response.status_code == expected

    def test_days_param_optional_defaults_to_30(self) -> None:
        response = self.client.get(ENDPOINT)
        assert response.status_code == status.HTTP_200_OK
        summary = response.json()["summary"]
        assert summary["period_days"] == 30
        assert summary["product"] is None

    def test_product_too_long_rejected(self) -> None:
        response = self.client.get(f"{ENDPOINT}?product={'x' * 100}")
        assert response.status_code == status.HTTP_400_BAD_REQUEST


class TestPersonalSpendQueries(ClickhouseTestMixin, APIBaseTest):
    """End-to-end tests against ClickHouse with real $ai_generation events."""

    def setUp(self) -> None:
        super().setUp()
        self._team_id_override = override_settings(LLM_ANALYTICS_INTERNAL_TEAM_ID=self.team.id)
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
        response = self.client.get(ENDPOINT)
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["summary"]["total_cost_usd"] == 0
        assert body["summary"]["event_count"] == 0
        assert body["summary"]["scoped_cost_usd"] == 0
        assert body["summary"]["scoped_event_count"] == 0
        assert body["by_product"] == []
        assert body["by_tool"] == []
        assert body["by_model"] == []
        assert body["top_traces"] == []

    def test_unfiltered_summary_aggregates_across_products(self) -> None:
        self._create_generation(ai_product="posthog_code", cost=2.0)
        self._create_generation(ai_product="background_agents", cost=1.0)
        self._create_generation(ai_product="posthog_code", cost=0.5, event_name="$ai_embedding")
        flush_persons_and_events()

        response = self.client.get(ENDPOINT)
        body = response.json()
        summary = body["summary"]
        assert summary["product"] is None
        assert summary["event_count"] == 3
        assert summary["total_cost_usd"] == 3.5
        # Without a product filter, scoped totals match the cross-product totals.
        assert summary["scoped_event_count"] == 3
        assert summary["scoped_cost_usd"] == 3.5
        # by_product carries each slice for the caller to pick out.
        code_row = _by_product(body["by_product"], "posthog_code")
        assert code_row is not None
        assert code_row["cost_usd"] == 2.5

    def test_product_filter_scopes_summary_and_breakdowns(self) -> None:
        self._create_generation(ai_product="posthog_code", tool="Bash", cost=2.0)
        self._create_generation(ai_product="background_agents", tool="Bash", cost=10.0)
        flush_persons_and_events()

        response = self.client.get(f"{ENDPOINT}?product=posthog_code")
        body = response.json()

        # Summary still reports cross-product totals; scoped_* is filtered.
        assert body["summary"]["product"] == "posthog_code"
        assert body["summary"]["total_cost_usd"] == 12.0
        assert body["summary"]["scoped_cost_usd"] == 2.0

        # by_tool is scoped to the filter — only the posthog_code Bash row.
        tool_rows = body["by_tool"]
        assert len(tool_rows) == 1
        assert tool_rows[0]["cost_usd"] == 2.0

        # by_product is always cross-product, regardless of the filter.
        assert {r["product"] for r in body["by_product"]} == {"posthog_code", "background_agents"}

    def test_by_tool_includes_null_tool_rows(self) -> None:
        self._create_generation(tool="Bash", cost=2.0)
        self._create_generation(tool=None, cost=0.5)
        flush_persons_and_events()

        response = self.client.get(f"{ENDPOINT}?product=posthog_code")
        tools = {r["tool"] for r in response.json()["by_tool"]}
        assert tools == {"Bash", None}

    def test_by_tool_splits_comma_separated_tools(self) -> None:
        # One generation that calls Bash and Read should contribute to both rows.
        self._create_generation(tool="Bash,Read", cost=2.0, trace_id="multi")
        # One single-tool generation that also touches Bash, plus a single-tool Read.
        self._create_generation(tool="Bash", cost=1.0, trace_id="bash-only")
        self._create_generation(tool="Read", cost=0.5, trace_id="read-only")
        flush_persons_and_events()

        response = self.client.get(f"{ENDPOINT}?product=posthog_code")
        rows = {r["tool"]: r for r in response.json()["by_tool"]}
        assert set(rows) == {"Bash", "Read"}
        # Bash row picks up both the Bash-only generation and the Bash,Read generation.
        assert rows["Bash"]["generation_count"] == 2
        assert rows["Bash"]["cost_usd"] == 3.0
        # Read row picks up both the Read-only generation and the Bash,Read generation.
        assert rows["Read"]["generation_count"] == 2
        assert rows["Read"]["cost_usd"] == 2.5
        # Scoped total stays $3.50 — the multi-tool generation is only counted once there.
        assert response.json()["summary"]["scoped_cost_usd"] == 3.5

    def test_top_traces_ordered_by_cost(self) -> None:
        self._create_generation(trace_id="cheap", cost=0.5)
        self._create_generation(trace_id="expensive", cost=5.0)
        self._create_generation(trace_id="expensive", cost=3.0)
        flush_persons_and_events()

        response = self.client.get(ENDPOINT)
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

        response = self.client.get(ENDPOINT)
        assert response.json()["summary"]["total_cost_usd"] == 1.0

    def test_days_window_passes_through_to_query_layer(self) -> None:
        with patch("products.llm_analytics.backend.api.personal_spend.execute_hogql_query") as mock_exec:
            mock_exec.return_value.results = []
            response = self.client.get(f"{ENDPOINT}?days=7")

        assert response.status_code == status.HTTP_200_OK
        # All 5 fetchers should run once.
        assert mock_exec.call_count == 5

    def test_second_call_serves_from_cache(self) -> None:
        with patch("products.llm_analytics.backend.api.personal_spend.execute_hogql_query") as mock_exec:
            mock_exec.return_value.results = []
            self.client.get(ENDPOINT)
            first = mock_exec.call_count
            self.client.get(ENDPOINT)
            assert mock_exec.call_count == first

    def test_refresh_bypasses_cache(self) -> None:
        with patch("products.llm_analytics.backend.api.personal_spend.execute_hogql_query") as mock_exec:
            mock_exec.return_value.results = []
            self.client.get(ENDPOINT)
            first = mock_exec.call_count
            self.client.get(f"{ENDPOINT}?refresh=true")
            assert mock_exec.call_count == first * 2

    def test_cache_key_includes_days(self) -> None:
        with patch("products.llm_analytics.backend.api.personal_spend.execute_hogql_query") as mock_exec:
            mock_exec.return_value.results = []
            self.client.get(f"{ENDPOINT}?days=7")
            first = mock_exec.call_count
            self.client.get(f"{ENDPOINT}?days=30")
            assert mock_exec.call_count == first * 2

    def test_cache_key_includes_product(self) -> None:
        with patch("products.llm_analytics.backend.api.personal_spend.execute_hogql_query") as mock_exec:
            mock_exec.return_value.results = []
            self.client.get(ENDPOINT)
            first = mock_exec.call_count
            self.client.get(f"{ENDPOINT}?product=posthog_code")
            assert mock_exec.call_count == first * 2
