from datetime import UTC, datetime
from types import SimpleNamespace

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from products.signals.backend.artefact_schemas import VerificationQuery, VerificationQueryResult
from products.signals.backend.report_verification import (
    ask_jev_for_verdict,
    execute_verification_query,
    verification_snapshot_matches,
)


def _verification() -> VerificationQuery:
    return VerificationQuery(
        description="Measures failed imports and import attempts.",
        query=(
            "SELECT countIf(event = 'failed') AS failures, count() AS attempts FROM events "
            "WHERE timestamp >= {window_start} AND timestamp < {window_end}"
        ),
        snapshot_result=VerificationQueryResult(
            window_start=datetime(2026, 6, 1, tzinfo=UTC),
            window_end=datetime(2026, 6, 8, tzinfo=UTC),
            columns=["failures", "attempts"],
            rows=[[12, 40]],
        ),
        success_criteria="Attempts continue and failures fall to zero.",
        inconclusive_conditions=["No import attempts occur."],
        mcp_commands=["execute-sql"],
        documentation_urls=["https://posthog.com/docs/sql"],
    )


class TestReportVerification(SimpleTestCase):
    @patch("products.signals.backend.report_verification.execute_hogql_query")
    def test_current_window_is_bound_as_constants_and_result_is_bounded(self, execute: MagicMock) -> None:
        execute.return_value = SimpleNamespace(columns=["failures", "attempts"], results=[[0, 55]])
        start = datetime(2026, 7, 1, tzinfo=UTC)
        end = datetime(2026, 7, 8, tzinfo=UTC)

        result = execute_verification_query(_verification(), team=object(), window_start=start, window_end=end)

        assert result.rows == [[0, 55]]
        assert execute.call_args.kwargs["placeholders"]["window_start"].value == start
        assert execute.call_args.kwargs["placeholders"]["window_end"].value == end

    @patch("products.signals.backend.report_verification.execute_hogql_query")
    def test_authored_snapshot_must_match_a_server_side_rerun(self, execute: MagicMock) -> None:
        execute.return_value = SimpleNamespace(columns=["failures", "attempts"], results=[[12, 40]])

        assert verification_snapshot_matches(_verification(), team=object())

        execute.return_value = SimpleNamespace(columns=["failures", "attempts"], results=[[11, 40]])
        assert not verification_snapshot_matches(_verification(), team=object())

    @override_settings(
        TYPESAFE_API_KEY="secret",
        TYPESAFE_BASE_URL="https://api.typesafe.ai",
        TYPESAFE_DEFAULT_MODEL="jev-latest",
    )
    @patch("products.signals.backend.report_verification.typesafe_request")
    def test_jev_receives_the_snapshot_as_snapshot_and_new_rows_as_current(self, request: MagicMock) -> None:
        response = MagicMock()
        response.json.return_value = {
            "model": "jev-1.13.0",
            "answers": {
                "issue_status": {
                    "choice": "solved",
                    "confidence": 0.82,
                    "probabilities": {"solved": 0.91, "not_solved": 0.04, "insufficient_evidence": 0.05},
                }
            },
        }
        request.return_value = response
        current = VerificationQueryResult(
            window_start=datetime(2026, 7, 1, tzinfo=UTC),
            window_end=datetime(2026, 7, 8, tzinfo=UTC),
            columns=["failures", "attempts"],
            rows=[[0, 55]],
        )

        decision, model = ask_jev_for_verdict(_verification(), current)

        state = request.call_args.kwargs["json"]["state"]
        assert state["snapshot_result"]["rows"] == [[12, 40]]
        assert state["current_result"]["rows"] == [[0, 55]]
        assert decision.choice == "solved"
        assert decision.confidence == 0.82
        assert model == "jev-1.13.0"
