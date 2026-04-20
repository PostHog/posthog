import json
import uuid

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from asgiref.sync import async_to_sync
from parameterized import parameterized

from products.llm_analytics.backend.tools.run_hog_eval_test import RunHogEvalTestTool


def _make_event(
    ai_input=None,
    ai_output_choices=None,
    event_type="$ai_generation",
):
    if ai_input is None:
        ai_input = [{"role": "user", "content": "Hello"}]
    if ai_output_choices is None:
        ai_output_choices = [{"message": {"role": "assistant", "content": "Hi there!"}}]
    return [
        str(uuid.uuid4()),
        event_type,
        json.dumps(
            {
                "$ai_input": ai_input,
                "$ai_output_choices": ai_output_choices,
                "$ai_model": "gpt-4",
            }
        ),
        "test-user",
    ]


def _run_tool(tool, **kwargs):
    return async_to_sync(tool._arun_impl)(**kwargs)


class TestRunHogEvalTestTool(BaseTest):
    def _make_tool(self):
        return RunHogEvalTestTool(team=self.team, user=self.user)

    @parameterized.expand(
        [
            ("valid_return_true", "return true;", True),
            ("valid_return_false", "return false;", False),
            ("with_print", "print('checking'); return true;", True),
            ("length_check", "return length(output) > 0;", True),
        ]
    )
    @patch("products.llm_analytics.backend.tools.run_hog_eval_test.execute_hogql_query")
    def test_compilation_and_execution(self, _name, source, expected_verdict, mock_query):
        mock_response = MagicMock()
        mock_response.results = [_make_event()]
        mock_query.return_value = mock_response

        tool = self._make_tool()
        result, artifact = _run_tool(tool, source=source, sample_count=1)

        assert artifact is None
        if expected_verdict:
            assert "PASS" in result
        else:
            assert "FAIL" in result

    def test_compilation_error(self):
        tool = self._make_tool()
        result, artifact = _run_tool(tool, source="this is not valid hog {{{{", sample_count=1)

        assert "Compilation error" in result
        assert artifact is None

    @patch("products.llm_analytics.backend.tools.run_hog_eval_test.execute_hogql_query")
    def test_no_events_found(self, mock_query):
        mock_response = MagicMock()
        mock_response.results = []
        mock_query.return_value = mock_response

        tool = self._make_tool()
        result, artifact = _run_tool(tool, source="return true;", sample_count=3)

        assert "No recent AI events" in result
        assert artifact is None

    @patch("products.llm_analytics.backend.tools.run_hog_eval_test.execute_hogql_query")
    def test_runtime_error_handling(self, mock_query):
        mock_response = MagicMock()
        mock_response.results = [_make_event()]
        mock_query.return_value = mock_response

        tool = self._make_tool()
        result, artifact = _run_tool(tool, source="return properties.nonexistent.nested;", sample_count=1)

        assert artifact is None
        assert "Event" in result

    @patch("products.llm_analytics.backend.tools.run_hog_eval_test.execute_hogql_query")
    def test_result_formatting_includes_previews(self, mock_query):
        mock_response = MagicMock()
        mock_response.results = [
            _make_event(
                ai_input=[{"role": "user", "content": "What is PostHog?"}],
                ai_output_choices=[{"message": {"role": "assistant", "content": "PostHog is analytics."}}],
            )
        ]
        mock_query.return_value = mock_response

        tool = self._make_tool()
        result, artifact = _run_tool(tool, source="return true;", sample_count=1)

        assert "Input:" in result
        assert "Output:" in result
        assert "Result: PASS" in result

    @patch("products.llm_analytics.backend.tools.run_hog_eval_test.execute_hogql_query")
    def test_null_return_shows_na(self, mock_query):
        mock_response = MagicMock()
        mock_response.results = [_make_event()]
        mock_query.return_value = mock_response

        tool = self._make_tool()
        result, artifact = _run_tool(tool, source="return null;", sample_count=1)

        assert artifact is None
        assert "N/A" in result
        assert "ERROR" not in result

    @patch("products.llm_analytics.backend.tools.run_hog_eval_test.execute_hogql_query")
    def test_runtime_error_shows_error_not_na(self, mock_query):
        mock_response = MagicMock()
        mock_response.results = [_make_event()]
        mock_query.return_value = mock_response

        tool = self._make_tool()
        result, artifact = _run_tool(tool, source="return 42;", sample_count=1)

        assert artifact is None
        assert "Result: ERROR" in result
        assert "Result: N/A" not in result

    @patch("products.llm_analytics.backend.tools.run_hog_eval_test.execute_hogql_query")
    def test_ai_metric_event_type(self, mock_query):
        mock_response = MagicMock()
        event_row = [
            str(uuid.uuid4()),
            "$ai_metric",
            json.dumps({"$ai_input_state": "some input", "$ai_output_state": "some output"}),
            "test-user",
        ]
        mock_response.results = [event_row]
        mock_query.return_value = mock_response

        tool = self._make_tool()
        result, artifact = _run_tool(tool, source="return true;", sample_count=1)

        assert "PASS" in result
        assert "$ai_metric" in result
