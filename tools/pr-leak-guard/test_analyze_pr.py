"""Tests for the analyze_pr orchestration logic."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import analyze_pr  # noqa: E402


def test_strip_template_boilerplate_removes_html_comments() -> None:
    body = """## Problem

<!-- Who are we building for, what are their needs, why is this important? -->

The customer Acme reported a bug.

<!-- Closes #ISSUE_ID -->

## Changes
"""
    cleaned = analyze_pr._strip_template_boilerplate(body)
    assert "<!--" not in cleaned
    assert "Acme reported a bug" in cleaned
    assert "## Problem" in cleaned


def test_strip_template_boilerplate_handles_multiline_comments() -> None:
    body = """before
<!-- this is
a multi
line comment -->
after
"""
    cleaned = analyze_pr._strip_template_boilerplate(body)
    assert "before" in cleaned
    assert "after" in cleaned
    assert "multi" not in cleaned


def test_analyze_clean_description_skips_llm() -> None:
    # short clean description shouldn't hit the LLM path
    result = analyze_pr.analyze("Bumped lockfile.", skip_llm=True)
    assert result.findings == []
    assert result.llm_verdict == "clean"
    assert not result.changed


def test_analyze_finds_regex_leak() -> None:
    description = (
        "## Problem\n"
        "Customer reported via https://posthog.zendesk.com/agent/tickets/9999 — "
        "discussed on https://posthog.slack.com/archives/C012/p123\n"
    )
    result = analyze_pr.analyze(description, skip_llm=True)
    categories = {f.category for f in result.findings}
    assert "zendesk-ticket-url" in categories
    assert "slack-permalink" in categories
    assert "zendesk.com" not in result.redacted
    assert "slack.com" not in result.redacted
    assert result.changed


def test_analyze_blocks_on_secrets() -> None:
    description = "## Problem\n\nFound the leaked AKIAIOSFODNN7EXAMPLE in code\n"
    result = analyze_pr.analyze(description, skip_llm=True)
    assert result.has_blockers


def test_render_comment_for_clean_description() -> None:
    result = analyze_pr.AnalysisResult(
        pr_number=42,
        description="x",
        findings=[],
        llm_verdict="clean",
        llm_reasoning="",
        redacted="x",
    )
    body = analyze_pr._render_comment(result)
    assert analyze_pr.COMMENT_MARKER in body
    assert "scan clean" in body.lower()


def test_render_comment_for_findings_includes_diff() -> None:
    description = "Customer Acme reported via https://posthog.zendesk.com/agent/tickets/9999"
    result = analyze_pr.analyze(description, skip_llm=True)
    body = analyze_pr._render_comment(result)
    assert analyze_pr.COMMENT_MARKER in body
    assert "Possible sensitive data" in body or "Possible secret leak" in body
    assert "[redacted: zendesk ticket]" in body
    assert "diff" in body.lower()


def test_render_comment_for_block_severity_calls_out_secret() -> None:
    description = "AKIAIOSFODNN7EXAMPLE leaked here"
    result = analyze_pr.analyze(description, skip_llm=True)
    body = analyze_pr._render_comment(result)
    assert "secret" in body.lower()
    assert "🛑" in body


def test_min_description_length_skips_llm_for_short_text(monkeypatch) -> None:
    """Confirm we don't waste an LLM call on near-empty descriptions."""
    called = {"v": False}

    def mock_analyze(*_a, **_kw):
        called["v"] = True
        return analyze_pr.LLMResult(verdict="clean", reasoning="", findings=[])

    monkeypatch.setattr(analyze_pr, "llm_analyze", mock_analyze)

    analyze_pr.analyze("short text", skip_llm=False)
    assert called["v"] is False


def test_first_sentence_truncates() -> None:
    text = "This is the reasoning. With more details after."
    assert analyze_pr._first_sentence(text) == "This is the reasoning."


def test_build_suggestion_block_shows_redaction_lines() -> None:
    original = "Reported by Customer Acme on slack: https://posthog.slack.com/archives/C012/p1"
    result = analyze_pr.analyze(original, skip_llm=True)
    diff = analyze_pr._build_suggestion_block(original, result.redacted)
    assert "+" in diff or "[redacted" in diff
