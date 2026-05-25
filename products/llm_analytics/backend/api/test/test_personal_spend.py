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

ENDPOINT = "/api/llm_analytics/@me/spend/"


def _by_product(rows: list[dict], product: str | None) -> dict | None:
    return next((r for r in rows if r["product"] == product), None)


class TestPersonalSpendEuRedirect(APIBaseTest):
    """Pure unit test of the EU redirect view — does not depend on URL conf for EU."""

    def test_eu_redirect_view_preserves_query_string(self) -> None:
        from django.test import RequestFactory

        from products.llm_analytics.backend.api.personal_spend import personal_spend_eu_redirect

        factory = RequestFactory()
        request = factory.get("/api/llm_analytics/@me/spend/", data={"date_from": "-7d", "product": "posthog_code"})
        response = personal_spend_eu_redirect(request)

        assert response.status_code == status.HTTP_302_FOUND
        assert response["Location"].startswith("https://us.posthog.com/api/llm_analytics/@me/spend/")
        assert "date_from=-7d" in response["Location"]
        assert "product=posthog_code" in response["Location"]

    def test_eu_redirect_view_strips_unknown_params(self) -> None:
        from django.test import RequestFactory

        from products.llm_analytics.backend.api.personal_spend import personal_spend_eu_redirect

        factory = RequestFactory()
        request = factory.get(
            "/api/llm_analytics/@me/spend/",
            data={"date_from": "-7d", "evil": "https://attacker.example/", "fragment": "#"},
        )
        response = personal_spend_eu_redirect(request)

        assert response.status_code == status.HTTP_302_FOUND
        # Target host stays hardcoded.
        assert response["Location"].startswith("https://us.posthog.com/")
        # Allowed param preserved.
        assert "date_from=-7d" in response["Location"]
        # Unknown params dropped (allowlist enforced).
        assert "evil" not in response["Location"]
        assert "fragment" not in response["Location"]
        assert "attacker.example" not in response["Location"]


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
            ("nonsense", "wibble", status.HTTP_400_BAD_REQUEST),
            ("over_max_window", "-365d", status.HTTP_400_BAD_REQUEST),
            ("valid_relative_short", "-1d", status.HTTP_200_OK),
            ("valid_relative_default", "-30d", status.HTTP_200_OK),
            ("valid_relative_max", "-90d", status.HTTP_200_OK),
        ]
    )
    def test_date_from_param_validation(self, _label: str, date_from: str, expected: int) -> None:
        response = self.client.get(f"{ENDPOINT}?date_from={date_from}")
        assert response.status_code == expected

    def test_date_params_optional_default_to_last_30_days(self) -> None:
        response = self.client.get(ENDPOINT)
        assert response.status_code == status.HTTP_200_OK
        summary = response.json()["summary"]
        assert summary["product"] is None
        # date_from / date_to are returned as ISO strings.
        assert summary["date_from"] is not None
        assert summary["date_to"] is not None

    def test_date_to_before_date_from_rejected(self) -> None:
        response = self.client.get(f"{ENDPOINT}?date_from=-7d&date_to=-30d")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_product_too_long_rejected(self) -> None:
        response = self.client.get(f"{ENDPOINT}?product={'x' * 100}")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @parameterized.expand(
        [
            ("zero", "0", status.HTTP_400_BAD_REQUEST),
            ("negative", "-1", status.HTTP_400_BAD_REQUEST),
            ("over_max", "1000", status.HTTP_400_BAD_REQUEST),
            ("valid_min", "1", status.HTTP_200_OK),
            ("valid_default", "50", status.HTTP_200_OK),
            ("valid_max", "200", status.HTTP_200_OK),
        ]
    )
    def test_limit_param_validation(self, _label: str, limit: str, expected: int) -> None:
        response = self.client.get(f"{ENDPOINT}?limit={limit}")
        assert response.status_code == expected


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
        flush_persons_and_events()

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
        assert body["by_product"] == {"items": [], "truncated": False}
        assert body["by_tool"] == {"items": [], "truncated": False}
        assert body["by_model"] == {"items": [], "truncated": False}
        assert body["top_traces"] == {"items": [], "truncated": False}

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
        code_row = _by_product(body["by_product"]["items"], "posthog_code")
        assert code_row is not None
        assert code_row["cost_usd"] == 2.5
        assert body["by_product"]["truncated"] is False

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
        tool_rows = body["by_tool"]["items"]
        assert len(tool_rows) == 1
        assert tool_rows[0]["cost_usd"] == 2.0
        assert tool_rows[0]["share_of_scoped"] == 1.0

        # by_product is always cross-product, regardless of the filter.
        assert {r["product"] for r in body["by_product"]["items"]} == {"posthog_code", "background_agents"}

    def test_by_tool_includes_null_tool_rows(self) -> None:
        self._create_generation(tool="Bash", cost=2.0)
        self._create_generation(tool=None, cost=0.5)
        flush_persons_and_events()

        response = self.client.get(f"{ENDPOINT}?product=posthog_code")
        tools = {r["tool"] for r in response.json()["by_tool"]["items"]}
        assert tools == {"Bash", None}

    def test_by_tool_splits_comma_separated_tools(self) -> None:
        # One generation that calls Bash and Read should contribute to both rows.
        self._create_generation(tool="Bash,Read", cost=2.0, trace_id="multi")
        # One single-tool generation that also touches Bash, plus a single-tool Read.
        self._create_generation(tool="Bash", cost=1.0, trace_id="bash-only")
        self._create_generation(tool="Read", cost=0.5, trace_id="read-only")
        flush_persons_and_events()

        response = self.client.get(f"{ENDPOINT}?product=posthog_code")
        rows = {r["tool"]: r for r in response.json()["by_tool"]["items"]}
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
        traces = response.json()["top_traces"]["items"]
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

    def test_date_window_passes_through_to_query_layer(self) -> None:
        with patch("products.llm_analytics.backend.api.personal_spend.execute_with_ai_events_fallback") as mock_exec:
            mock_exec.return_value.results = []
            response = self.client.get(f"{ENDPOINT}?date_from=-7d")

        assert response.status_code == status.HTTP_200_OK
        # All 5 fetchers should run once.
        assert mock_exec.call_count == 5

    def test_second_call_serves_from_cache(self) -> None:
        with patch("products.llm_analytics.backend.api.personal_spend.execute_with_ai_events_fallback") as mock_exec:
            mock_exec.return_value.results = []
            self.client.get(ENDPOINT)
            first = mock_exec.call_count
            self.client.get(ENDPOINT)
            assert mock_exec.call_count == first

    def test_refresh_bypasses_cache(self) -> None:
        with patch("products.llm_analytics.backend.api.personal_spend.execute_with_ai_events_fallback") as mock_exec:
            mock_exec.return_value.results = []
            self.client.get(ENDPOINT)
            first = mock_exec.call_count
            self.client.get(f"{ENDPOINT}?refresh=true")
            assert mock_exec.call_count == first * 2

    def test_cache_key_includes_date_from(self) -> None:
        with patch("products.llm_analytics.backend.api.personal_spend.execute_with_ai_events_fallback") as mock_exec:
            mock_exec.return_value.results = []
            self.client.get(f"{ENDPOINT}?date_from=-7d")
            first = mock_exec.call_count
            self.client.get(f"{ENDPOINT}?date_from=-30d")
            assert mock_exec.call_count == first * 2

    def test_cache_key_includes_product(self) -> None:
        with patch("products.llm_analytics.backend.api.personal_spend.execute_with_ai_events_fallback") as mock_exec:
            mock_exec.return_value.results = []
            self.client.get(ENDPOINT)
            first = mock_exec.call_count
            self.client.get(f"{ENDPOINT}?product=posthog_code")
            assert mock_exec.call_count == first * 2

    def test_cache_key_includes_limit(self) -> None:
        with patch("products.llm_analytics.backend.api.personal_spend.execute_with_ai_events_fallback") as mock_exec:
            mock_exec.return_value.results = []
            self.client.get(f"{ENDPOINT}?limit=10")
            first = mock_exec.call_count
            self.client.get(f"{ENDPOINT}?limit=50")
            assert mock_exec.call_count == first * 2

    def test_by_product_truncated_when_more_than_limit_products(self) -> None:
        # Three products, ask for limit=2 → top 2 returned, truncated=True.
        self._create_generation(ai_product="a", cost=3.0)
        self._create_generation(ai_product="b", cost=2.0)
        self._create_generation(ai_product="c", cost=1.0)
        flush_persons_and_events()

        response = self.client.get(f"{ENDPOINT}?limit=2")
        by_product = response.json()["by_product"]
        assert len(by_product["items"]) == 2
        assert by_product["truncated"] is True

    def test_by_tool_share_of_scoped(self) -> None:
        self._create_generation(tool="Bash", cost=2.0)
        self._create_generation(tool="Read", cost=2.0)
        flush_persons_and_events()

        response = self.client.get(f"{ENDPOINT}?product=posthog_code")
        rows = {r["tool"]: r for r in response.json()["by_tool"]["items"]}
        # Each tool drove half of the scoped spend.
        assert rows["Bash"]["share_of_scoped"] == 0.5
        assert rows["Read"]["share_of_scoped"] == 0.5
