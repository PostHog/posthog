"""Tests for the PR-writing handoff layer.

Covers two components that are easy to regress without live Temporal:

* :func:`render_code_handoff_prompt` — must embed every autoresearch
  artifact the agent needs, never silently drop empty sections.
* :func:`_parse_pr_report` — parses the agent's final JSON block into
  typed ``PrEntry`` / ``SkippedHunch`` values. It must be defensive: the
  agent can skip fields, emit no JSON at all, or embed extra prose.
"""

from __future__ import annotations

import textwrap

import pytest

from products.query_performance_ai.backend.prompts import render_code_handoff_prompt
from products.query_performance_ai.backend.temporal.workflows import (
    PrEntry,
    SkippedHunch,
    _parse_pr_report,
)


class TestRenderCodeHandoffPrompt:
    def _render(self, **overrides):
        defaults = dict(
            query_id="slow-abc-123",
            team_id=42,
            original_sql="SELECT count() FROM events",
            best_sql="SELECT count() FROM events WHERE event = 'x'",
            baseline_metrics_json='{"primary":{"name":"latency_ms","value":1200}}',
            best_metrics_json='{"primary":{"name":"latency_ms","value":300}}',
            last_run_json='{"kind":"candidate"}',
            operator_hunches="Suspect predicate pushdown on event filter.",
            suggestions="Consider materializing event_count per team.",
            lanes=[("L1-pushdown.md", "Lane 1 body\nmore lines")],
            hypotheses=[("H-001.md", "Hypothesis body")],
            reviews=[("campaign-review.md", "Final review")],
        )
        defaults.update(overrides)
        return render_code_handoff_prompt(**defaults)

    def test_embeds_required_artifacts(self):
        prompt = self._render()
        assert "slow-abc-123" in prompt
        assert "SELECT count() FROM events" in prompt
        assert "predicate pushdown" in prompt
        assert "materializing event_count" in prompt
        assert "L1-pushdown.md" in prompt
        assert "H-001.md" in prompt
        assert "campaign-review.md" in prompt

    def test_prettifies_metrics_json(self):
        prompt = self._render()
        # A prettified block has the key on its own line with padding.
        assert '"primary": {\n    "name": "latency_ms"' in prompt

    def test_empty_sections_render_none_placeholder_not_gaps(self):
        prompt = self._render(lanes=[], hypotheses=[], reviews=[], operator_hunches="")
        assert "_(none)_" in prompt
        # The template sections are still labelled.
        assert "### Lanes" in prompt
        assert "### Hypotheses" in prompt

    def test_final_json_block_is_present_unchanged(self):
        # The PR-writing contract requires the template's trailing JSON
        # example to survive formatting (no collapsed braces).
        prompt = self._render()
        assert '"prs": [' in prompt
        assert '"url": "https://github.com/PostHog/posthog/pull/NNNN"' in prompt
        assert '"skipped_hunches": [' in prompt


class TestParsePrReport:
    def test_empty_output_returns_empty_lists(self):
        prs, skipped = _parse_pr_report(None)
        assert prs == []
        assert skipped == []

    def test_extracts_from_pr_report_field(self):
        output = {
            "pr_report": {
                "prs": [
                    {"url": "https://github.com/PostHog/posthog/pull/1", "kind": "query-rewrite", "improvement_pct": 42.1},
                    {"url": "https://github.com/PostHog/posthog/pull/2"},
                ],
                "skipped_hunches": [
                    {"hunch": "materialize foo", "reason": "needs migration coordination"},
                ],
            }
        }
        prs, skipped = _parse_pr_report(output)
        assert prs == [
            PrEntry(url="https://github.com/PostHog/posthog/pull/1", kind="query-rewrite", improvement_pct=42.1),
            PrEntry(url="https://github.com/PostHog/posthog/pull/2", kind="", improvement_pct=None),
        ]
        assert skipped == [SkippedHunch(hunch="materialize foo", reason="needs migration coordination")]

    def test_extracts_from_last_message_json_block(self):
        # The more common path: agent dropped the report in its final message.
        last_message = textwrap.dedent(
            """
            Done. Opened the PRs and documented what I couldn't ship.

            ```json
            {"prs":[{"url":"https://github.com/PostHog/posthog/pull/42","kind":"index","improvement_pct":18.5}],"skipped_hunches":[]}
            ```

            Let me know if you need anything else.
            """
        )
        prs, skipped = _parse_pr_report({"last_message": last_message})
        assert prs == [PrEntry(url="https://github.com/PostHog/posthog/pull/42", kind="index", improvement_pct=18.5)]
        assert skipped == []

    def test_prefers_last_json_block_when_multiple_present(self):
        # Agents sometimes write a "wip" block then a final block. We take
        # the last one as authoritative.
        last_message = textwrap.dedent(
            """
            Draft: ```json
            {"prs":[{"url":"https://github.com/PostHog/posthog/pull/1"}]}
            ```
            Final: ```json
            {"prs":[{"url":"https://github.com/PostHog/posthog/pull/2"}]}
            ```
            """
        )
        prs, _ = _parse_pr_report({"last_message": last_message})
        assert [pr.url for pr in prs] == ["https://github.com/PostHog/posthog/pull/2"]

    def test_ignores_malformed_entries(self):
        output = {
            "pr_report": {
                "prs": [
                    {"url": "https://github.com/PostHog/posthog/pull/1"},
                    {"kind": "no url here"},  # missing url → drop
                    "not a dict",  # drop
                    {"url": 42},  # wrong type → drop
                ],
                "skipped_hunches": [
                    {"hunch": "ok hunch", "reason": "ok reason"},
                    {"hunch": "missing reason"},  # drop
                ],
            }
        }
        prs, skipped = _parse_pr_report(output)
        assert [pr.url for pr in prs] == ["https://github.com/PostHog/posthog/pull/1"]
        assert [h.hunch for h in skipped] == ["ok hunch"]

    def test_non_dict_output_is_safe(self):
        prs, skipped = _parse_pr_report("just a string")  # type: ignore[arg-type]
        assert prs == []
        assert skipped == []

    @pytest.mark.parametrize(
        "output",
        [
            {"last_message": "no json here at all"},
            {"last_message": "```json\nnot a dict — just a number\n```"},
            {"last_message": "```json\n{invalid json\n```"},
        ],
    )
    def test_garbage_last_message_returns_empty(self, output):
        prs, skipped = _parse_pr_report(output)
        assert prs == []
        assert skipped == []
