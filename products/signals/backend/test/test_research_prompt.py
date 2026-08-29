from datetime import datetime

import pytest

from products.signals.backend.report_charts import ReportChart
from products.signals.backend.report_generation.research import (
    SignalFinding,
    _render_signal_for_research,
    build_initial_research_prompt,
    build_report_presentation_prompt,
    build_signal_investigation_prompt,
)
from products.signals.backend.temporal.types import SignalData


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
    # A DataVisualizationNode carrying `display` but no `chartSettings` stores and validates
    # cleanly, then draws every row at a single x position instead of a series. The guidance is
    # the only thing that tells the agent to set the axes, so losing this line means every
    # SQL-backed chart the pipeline authors renders wrong in the reader's inbox with nothing
    # reporting a failure. The scout channel guards the same instruction in its own example.
    def test_chart_guidance_names_the_axes_a_sql_graph_needs(self):
        on = build_report_presentation_prompt(2)
        assert "chartSettings.xAxis.column" in on
        assert "chartSettings.yAxis[].column" in on

    def test_previous_charts_context_rendered_when_present(self):
        chart = _make_chart()
        with_previous = build_report_presentation_prompt(1, previous_charts=[chart])
        without_previous = build_report_presentation_prompt(1)
        assert "Charts this report already shows" in with_previous
        assert "signups-drop" in with_previous
        assert "Charts this report already shows" not in without_previous
