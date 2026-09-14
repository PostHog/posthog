import logging
from datetime import datetime

import pytest

from products.signals.backend.report_charts import ReportChart
from products.signals.backend.report_generation.research import (
    FixVerificationOutput,
    ReportPresentationOutput,
    SignalFinding,
    _render_previous_metrics_context,
    _render_signal_for_research,
    build_fix_verification_prompt,
    build_actionability_prompt,
    build_initial_research_prompt,
    build_report_presentation_prompt,
    build_signal_investigation_prompt,
    build_supersede_prompt,
)
from products.signals.backend.report_metrics import (
    DEFAULT_LIVE_METRIC_DATE_FROM,
    MAX_LIVE_METRIC_QUERY_POINTS,
    MAX_LIVE_METRIC_QUERY_SERIES,
    ReportMetric,
)
from products.signals.backend.temporal.types import SignalData
from products.signals.backend.test.report_metric_test_fixtures import trends_metric_query


def _make_signal(extra: dict) -> SignalData:
    return SignalData(
        signal_id="sig-1",
        content="Thing is broken",
        source_product="conversations",
        source_type="ticket",
        source_id="t-1",
        weight=1.0,
        timestamp=datetime(2026, 4, 1, 12, 0, 0),
        extra=extra,
    )


class TestRenderSignalForResearch:
    def test_renders_attached_images_with_author_prefix(self):
        signal = _make_signal(
            {
                "images": [
                    {"url": "https://media.posthog.com/a.png", "author": "customer"},
                    {"url": "https://media.posthog.com/b.png", "author": "team"},
                ]
            }
        )

        rendered = _render_signal_for_research(signal, index=1, total=1)

        assert (
            "- images: [customer] https://media.posthog.com/a.png, [team] https://media.posthog.com/b.png"
        ) in rendered

    @pytest.mark.parametrize(
        "extra",
        [
            {},
            {"images": []},
            {"images": None},
        ],
    )
    def test_omits_attached_images_line_when_empty_or_missing(self, extra):
        signal = _make_signal(extra)

        rendered = _render_signal_for_research(signal, index=1, total=1)

        assert "- images:" not in rendered

    def test_skips_image_entries_without_url(self):
        signal = _make_signal(
            {
                "images": [
                    {"url": "", "author": "customer"},
                    {"author": "team"},
                    {"url": "https://media.posthog.com/ok.png", "author": "customer"},
                ]
            }
        )

        rendered = _render_signal_for_research(signal, index=1, total=1)

        assert "- images: [customer] https://media.posthog.com/ok.png" in rendered
        assert "[team]" not in rendered


class TestBuildInitialResearchPrompt:
    @pytest.mark.parametrize(
        "has_bk, expected_present, extra_checks",
        [
            (True, True, ["business-knowledge-documents-search"]),
            (False, False, []),
        ],
    )
    def test_business_knowledge_block_presence(self, has_bk, expected_present, extra_checks):
        signal = _make_signal({})
        prompt = build_initial_research_prompt(signal, 1, has_business_knowledge=has_bk)
        assert ("## Business knowledge" in prompt) == expected_present
        for snippet in extra_checks:
            assert snippet in prompt

    def test_resolved_report_context_present_when_provided(self):
        signal = _make_signal({})
        prompt = build_initial_research_prompt(
            signal,
            1,
            resolved_report_title="fix(funnel): drop off after step 2",
            resolved_report_summary="Users were falling out of the funnel.",
        )
        assert "## Previously resolved report" in prompt
        assert "fix(funnel): drop off after step 2" in prompt
        assert "Users were falling out of the funnel." in prompt

    def test_resolved_report_context_absent_by_default(self):
        signal = _make_signal({})
        prompt = build_initial_research_prompt(signal, 1)
        assert "## Previously resolved report" not in prompt

    # The steering section is what carries a reviewer's dismissal reason into the stage that judges
    # whether to surface the topic again. A team that left no notes renders nothing, so a quiet
    # project pays no tokens for a heading with nothing under it.
    @pytest.mark.parametrize("steering_section", ["", "## Steering from this team\n\n- 2026-08-27: frozen"])
    def test_steering_section_rendered_verbatim_only_when_present(self, steering_section):
        signal = _make_signal({})
        prompt = build_initial_research_prompt(signal, 1, steering_section=steering_section)
        assert ("## Steering from this team" in prompt) == bool(steering_section)
        if steering_section:
            assert steering_section in prompt

    @pytest.mark.parametrize("has_previous_finding", [False, True])
    def test_uses_stable_finding_response_envelope(self, has_previous_finding):
        signal = _make_signal({})
        previous_finding = (
            SignalFinding(
                signal_id=signal.signal_id,
                relevant_code_paths=["example.py"],
                data_queried="Queried the relevant events.",
                verified=True,
            )
            if has_previous_finding
            else None
        )

        initial_prompt = build_initial_research_prompt(signal, 2, previous_finding=previous_finding)
        followup_prompt = build_signal_investigation_prompt(signal, 2, 2, previous_finding=previous_finding)

        for prompt in (initial_prompt, followup_prompt):
            assert '"previous_finding_correct"' in prompt
            assert '"finding"' in prompt
            assert "respond with a `SignalFinding` JSON object" not in prompt
        if not has_previous_finding:
            assert "There is no previous finding for this signal" in initial_prompt
            assert "There is no previous finding for this signal" in followup_prompt


class TestBuildFixVerificationPrompt:
    def test_is_a_final_step_based_on_completed_research(self):
        prompt = build_fix_verification_prompt()

        assert "As the final step" in prompt
        assert "Do not do more research in this turn" in prompt
        assert "Do not prescribe a resolution" in prompt
        assert "In `current_state`" in prompt
        assert "In `outcome`" in prompt
        assert "query, test, log search, replay, code review, or manual check" in prompt
        assert "What evidence to collect" in prompt
        assert "What result supports the conclusion" in prompt
        assert "What result is inconclusive" in prompt
        assert "Missing data, insufficient traffic, and failed checks are inconclusive" in prompt
        assert "Do not invent tool arguments, IDs, events, baselines, or numerical thresholds" in prompt
        assert '"current_state"' in prompt
        assert '"outcome"' in prompt

    def test_formats_plan_as_a_note_with_the_expected_headings(self):
        current_state = (
            'Run query-trends with {"kind":"TrendsQuery","dateRange":{"date_from":"-1h"},'
            '"interval":"hour","series":[{"kind":"EventsNode","event":"upload_failed","math":"total"},'
            '{"kind":"EventsNode","event":"upload_completed","math":"total"}]}. '
            "Any upload_failed events confirm that uploads still fail. No upload events is inconclusive."
        )
        outcome = (
            "Repeat the same query after the chosen resolution, once an hour of traffic is available. Use a window "
            "that excludes earlier data. Zero upload_failed events alongside "
            "upload_completed events supports recovery; any failure means the issue still occurs. "
            "No upload events or a failed query is inconclusive."
        )
        result = FixVerificationOutput(current_state=f" {current_state} ", outcome=f" {outcome} ")

        assert result.to_note().note == (
            f"## Verification plan\n\n"
            f"### Confirm the current state\n\n{current_state}\n\n"
            f"### Confirm the outcome\n\n{outcome}"
        )


def _make_chart() -> ReportChart:
    return ReportChart(
        chart_id="signups-drop",
        title="Daily signups",
        query={
            "kind": "InsightVizNode",
            "source": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "user_signed_up"}]},
        },
    )


class TestBuildReportPresentationPrompt:
    # Chart and metric rollouts are independent: a team can receive live impact measurements
    # without enabling free-form report charts, or vice versa.
    def test_chart_guidance_and_schema_field_only_present_when_enabled(self):
        off = build_report_presentation_prompt(2, charts_enabled=False)
        on = build_report_presentation_prompt(2, charts_enabled=True)
        assert "Attaching charts" not in off
        assert "Attaching charts" in on
        # The schema field is dropped when disabled and present when enabled.
        assert '"charts"' not in off
        assert '"charts"' in on

    def test_metric_guidance_and_schema_field_only_present_when_enabled(self):
        off = build_report_presentation_prompt(2, charts_enabled=True, metrics_enabled=False)
        on = build_report_presentation_prompt(2, charts_enabled=False, metrics_enabled=True)

        assert "Measuring impact" not in off
        assert '"metrics"' not in off
        assert f"at most {MAX_LIVE_METRIC_QUERY_POINTS} estimated interval points" not in off
        assert "Attaching charts" in off
        assert '"charts"' in off

        assert "Measuring impact" in on
        assert '"metrics"' in on
        assert (
            f'Default the query to `dateRange.date_from: "{DEFAULT_LIVE_METRIC_DATE_FROM}"` with `interval: "day"`'
            in on
        )
        assert "Do not author comparisons" in on
        assert f"at most {MAX_LIVE_METRIC_QUERY_POINTS} estimated interval points" in on
        assert "Every source series must be an `EventsNode` or `ActionsNode`" in on
        assert "Do not use a breakdown or compare mode on any report metric" in on
        assert "exactly one output series per query" in on
        assert f"up to {MAX_LIVE_METRIC_QUERY_SERIES} event/action source series as formula inputs" in on
        assert "exactly one formula output" in on
        assert "Consumers derive `BoldNumber`" in on
        assert "and `ActionsBar`" in on
        assert "bar or line response does not supply the whole-window total" in on
        assert "must set `aggregationAxisFormat` to exactly the same value" in on
        assert "Attaching charts" not in on
        assert '"charts"' not in on

    # A DataVisualizationNode carrying `display` but no `chartSettings` stores and validates
    # cleanly, then draws every row at a single x position instead of a series. The guidance is
    # the only thing that tells the agent to set the axes, so losing this line means every
    # SQL-backed chart the pipeline authors renders wrong in the reader's inbox with nothing
    # reporting a failure. The scout channel guards the same instruction in its own example.
    def test_chart_guidance_names_the_axes_a_sql_graph_needs(self):
        on = build_report_presentation_prompt(2, charts_enabled=True)
        assert "chartSettings.xAxis.column" in on
        assert "chartSettings.yAxis[].column" in on

    def test_previous_charts_context_only_rendered_when_enabled(self):
        chart = _make_chart()
        on = build_report_presentation_prompt(1, previous_charts=[chart], charts_enabled=True)
        off = build_report_presentation_prompt(1, previous_charts=[chart], charts_enabled=False)
        assert "Charts this report already shows" in on
        assert "signups-drop" in on
        assert "Charts this report already shows" not in off

    def test_previous_metric_context_omits_legacy_comparison(self):
        metric = ReportMetric.model_validate(
            {
                "metric_id": "affected-users",
                "title": "Affected users",
                "kind": "affected_users",
                "role": "primary",
                "value": 17,
                "value_at": "2026-08-29T12:00:00Z",
                "value_format": "count",
                "unit": "users",
                "query": trends_metric_query(series=[{"kind": "EventsNode", "event": "$exception", "math": "dau"}]),
                "comparison": {"value": 11, "label": "Previous period"},
            }
        )

        prompt = _render_previous_metrics_context([metric])

        assert '"comparison"' not in prompt
        assert "Previous period" not in prompt


class TestReportPresentationOutputCharts:
    # Title, summary, and charts arrive as one response, so a chart that fails validation used to
    # take the whole presentation step down and end the research run with no report.
    def test_a_malformed_chart_is_dropped_and_the_rest_of_the_response_survives(self):
        parsed = ReportPresentationOutput.model_validate(
            {
                "title": "fix(signups): Handle the drop",
                "summary": "Signups fell 60% over the week.",
                "charts": [
                    {
                        "chart_id": "signups-drop",
                        "title": "Daily signups",
                        "query": {"kind": "InsightVizNode", "source": {"kind": "TrendsQuery"}},
                    },
                    {"chart_id": "bare-trends", "title": "Wrong node", "query": {"kind": "TrendsQuery"}},
                ],
            }
        )

        assert parsed.title == "fix(signups): Handle the drop"
        assert [chart.chart_id for chart in parsed.charts] == ["signups-drop"]

    def test_the_dropped_chart_warning_names_the_rule_without_the_rejected_query(self, caplog):
        with caplog.at_level(logging.WARNING):
            ReportPresentationOutput.model_validate(
                {
                    "title": "fix(signups): Handle the drop",
                    "summary": "Signups fell 60% over the week.",
                    "charts": [
                        {
                            "chart_id": "leaky",
                            "title": "Wrong node",
                            "query": {"kind": "HogQLQuery", "query": "SELECT email FROM persons WHERE team='acme'"},
                        }
                    ],
                }
            )

        warning = "".join(record.getMessage() for record in caplog.records)
        # Pydantic renders the rejected input in the error's own text, so logging it would copy the
        # chart's query into application logs.
        assert "SELECT email" not in warning
        assert "acme" not in warning
        assert "query: value_error" in warning

    def test_a_response_whose_every_chart_is_malformed_still_yields_the_prose(self):
        parsed = ReportPresentationOutput.model_validate(
            {
                "title": "fix(signups): Handle the drop",
                "summary": "Signups fell 60% over the week.",
                "charts": [{"chart_id": "NOT A SLUG", "title": "Bad id", "query": {"kind": "InsightVizNode"}}],
            }
        )

        assert parsed.charts == []
        assert parsed.summary == "Signups fell 60% over the week."
class TestOwnPullRequestCarveOut:
    _PR = "https://github.com/PostHog/posthog/pull/7"

    def test_actionability_prompt_exempts_the_report_own_pr(self):
        # On a re-research the in-flight check finds the draft PR this report opened last pass. Read
        # as somebody else's work it makes the report already_addressed, and superseding never fires.
        prompt = build_actionability_prompt(2, own_pr_url=self._PR)
        assert self._PR in prompt
        assert "never counts as `already_addressed`" in prompt

    def test_actionability_prompt_says_nothing_without_a_pr(self):
        prompt = build_actionability_prompt(2)
        assert "already_addressed`" in prompt  # the general guidance survives
        assert "github.com" not in prompt

    def test_supersede_prompt_names_the_pr_and_the_summary_it_was_built_from(self):
        prompt = build_supersede_prompt(self._PR, "the previous summary")
        assert self._PR in prompt
        assert "the previous summary" in prompt
        assert "obsolete_pr_urls" in prompt
