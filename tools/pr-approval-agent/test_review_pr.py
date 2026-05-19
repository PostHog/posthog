"""Tests for the review_pr.py output format."""

import sys

from unittest.mock import MagicMock

# review_pr.py is a uv-script; its `claude_agent_sdk` dep is installed by
# `uv run`, not the test venv. Stub the modules reviewer.py imports from.
sys.modules.setdefault("claude_agent_sdk", MagicMock())
sys.modules.setdefault("claude_agent_sdk.types", MagicMock())

from github import PRData  # noqa: E402
from review_pr import Pipeline  # noqa: E402


def _fake_pr(head_sha: str) -> PRData:
    return PRData(
        number=1,
        repo="PostHog/posthog",
        title="test",
        state="OPEN",
        draft=False,
        mergeable_state="clean",
        author="alice",
        labels=[],
        base_sha="def456",
        head_sha=head_sha,
        files=[],
        reviews=[],
        review_comments=[],
        check_runs=[],
    )


def test_to_dict_includes_head_sha() -> None:
    """The post-review workflow step reads head_sha from the JSON output to
    lock the resulting GitHub review to the sha the LLM actually saw — see
    `.github/workflows/pr-approval-agent.yml`'s "Post review" step."""
    pipeline = Pipeline(pr_number=1, repo="PostHog/posthog")
    pipeline.pr = _fake_pr(head_sha="07dfeff14d95be1247e4c8c1065fd958a367389e")
    pipeline.classification = {"tier": "T1-trivial", "breadth": "narrow"}
    pipeline.gate_results = []
    pipeline.reviewer_output = None
    pipeline.final_verdict = "APPROVED"

    output = pipeline.to_dict()

    assert output["head_sha"] == "07dfeff14d95be1247e4c8c1065fd958a367389e"
