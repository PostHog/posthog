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


class _WindowPipelineHelpers:
    """Shared spec/synthesis-capture helpers for the window integration tests. Distinct scenarios live
    in distinct classes rather than methods: NonAtomicBaseTest doesn't roll back Postgres between
    methods in a class, so per-method org/membership creates collide."""

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


class TestAIReportPipelineIntegration(_WindowPipelineHelpers, ClickhouseTestMixin, NonAtomicBaseTest):
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

    # Combined into a single test method: NonAtomicBaseTest doesn't roll back Postgres state
    # between test methods in the same class, so per-method org/membership creates collide.
    # Three scenarios in one test keep that isolation while covering the happy, degrade, and
    # first-ever-per-user flows.
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

        # --- first-ever-per-user subquery (the planner's first-occurrence recipe) runs for real ---
        # Guards that the FROM-subquery + min/argMin pattern we instruct the planner to emit for
        # "first-ever per user" is valid, executable HogQL — if it ever stops parsing, this fails
        # instead of silently degrading every such metric to a placeholder in production. The outer
        # filter uses the window literals (not now() - INTERVAL) to match what the planner now emits
        # and to keep the assertion deterministic against the fixed-timestamp events.
        mock_bep.return_value = self._spec(
            "SELECT first_event AS first_event, count() AS first_time_users "
            "FROM (SELECT distinct_id, min(timestamp) AS first_seen, argMin(event, timestamp) AS first_event "
            "FROM events GROUP BY distinct_id) "
            f"WHERE first_seen >= toDateTime('{window.start_literal}') AND first_seen < toDateTime('{window.end_literal}') "
            "GROUP BY first_event ORDER BY first_time_users DESC LIMIT 50"
        )
        captured = self._capture_synthesis(mock_chat, "# First occurrence report")

        report = await generate_ai_report(team=self.team, user=self.user, prompt="first ever", window=window)

        assert report.markdown == "# First occurrence report"
        assert report.diagnostics and all(d.ok for d in report.diagnostics)


# Anchor scenario: a prior successful delivery, with one event before it and one after. The window
# start must follow the delivery (not now - window_days), so the pre-delivery event is filtered out
# by the real ClickHouse query while the post-delivery one survives.
_ANCHOR_LAST_DELIVERY = datetime(2026, 6, 22, 12, 0, tzinfo=UTC)
_ANCHOR_NOW = datetime(2026, 6, 25, 12, 0, tzinfo=UTC)
_PRE_ANCHOR_TS = datetime(2026, 6, 20, 12, 0, tzinfo=UTC)
_POST_ANCHOR_TS = datetime(2026, 6, 23, 12, 0, tzinfo=UTC)


class TestAIReportWindowAnchor(_WindowPipelineHelpers, ClickhouseTestMixin, NonAtomicBaseTest):
    """The gap-free "since last send" anchor, proven end-to-end through real ClickHouse: with a prior
    delivery set, the window is [last_delivery, now), so a query copying those literals excludes events
    that fired before the delivery and includes those after. A regression that ignored the anchor (or
    resolved the literal to the wrong instant) would leak the pre-delivery event into the report."""

    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        # Non-UTC project, same as the sibling class: the anchor literal is project-tz wall clock, so
        # this also proves the anchor instant survives the tz round-trip through HogQL.
        self.team.timezone = "Australia/Sydney"
        self.team.save()
        _create_person(team=self.team, distinct_ids=["u1"])
        _create_event(team=self.team, event="pre_delivery", distinct_id="u1", timestamp=_PRE_ANCHOR_TS)
        _create_event(team=self.team, event="post_delivery", distinct_id="u1", timestamp=_POST_ANCHOR_TS)
        flush_persons_and_events()

    @patch(f"{_RP}.MaxChatOpenAI")
    @patch(f"{_RP}.build_enriched_prompt")
    async def test_window_start_anchors_to_last_delivery_and_excludes_earlier_events(
        self, mock_bep: MagicMock, mock_chat: MagicMock
    ) -> None:
        window = compute_report_window(
            self.team, last_successful_delivery_at=_ANCHOR_LAST_DELIVERY, now=_ANCHOR_NOW, window_days=7
        )
        # Window follows the delivery gap (3 days), not the 7-day cadence — the anchor, not window_days.
        assert window.start == _ANCHOR_LAST_DELIVERY

        mock_bep.return_value = self._spec(
            f"SELECT event, count() AS c FROM events "
            f"WHERE timestamp >= toDateTime('{window.start_literal}') AND timestamp < toDateTime('{window.end_literal}') "
            f"GROUP BY event ORDER BY c DESC"
        )
        captured = self._capture_synthesis(mock_chat, "# Report")

        report = await generate_ai_report(team=self.team, user=self.user, prompt="how many events", window=window)

        assert report.markdown == "# Report"
        # post_delivery fired inside [last_delivery, now); pre_delivery fired before the anchor and the
        # real filter drops it — the proof the anchor is applied and the literal resolves to the right instant.
        assert "post_delivery" in captured["human"]
        assert "pre_delivery" not in captured["human"]
