"""Tests for `LLMAnalyticsOfflineEvaluationsViewSet.experiment_items`.

The view replaces the previous frontend HogQL query at
`offlineEvaluationsLogic.ts::loadSelectedExperimentData`. It serves the
heavy-prop read path (`input` / `output` for offline experiment items)
through `execute_with_ai_events_fallback` so the rollout flag, events
fallback, and `ai_query_source` tagging all apply.
"""

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from rest_framework import status


class TestOfflineEvaluationItemsEndpoint(APIBaseTest):
    URL: str = ""

    def setUp(self) -> None:
        super().setUp()
        self.URL = f"/api/environments/{self.team.id}/llm_analytics/offline_evaluations/experiment_items/"

    def _make_resolver_response(self, rows: list[list]) -> MagicMock:
        response = MagicMock()
        response.results = rows
        return response

    @patch("products.llm_analytics.backend.api.offline_evaluations.execute_with_ai_events_fallback")
    def test_missing_experiment_id_returns_400(self, mock_resolver: MagicMock) -> None:
        response = self.client.post(self.URL, {}, content_type="application/json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert mock_resolver.call_count == 0

    @patch("products.llm_analytics.backend.api.offline_evaluations.execute_with_ai_events_fallback")
    def test_empty_experiment_id_returns_400(self, mock_resolver: MagicMock) -> None:
        # Distinct from the missing case — an empty string can pass through some
        # serializers; the request-level validation should still reject it
        # before any DB hit.
        response = self.client.post(self.URL, {"experiment_id": ""}, content_type="application/json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert mock_resolver.call_count == 0

    @patch("products.llm_analytics.backend.api.offline_evaluations.execute_with_ai_events_fallback")
    def test_returns_rows_for_experiment(self, mock_resolver: MagicMock) -> None:
        rows = [["item-1"] + [None] * 17]  # 18 columns total per the SQL projection
        mock_resolver.return_value = self._make_resolver_response(rows)

        response = self.client.post(
            self.URL,
            {"experiment_id": "exp-1"},
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"results": rows}

    @patch("products.llm_analytics.backend.api.offline_evaluations.execute_with_ai_events_fallback")
    def test_omitted_dates_inline_as_null_guards(self, mock_resolver: MagicMock) -> None:
        """When date_from/date_to are not passed, the SQL's
        `{date_from_is_null}` / `{date_to_is_null}` placeholders inline as
        True at parse time, short-circuiting the parseDateTimeBestEffort
        branch. Placeholders are inlined at parse time (not at resolver
        execute time) to dodge a HogQL placeholder-bytecode quirk; the
        endpoint comment explains the rationale."""
        from posthog.hogql import ast
        from posthog.hogql.visitor import TraversingVisitor

        mock_resolver.return_value = self._make_resolver_response([])
        response = self.client.post(
            self.URL,
            {"experiment_id": "exp-1"},
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_200_OK

        # Resolver receives an empty placeholders dict (everything was inlined).
        assert mock_resolver.call_args.kwargs["placeholders"] == {}

        query = mock_resolver.call_args.kwargs["query"]
        true_constants: list[ast.Constant] = []

        class _BoolCounter(TraversingVisitor):
            def visit_constant(self, node: ast.Constant) -> None:
                if isinstance(node.value, bool) and node.value is True:
                    true_constants.append(node)
                super().visit_constant(node)

        _BoolCounter().visit(query)
        # The two `is_null` guards both inline as True when no dates passed.
        assert len(true_constants) >= 2

    @patch("products.llm_analytics.backend.api.offline_evaluations.execute_with_ai_events_fallback")
    def test_provided_dates_are_inlined_into_query(self, mock_resolver: MagicMock) -> None:
        from posthog.hogql import ast
        from posthog.hogql.visitor import TraversingVisitor

        mock_resolver.return_value = self._make_resolver_response([])

        response = self.client.post(
            self.URL,
            {
                "experiment_id": "exp-1",
                "date_from": "2026-04-01T00:00:00Z",
                "date_to": "2026-04-30T00:00:00Z",
            },
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert mock_resolver.call_args.kwargs["placeholders"] == {}

        query = mock_resolver.call_args.kwargs["query"]
        string_constants: list[str] = []

        class _StringCollector(TraversingVisitor):
            def visit_constant(self, node: ast.Constant) -> None:
                if isinstance(node.value, str):
                    string_constants.append(node.value)
                super().visit_constant(node)

        _StringCollector().visit(query)
        assert "exp-1" in string_constants
        assert "2026-04-01T00:00:00Z" in string_constants
        assert "2026-04-30T00:00:00Z" in string_constants

    @patch("products.llm_analytics.backend.api.offline_evaluations.execute_with_ai_events_fallback")
    def test_query_reads_heavy_columns_from_ai_events(self, mock_resolver: MagicMock) -> None:
        """The whole point of routing through this endpoint is that `input`
        and `output` come off the dedicated `ai_events` columns, not from
        `events.properties.$ai_*` (which are NULL post-strip). The SQL
        wraps the FROM in a subquery to dodge a HogQL placeholder-bytecode
        quirk, so we check via the AST walker rather than `select_from.table`
        on the outer SELECT."""
        from posthog.hogql import ast
        from posthog.hogql.visitor import TraversingVisitor

        mock_resolver.return_value = self._make_resolver_response([])

        response = self.client.post(
            self.URL,
            {"experiment_id": "exp-1"},
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_200_OK

        query = mock_resolver.call_args.kwargs["query"]
        ai_events_seen = []

        class _AiEventsFinder(TraversingVisitor):
            def visit_join_expr(self, node: ast.JoinExpr) -> None:
                if isinstance(node.table, ast.Field):
                    # nosemgrep: hogql-no-string-table-chain
                    if node.table.chain == ["posthog", "ai_events"]:
                        ai_events_seen.append(node)
                super().visit_join_expr(node)

        _AiEventsFinder().visit(query)
        assert ai_events_seen, "expected the SQL to read FROM posthog.ai_events"

    @patch("products.llm_analytics.backend.api.offline_evaluations.execute_with_ai_events_fallback")
    def test_resolver_failure_returns_500(self, mock_resolver: MagicMock) -> None:
        mock_resolver.side_effect = RuntimeError("clickhouse boom")

        response = self.client.post(
            self.URL,
            {"experiment_id": "exp-1"},
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
