from datetime import UTC, datetime

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
from products.exports.backend.temporal.subscriptions.ai_subscription.spec_generator import (
    ReportWindow,
    compute_report_window,
)

_RP = "products.exports.backend.temporal.subscriptions.ai_subscription.report_pipeline"

# Fixed event time + window anchor so the [start, end) filter brackets the events deterministically
# (no wall-clock race) — the events sit squarely inside the computed window.
_EVENT_TS = datetime(2026, 6, 20, 12, 0, tzinfo=UTC)
_WINDOW_NOW = datetime(2026, 6, 25, 12, 0, tzinfo=UTC)


class TestAIReportPipelineIntegration(ClickhouseTestMixin, NonAtomicBaseTest):
    """Exercises the real plan -> execute -> synthesize wiring: only the two LLM boundaries (planner,
    synthesis) are mocked; the planned HogQL runs against the test ClickHouse for real."""

    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        # Non-UTC project: proves the project-tz wall-clock window literal resolves to the right instant
        # when it flows through HogQL (which anchors a bare datetime to the project timezone).
        self.team.timezone = "Australia/Sydney"
        self.team.save()
        _create_person(team=self.team, distinct_ids=["u1"])
        for _ in range(3):
            _create_event(team=self.team, event="$pageview", distinct_id="u1", timestamp=_EVENT_TS)
        _create_event(team=self.team, event="signed_up", distinct_id="u1", timestamp=_EVENT_TS)
        flush_persons_and_events()

    def _window(self) -> ReportWindow:
        return compute_report_window(self.team, last_successful_delivery_at=None, now=_WINDOW_NOW, window_days=7)

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
        # --- happy path: planned HogQL (with the real window-filter literals) runs for real ---
        # The query copies the project-tz wall-clock bounds the way the planner is instructed to. If the
        # literal failed to parse or resolved to the wrong instant, the in-window events would drop out
        # and the assertions below would fail — this is the regression guard for the window filter itself.
        window = self._window()
        mock_bep.return_value = self._spec(
            f"SELECT event, count() AS c FROM events "
            f"WHERE timestamp >= toDateTime('{window.start_literal}') AND timestamp < toDateTime('{window.end_literal}') "
            f"GROUP BY event ORDER BY c DESC"
        )
        captured = self._capture_synthesis(mock_chat, "# Report")

        report = await generate_ai_report(team=self.team, user=self.user, prompt="how many events", window=window)

        assert report.markdown == "# Report"
        assert "$pageview" in captured["human"]
        assert "signed_up" in captured["human"]

        # --- degrade path: invalid query produces a placeholder but the report still ships ---
        # fix LLM (also MaxChatOpenAI) returns a non-HogQLFix, so the step can't recover and degrades
        mock_chat.return_value.with_structured_output.return_value.invoke.return_value = "not a fix"
        mock_bep.return_value = self._spec("SELECT count() FROM a_table_that_does_not_exist")
        captured = self._capture_synthesis(mock_chat, "# Degraded report")

        report = await generate_ai_report(team=self.team, user=self.user, prompt="x", window=self._window())

        assert "Query failed to run" in captured["human"]
        # Every query failed, so the delivered report leads with the deterministic failure notice
        # (prepended to the synthesis output) instead of a confident-looking but empty report.
        assert "could not be generated" in report.markdown
        assert "# Degraded report" in report.markdown
        # The degraded step's generated HogQL + error type are captured for persistence/debugging.
        assert any(not d.ok and d.error_type for d in report.diagnostics)
