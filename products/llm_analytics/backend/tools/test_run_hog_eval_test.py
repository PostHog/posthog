import json
import uuid

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from asgiref.sync import async_to_sync
from parameterized import parameterized

from posthog.hogql_queries.ai.utils import HEAVY_COLUMN_NAMES

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
        *(None,) * len(HEAVY_COLUMN_NAMES),
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
    @patch("products.llm_analytics.backend.tools.run_hog_eval_test.execute_with_ai_events_fallback")
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

    @patch("products.llm_analytics.backend.tools.run_hog_eval_test.execute_with_ai_events_fallback")
    def test_no_events_found(self, mock_query):
        mock_response = MagicMock()
        mock_response.results = []
        mock_query.return_value = mock_response

        tool = self._make_tool()
        result, artifact = _run_tool(tool, source="return true;", sample_count=3)

        assert "No recent AI events" in result
        assert artifact is None

    @patch("products.llm_analytics.backend.tools.run_hog_eval_test.execute_with_ai_events_fallback")
    def test_runtime_error_handling(self, mock_query):
        mock_response = MagicMock()
        mock_response.results = [_make_event()]
        mock_query.return_value = mock_response

        tool = self._make_tool()
        result, artifact = _run_tool(tool, source="return properties.nonexistent.nested;", sample_count=1)

        assert artifact is None
        assert "Event" in result

    @patch("products.llm_analytics.backend.tools.run_hog_eval_test.execute_with_ai_events_fallback")
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

    @patch("products.llm_analytics.backend.tools.run_hog_eval_test.execute_with_ai_events_fallback")
    def test_null_return_shows_na(self, mock_query):
        mock_response = MagicMock()
        mock_response.results = [_make_event()]
        mock_query.return_value = mock_response

        tool = self._make_tool()
        result, artifact = _run_tool(tool, source="return null;", sample_count=1)

        assert artifact is None
        assert "N/A" in result
        assert "ERROR" not in result

    @patch("products.llm_analytics.backend.tools.run_hog_eval_test.execute_with_ai_events_fallback")
    def test_runtime_error_shows_error_not_na(self, mock_query):
        mock_response = MagicMock()
        mock_response.results = [_make_event()]
        mock_query.return_value = mock_response

        tool = self._make_tool()
        result, artifact = _run_tool(tool, source="return 42;", sample_count=1)

        assert artifact is None
        assert "Result: ERROR" in result
        assert "Result: N/A" not in result

    @patch("products.llm_analytics.backend.tools.run_hog_eval_test.execute_with_ai_events_fallback")
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

    @patch("products.llm_analytics.backend.tools.run_hog_eval_test.execute_with_ai_events_fallback")
    def test_heavy_column_remerge_for_stripped_event(self, mock_query):
        """Post-strip rows have empty `properties.$ai_input` on `events`, but
        the dedicated `ai_events` table carries the value in the `input`
        column. The tool must re-merge those native columns back into
        `properties` so the Hog body can read `properties.$ai_input` as
        before. This test simulates the post-strip shape coming back from
        the resolver."""
        from posthog.hogql_queries.ai.utils import HEAVY_COLUMN_NAMES

        # row[2]: stripped properties (no $ai_input).
        # row[4..9]: native heavy column values, in HEAVY_COLUMN_NAMES order
        #   ("input", "output", "output_choices", "input_state", "output_state", "tools").
        stripped_props = json.dumps({"$ai_model": "gpt-4o"})
        heavy_input = '[{"role":"user","content":"recovered from native column"}]'
        row = [
            str(uuid.uuid4()),
            "$ai_generation",
            stripped_props,
            "test-user",
            heavy_input,  # input
            None,  # output
            None,  # output_choices
            None,  # input_state
            None,  # output_state
            None,  # tools
        ]
        # Sanity: row layout matches what the source expects.
        assert len(row) == 4 + len(HEAVY_COLUMN_NAMES)
        mock_query.return_value = MagicMock(results=[row])

        tool = self._make_tool()
        # Hog body reads `properties.$ai_input` — this must be populated post-merge.
        result, _artifact = _run_tool(
            tool,
            source="return properties.$ai_input != null;",
            sample_count=1,
        )

        assert "Result: PASS" in result, f"expected PASS after heavy-merge, got: {result}"

    @patch("products.llm_analytics.backend.tools.run_hog_eval_test.execute_with_ai_events_fallback")
    def test_query_targets_ai_events(self, mock_query):
        """The constructed SelectQuery must target `posthog.ai_events` — otherwise
        the heavy column slots in the projection are NULL on the events table."""
        from posthog.hogql import ast

        mock_query.return_value = MagicMock(results=[])
        tool = self._make_tool()
        _run_tool(tool, source="return true;", sample_count=1)

        kwargs = mock_query.call_args.kwargs
        select = kwargs["query"]
        assert isinstance(select, ast.SelectQuery)
        from_chain = select.select_from.table.chain  # type: ignore[union-attr]
        # nosemgrep: hogql-no-string-table-chain
        assert from_chain == ["posthog", "ai_events"]
