import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from products.streamlit_apps.backend.logic.bridge import execute_bridge_query


class TestExecuteBridgeQuery(BaseTest):
    @patch("products.streamlit_apps.backend.logic.bridge.execute_hogql_query")
    def test_returns_whitelisted_response(self, mock_execute):
        """Only the columns/results/types fields are surfaced — clickhouse SQL,
        hogql AST, internal timings, and modifiers must NOT leak through."""
        response = MagicMock()
        response.model_dump.return_value = {
            "results": [[1, "hello"]],
            "columns": ["id", "name"],
            "clickhouse": "SELECT ...",
            "hogql": "SELECT ...",
            "timings": {"total": 0.1},
            "modifiers": {},
            "types": [["Int64"], ["String"]],
        }
        mock_execute.return_value = response

        result = execute_bridge_query(query="SELECT 1", team_id=self.team.id)

        assert result["results"] == [[1, "hello"]]
        assert result["columns"] == ["id", "name"]
        assert result["types"] == [["Int64"], ["String"]]
        assert "clickhouse" not in result
        assert "hogql" not in result
        assert "timings" not in result
        assert "modifiers" not in result

    @patch("products.streamlit_apps.backend.logic.bridge.execute_hogql_query")
    def test_passes_query_and_team(self, mock_execute):
        response = MagicMock()
        response.model_dump.return_value = {"results": [], "columns": []}
        mock_execute.return_value = response

        execute_bridge_query(query="SELECT event FROM events", team_id=self.team.id)

        mock_execute.assert_called_once()
        call_kwargs = mock_execute.call_args
        assert call_kwargs.kwargs["query"] == "SELECT event FROM events"
        assert call_kwargs.kwargs["team"].id == self.team.id

    def test_invalid_team_raises(self):
        with pytest.raises(Exception):
            execute_bridge_query(query="SELECT 1", team_id=999999)
