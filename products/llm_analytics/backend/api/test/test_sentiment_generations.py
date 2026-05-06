from datetime import UTC, datetime
from typing import Any, cast

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from rest_framework import status


class TestSentimentGenerationsEndpoint(APIBaseTest):
    URL: str = ""

    def setUp(self) -> None:
        super().setUp()
        self.URL = f"/api/environments/{self.team.id}/llm_analytics/sentiment/generations/"

    def _make_response(self, rows: list[list[Any]]) -> MagicMock:
        response = MagicMock()
        response.results = rows
        return response

    def _preflight_row(
        self,
        uuid: str = "uuid-1",
        trace_id: str = "trace-1",
        model: str = "gpt-4",
        distinct_id: str = "person-1",
        ts_max: Any = "2026-04-27T07:00:00+00:00",
        ts_min: Any = "2026-04-27T06:50:00+00:00",
    ) -> list[Any]:
        return [uuid, trace_id, model, distinct_id, ts_max, ts_min]

    @patch("products.llm_analytics.backend.api.sentiment.execute_with_ai_events_fallback")
    @patch("products.llm_analytics.backend.api.sentiment.execute_hogql_query")
    def test_returns_rows_in_tuple_order(self, mock_preflight: MagicMock, mock_heavy: MagicMock) -> None:
        mock_preflight.return_value = self._make_response(
            [
                self._preflight_row(
                    uuid="uuid-1",
                    trace_id="trace-1",
                    model="gpt-4",
                    distinct_id="person-1",
                    ts_max="2026-04-27T07:00:00+00:00",
                    ts_min="2026-04-27T06:50:00+00:00",
                ),
            ]
        )
        mock_heavy.return_value = self._make_response([["trace-1", '[{"role":"user","content":"hi"}]']])

        response = self.client.post(
            self.URL,
            {"filters": {"dateRange": {"date_from": "-7d", "date_to": None}, "properties": []}},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body == {
            "results": [
                [
                    "uuid-1",
                    "trace-1",
                    '[{"role":"user","content":"hi"}]',
                    "gpt-4",
                    "person-1",
                    "2026-04-27T07:00:00+00:00",
                    "2026-04-27T06:50:00+00:00",
                ]
            ]
        }
        assert mock_preflight.call_args.kwargs["query_type"] == "LLMSentimentGenerationsTraceIdResolve"
        assert mock_heavy.call_args.kwargs["query_type"] == "LLMSentimentGenerations"

    @patch("products.llm_analytics.backend.api.sentiment.execute_with_ai_events_fallback")
    @patch("products.llm_analytics.backend.api.sentiment.execute_hogql_query")
    def test_empty_filters_payload_is_accepted(self, mock_preflight: MagicMock, mock_heavy: MagicMock) -> None:
        mock_preflight.return_value = self._make_response([])

        response = self.client.post(self.URL, {}, content_type="application/json")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"results": []}
        assert mock_heavy.call_count == 0

    @patch("products.llm_analytics.backend.api.sentiment.execute_with_ai_events_fallback")
    @patch("products.llm_analytics.backend.api.sentiment.execute_hogql_query")
    def test_invalid_filters_returns_400(self, mock_preflight: MagicMock, mock_heavy: MagicMock) -> None:
        response = self.client.post(
            self.URL,
            {"filters": {"filterTestAccounts": "this should be a bool"}},
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert mock_preflight.call_count == 0
        assert mock_heavy.call_count == 0

    @patch("products.llm_analytics.backend.api.sentiment.execute_with_ai_events_fallback")
    @patch("products.llm_analytics.backend.api.sentiment.execute_hogql_query")
    def test_empty_preflight_skips_heavy_query(self, mock_preflight: MagicMock, mock_heavy: MagicMock) -> None:
        mock_preflight.return_value = self._make_response([])

        response = self.client.post(self.URL, {"filters": {}}, content_type="application/json")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"results": []}
        assert mock_heavy.call_count == 0

    @patch("products.llm_analytics.backend.api.sentiment.execute_with_ai_events_fallback")
    @patch("products.llm_analytics.backend.api.sentiment.execute_hogql_query")
    def test_preflight_failure_returns_500(self, mock_preflight: MagicMock, mock_heavy: MagicMock) -> None:
        mock_preflight.side_effect = RuntimeError("clickhouse boom")

        response = self.client.post(self.URL, {"filters": {}}, content_type="application/json")
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert mock_heavy.call_count == 0

    @patch("products.llm_analytics.backend.api.sentiment.execute_with_ai_events_fallback")
    @patch("products.llm_analytics.backend.api.sentiment.execute_hogql_query")
    def test_heavy_failure_returns_500(self, mock_preflight: MagicMock, mock_heavy: MagicMock) -> None:
        mock_preflight.return_value = self._make_response([self._preflight_row()])
        mock_heavy.side_effect = RuntimeError("clickhouse boom")

        response = self.client.post(self.URL, {"filters": {}}, content_type="application/json")
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

    @patch("products.llm_analytics.backend.api.sentiment.execute_with_ai_events_fallback")
    @patch("products.llm_analytics.backend.api.sentiment.execute_hogql_query")
    def test_preflight_targets_events_and_heavy_targets_ai_events(
        self, mock_preflight: MagicMock, mock_heavy: MagicMock
    ) -> None:
        from posthog.hogql import ast

        mock_preflight.return_value = self._make_response(
            [
                self._preflight_row(
                    uuid="uuid-1",
                    trace_id="trace-1",
                    ts_max=datetime(2026, 4, 27, 7, 0, tzinfo=UTC),
                    ts_min=datetime(2026, 4, 27, 6, 50, tzinfo=UTC),
                ),
                self._preflight_row(
                    uuid="uuid-2",
                    trace_id="trace-2",
                    ts_max=datetime(2026, 4, 27, 6, 30, tzinfo=UTC),
                    ts_min=datetime(2026, 4, 27, 6, 0, tzinfo=UTC),
                ),
            ]
        )
        mock_heavy.return_value = self._make_response(
            [
                ["trace-1", '[{"role":"user","content":"hi"}]'],
                ["trace-2", '[{"role":"user","content":"hello"}]'],
            ]
        )

        response = self.client.post(self.URL, {"filters": {}}, content_type="application/json")
        assert response.status_code == status.HTTP_200_OK

        preflight_query = mock_preflight.call_args.kwargs["query"]
        preflight_select = cast(ast.SelectQuery, preflight_query)
        # nosemgrep: hogql-no-string-table-chain
        assert preflight_select.select_from.table.chain == ["events"]  # type: ignore[union-attr]

        heavy_query = mock_heavy.call_args.kwargs["query"]
        heavy_select = cast(ast.SelectQuery, heavy_query)
        # nosemgrep: hogql-no-string-table-chain
        assert heavy_select.select_from.table.chain == ["posthog", "ai_events"]  # type: ignore[union-attr]

        heavy_placeholders = mock_heavy.call_args.kwargs["placeholders"]
        trace_id_values = [c.value for c in heavy_placeholders["trace_ids"].exprs]
        assert trace_id_values == ["trace-1", "trace-2"]
        assert heavy_placeholders["ts_start"].value == datetime(2026, 4, 27, 6, 0, tzinfo=UTC)
        assert heavy_placeholders["ts_end"].value == datetime(2026, 4, 27, 7, 0, tzinfo=UTC)

    @patch("products.llm_analytics.backend.api.sentiment.execute_with_ai_events_fallback")
    @patch("products.llm_analytics.backend.api.sentiment.execute_hogql_query")
    def test_traces_without_heavy_match_get_null_ai_input(
        self, mock_preflight: MagicMock, mock_heavy: MagicMock
    ) -> None:
        mock_preflight.return_value = self._make_response(
            [
                self._preflight_row(uuid="uuid-1", trace_id="trace-1"),
                self._preflight_row(uuid="uuid-2", trace_id="trace-2"),
            ]
        )
        mock_heavy.return_value = self._make_response([["trace-1", '[{"role":"user","content":"hi"}]']])

        response = self.client.post(self.URL, {"filters": {}}, content_type="application/json")
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert len(body["results"]) == 2
        assert body["results"][0][2] == '[{"role":"user","content":"hi"}]'
        assert body["results"][1][2] is None
