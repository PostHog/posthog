"""Tests for reviewer.py error handling."""

import sys
from dataclasses import dataclass
from unittest.mock import MagicMock, patch
from pathlib import Path

import pytest

# Provide real-enough stubs for claude_agent_sdk so we can test error paths
# without the full SDK installed.


@dataclass
class FakeProcessError(Exception):
    """Mimics claude_agent_sdk.ProcessError."""

    exit_code: int | None = None
    stderr: str | None = None


@dataclass
class FakeResultMessage:
    subtype: str = "success"
    is_error: bool = False
    structured_output: dict | None = None
    api_error_status: int | None = None
    duration_ms: int = 0
    duration_api_ms: int = 0
    num_turns: int = 1
    session_id: str = "test"


# Wire up the mock module with realistic types
mock_sdk = MagicMock()
mock_sdk.ProcessError = FakeProcessError
mock_sdk.ResultMessage = FakeResultMessage
mock_sdk.ClaudeAgentOptions = MagicMock
sys.modules.setdefault("claude_agent_sdk", mock_sdk)
sys.modules.setdefault("claude_agent_sdk.types", MagicMock())

from github import PRData  # noqa: E402
from reviewer import Reviewer  # noqa: E402


def _fake_pr() -> PRData:
    return PRData(
        number=1,
        repo="PostHog/posthog",
        title="test",
        state="OPEN",
        draft=False,
        mergeable_state="clean",
        author="alice",
        labels=[],
        base_sha="aaa",
        head_sha="bbb",
        files=[{"filename": "foo.py", "status": "modified", "additions": 1, "deletions": 0, "patch": "+x"}],
        reviews=[],
        review_comments=[],
        check_runs=[],
    )


def _gate_context():
    return {"gate_verdict": "pass", "gates": []}


async def _query_raise_process_error(**kwargs):
    """Simulates the SDK raising ProcessError after an API-level failure."""
    raise FakeProcessError(exit_code=1, stderr=None)
    yield  # pragma: no cover — makes this an async generator


async def _query_yield_error_result(**kwargs):
    """Simulates receiving a ResultMessage with is_error=True (API failure)."""
    yield FakeResultMessage(
        subtype="success",
        is_error=True,
        api_error_status=429,
        structured_output=None,
    )


async def _query_yield_valid_result(**kwargs):
    """Simulates a successful review."""
    yield FakeResultMessage(
        subtype="success",
        is_error=False,
        structured_output={
            "verdict": "APPROVE",
            "reasoning": "LGTM",
            "risk": "low",
            "issues": [],
        },
    )


@patch("reviewer.query")
@patch.object(Reviewer, "_write_diff_file")
@patch.object(Reviewer, "_build_review_prompt", return_value="review this")
def test_process_error_surfaces_clear_message(mock_prompt, mock_write_diff, mock_query, tmp_path):
    """When the SDK raises ProcessError (CLI exit non-zero after API failure),
    reviewer.py should raise RuntimeError with actionable info, not the
    confusing 'error result: success' message."""
    mock_write_diff.return_value = tmp_path / "diff.patch"
    (tmp_path / "diff.patch").write_text("")
    mock_query.side_effect = _query_raise_process_error

    reviewer = Reviewer(repo_root=tmp_path, verbose=False)
    with pytest.raises(RuntimeError, match="Claude CLI exited with error"):
        reviewer.review(_fake_pr(), {"tier": "T1"}, _gate_context())


@patch("reviewer.query")
@patch.object(Reviewer, "_write_diff_file")
@patch.object(Reviewer, "_build_review_prompt", return_value="review this")
def test_is_error_result_raises_with_status(mock_prompt, mock_write_diff, mock_query, tmp_path):
    """When a ResultMessage has is_error=True, reviewer.py should raise
    immediately with the HTTP status code for debuggability."""
    mock_write_diff.return_value = tmp_path / "diff.patch"
    (tmp_path / "diff.patch").write_text("")
    mock_query.return_value = _query_yield_error_result()

    reviewer = Reviewer(repo_root=tmp_path, verbose=False)
    with pytest.raises(RuntimeError, match="API error during review \\(HTTP 429\\)"):
        reviewer.review(_fake_pr(), {"tier": "T1"}, _gate_context())


@patch("reviewer.query")
@patch.object(Reviewer, "_write_diff_file")
@patch.object(Reviewer, "_build_review_prompt", return_value="review this")
def test_successful_review_returns_verdict(mock_prompt, mock_write_diff, mock_query, tmp_path):
    """Happy path: valid structured output is returned as the verdict."""
    mock_write_diff.return_value = tmp_path / "diff.patch"
    (tmp_path / "diff.patch").write_text("")
    mock_query.return_value = _query_yield_valid_result()

    reviewer = Reviewer(repo_root=tmp_path, verbose=False)
    result = reviewer.review(_fake_pr(), {"tier": "T1"}, _gate_context())

    assert result["verdict"] == "APPROVE"
    assert result["reasoning"] == "LGTM"
