"""An author's rejection of a review-bot finding, judged through the offline review entrypoint."""

import sys
import json
from types import SimpleNamespace
from typing import Any

import pytest
from unittest.mock import MagicMock

sys.modules.setdefault("claude_agent_sdk", MagicMock())
sys.modules.setdefault("claude_agent_sdk.types", MagicMock())

import review_local  # noqa: E402
import openai_reviewer  # noqa: E402
from test_review_local import _api_file, _run_context, _thread_comment  # noqa: E402

_FINDING = "src/app.py: handler() returns None when the cache is empty."


def _rejected(bot: str, *, holds: bool = True, category: str = "other") -> dict:
    return {
        "bot": bot,
        "concern": _FINDING,
        "category": category,
        "rejection_holds": holds,
        "evidence": "src/app.py fills the cache before handler() can run.",
    }


class _JudgingReviewer(openai_reviewer.OpenAIReviewer):
    facts: dict = {}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        usage = SimpleNamespace(
            input_tokens=1,
            input_tokens_details=SimpleNamespace(cached_tokens=0),
            output_tokens=1,
            output_tokens_details=SimpleNamespace(reasoning_tokens=0),
        )
        answer = SimpleNamespace(
            status="completed",
            output=[SimpleNamespace(type="message")],
            output_text=json.dumps(self.facts),
            usage=usage,
        )
        self.client = SimpleNamespace(responses=SimpleNamespace(create=lambda **_: answer))


@pytest.mark.parametrize(
    "root, rejected, expected",
    [
        pytest.param(_thread_comment("posthog", _FINDING, is_bot=True), _rejected("posthog"), "APPROVED", id="holds"),
        pytest.param(
            _thread_comment("posthog", _FINDING, is_bot=True),
            _rejected("posthog", holds=False),
            "REFUSED",
            id="rejection-does-not-hold",
        ),
        pytest.param(
            _thread_comment("posthog", _FINDING, is_bot=True),
            _rejected("posthog", category="auth"),
            "REFUSED",
            id="strict-category",
        ),
        pytest.param(_thread_comment("carol", _FINDING), _rejected("carol"), "REFUSED", id="raised-by-a-person"),
        pytest.param(
            _thread_comment("posthog", _FINDING, is_bot=True),
            _rejected("veria-ai"),
            "REFUSED",
            id="bot-not-on-the-pr",
        ),
    ],
)
def test_author_rejected_bot_finding_resolves_only_when_the_judge_upholds_it(
    monkeypatch, root: dict, rejected: dict, expected: str
) -> None:
    monkeypatch.setattr(review_local, "_git_diff_files", lambda *a, **k: [])
    monkeypatch.setattr(review_local, "pr_provenance", lambda *a, **k: None)
    _JudgingReviewer.facts = {
        "risky_areas": [],
        "reviews_on_current_head": [],
        "owning_team_author": False,
        "strong_familiarity": False,
        "unresolved_substantive_concerns": [],
        "other_refusal_grounds": [],
        "rejected_bot_concerns": [rejected],
        "reasoning": "One rejected finding.",
        "change_summary": "The handler reads from a warm cache.",
    }
    monkeypatch.setattr(openai_reviewer, "OpenAIReviewer", _JudgingReviewer)
    thread = {"is_resolved": False, "is_outdated": False, "path": "src/app.py", "line": 3}
    reply = _thread_comment("alice", "Not a bug: the cache is filled at import.")
    context = {**_run_context([_api_file("src/app.py")]), "review_threads": [{**thread, "comments": [root, reply]}]}

    result = review_local.run(context)

    assert result["final_verdict"] == expected
    named_in_body = f"after checking the author's rejection: @{rejected['bot']}: {_FINDING}" in result["review_body"]
    assert named_in_body is (expected == "APPROVED")
    assert ".." not in result["review_body"]
