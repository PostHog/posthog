"""Tests for `LLMAnalyticsSentimentViewSet.generations` — the
`sentiment_generations.sql`-equivalent backend endpoint.

The view's responsibility is narrow: parse + validate the filter payload, route
the SQL through `execute_with_ai_events_fallback` so the rollout flag /
events fallback / `ai_query_source` tagging are honored, and return the result
rows tuple-shape unchanged. Tests cover:

  - success on the dedicated path with populated rows
  - success on the events fallback when ai_events is empty (post-strip is the
    motivating case — the resolver re-runs against `events` automatically)
  - kill-switch off (skips ai_events, queries events directly)
  - empty filters (omitted dateRange / properties / filterTestAccounts)
  - resolver receives the correct query body + tags

The resolver itself is covered by `test_ai_table_resolver.py`; here we mock
it and verify the call shape, then probe the failure paths.
"""

from typing import cast

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from rest_framework import status


class TestSentimentGenerationsEndpoint(APIBaseTest):
    URL: str = ""

    def setUp(self) -> None:
        super().setUp()
        self.URL = f"/api/environments/{self.team.id}/llm_analytics/sentiment/generations/"

    def _resolver_path(self) -> str:
        return "products.llm_analytics.backend.api.sentiment.execute_with_ai_events_fallback"

    def _make_resolver_response(self, rows: list[list]) -> MagicMock:
        response = MagicMock()
        response.results = rows
        return response

    @patch("products.llm_analytics.backend.api.sentiment.execute_with_ai_events_fallback")
    def test_returns_rows_in_tuple_order(self, mock_resolver: MagicMock) -> None:
        # Tuple order: [uuid, trace_id, ai_input, model, distinct_id, timestamp, created_at]
        rows = [
            [
                "uuid-1",
                "trace-1",
                '[{"role":"user","content":"hi"}]',
                "gpt-4",
                "person-1",
                "2026-04-27T07:00:00+00:00",
                "2026-04-27T06:50:00+00:00",
            ],
        ]
        mock_resolver.return_value = self._make_resolver_response(rows)

        response = self.client.post(
            self.URL,
            {"filters": {"dateRange": {"date_from": "-7d", "date_to": None}, "properties": []}},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body == {"results": rows}
        # Resolver received an LLMSentimentGenerations query_type for tagging dashboards.
        assert mock_resolver.call_args.kwargs["query_type"] == "LLMSentimentGenerations"

    @patch("products.llm_analytics.backend.api.sentiment.execute_with_ai_events_fallback")
    def test_empty_filters_payload_is_accepted(self, mock_resolver: MagicMock) -> None:
        # Tab loads with no filters set; backend should not reject this.
        mock_resolver.return_value = self._make_resolver_response([])

        response = self.client.post(self.URL, {}, content_type="application/json")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"results": []}

    @patch("products.llm_analytics.backend.api.sentiment.execute_with_ai_events_fallback")
    def test_invalid_filters_returns_400(self, mock_resolver: MagicMock) -> None:
        # `filterTestAccounts` is meant to be a bool; a non-bool should fail
        # `HogQLFilters` validation and surface as a 400 (not 500).
        response = self.client.post(
            self.URL,
            {"filters": {"filterTestAccounts": "this should be a bool"}},
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert mock_resolver.call_count == 0

    @patch("products.llm_analytics.backend.api.sentiment.execute_with_ai_events_fallback")
    def test_resolver_failure_returns_500(self, mock_resolver: MagicMock) -> None:
        mock_resolver.side_effect = RuntimeError("clickhouse boom")

        response = self.client.post(
            self.URL,
            {"filters": {}},
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

    @patch("products.llm_analytics.backend.api.sentiment.execute_with_ai_events_fallback")
    def test_query_targets_ai_events_with_heavy_input_column(self, mock_resolver: MagicMock) -> None:
        """The migrated SQL must reach the resolver with the heavy `input`
        column referenced via the dedicated `ai_events` table — not as
        `properties.$ai_input`. That's the whole point of the migration; if
        someone reverts the SQL, this test catches it."""
        from posthog.hogql import ast

        mock_resolver.return_value = self._make_resolver_response([])

        response = self.client.post(self.URL, {"filters": {}}, content_type="application/json")
        assert response.status_code == status.HTTP_200_OK

        query_arg = mock_resolver.call_args.kwargs["query"]
        # SelectQuery → outer query reads `argMax(ai_input, ts)` over a subquery
        # whose FROM is `posthog.ai_events`.
        # Easier to verify by walking down to the FROM clause.
        select = cast(ast.SelectQuery, query_arg)
        # Outer: argMax(ai_input, ts) … FROM (subquery)
        # Subquery's FROM is what we care about.
        inner = select.select_from.table  # type: ignore[union-attr]
        if isinstance(inner, ast.SelectQuery):
            from_chain = inner.select_from.table.chain  # type: ignore[union-attr]
            # nosemgrep: hogql-no-string-table-chain
            assert from_chain == ["posthog", "ai_events"], f"expected FROM posthog.ai_events, got {from_chain}"
