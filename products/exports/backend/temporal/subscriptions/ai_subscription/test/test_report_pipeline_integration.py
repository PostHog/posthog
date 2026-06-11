from posthog.test.base import (
    ClickhouseTestMixin,
    NonAtomicBaseTest,
    _create_event,
    _create_person,
    flush_persons_and_events,
)
from unittest.mock import MagicMock, patch

from products.exports.backend.temporal.subscriptions.ai_subscription.report_pipeline import generate_ai_report
from products.exports.backend.temporal.subscriptions.ai_subscription.schemas import (
    EnrichedPromptSpec,
    QueryPlan,
    QueryPlanStep,
)

_RP = "products.exports.backend.temporal.subscriptions.ai_subscription.report_pipeline"


class TestAIReportPipelineIntegration(ClickhouseTestMixin, NonAtomicBaseTest):
    """Exercises the real plan -> execute -> synthesize wiring: only the two LLM boundaries (planner,
    synthesis) are mocked; the planned HogQL runs against the test ClickHouse for real."""

    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        _create_person(team=self.team, distinct_ids=["u1"])
        for _ in range(3):
            _create_event(team=self.team, event="$pageview", distinct_id="u1")
        _create_event(team=self.team, event="signed_up", distinct_id="u1")
        flush_persons_and_events()

    def _spec(self, hogql: str) -> EnrichedPromptSpec:
        return EnrichedPromptSpec(
            cleaned_prompt="how many events",
            context_blob="ctx",
            plan=QueryPlan(
                overall_intent="count events",
                steps=[QueryPlanStep(description="Event counts", hogql=hogql)],
            ),
        )

    def _capture_synthesis(self, mock_chat: MagicMock, report: str) -> dict[str, str]:
        captured: dict[str, str] = {}

        def _invoke(messages: list) -> MagicMock:
            captured["human"] = messages[1][1]
            return MagicMock(content=report)

        mock_chat.return_value.invoke.side_effect = _invoke
        return captured

    # Combined into a single test method: NonAtomicBaseTest doesn't roll back Postgres state
    # between test methods in the same class, so per-method org/membership creates collide.
    # Two assertions in one test gives reliable isolation while keeping both flows covered.
    @patch(f"{_RP}.MaxChatOpenAI")
    @patch(f"{_RP}.build_enriched_prompt")
    async def test_real_hogql_flows_into_synthesis_and_invalid_hogql_degrades(
        self, mock_bep: MagicMock, mock_chat: MagicMock
    ) -> None:
        # --- happy path: planned HogQL runs for real, results reach synthesis ---
        mock_bep.return_value = self._spec("SELECT event, count() AS c FROM events GROUP BY event ORDER BY c DESC")
        captured = self._capture_synthesis(mock_chat, "# Report")

        report = await generate_ai_report(team=self.team, user=self.user, prompt="how many events", window_days=7)

        assert report.markdown == "# Report"
        assert "$pageview" in captured["human"]
        assert "signed_up" in captured["human"]

        # --- degrade path: invalid query produces a placeholder but the report still ships ---
        # fix LLM (also MaxChatOpenAI) returns a non-HogQLFix, so the step can't recover and degrades
        mock_chat.return_value.with_structured_output.return_value.invoke.return_value = "not a fix"
        mock_bep.return_value = self._spec("SELECT count() FROM a_table_that_does_not_exist")
        captured = self._capture_synthesis(mock_chat, "# Degraded report")

        report = await generate_ai_report(team=self.team, user=self.user, prompt="x", window_days=7)

        assert report.markdown == "# Degraded report"
        assert "Query failed to run" in captured["human"]
        # The degraded step's generated HogQL + error type are captured for persistence/debugging.
        assert any(not d.ok and d.error_type for d in report.diagnostics)
