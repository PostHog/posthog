from __future__ import annotations

import json
from typing import Any

import pytest
from unittest.mock import patch

from click.testing import CliRunner
from hogli_commands import agent_usage, ci_insights, posthog_auth

_SOURCES = [{"id": "src-good", "repo": "PostHog/posthog", "prefix": "eng_analytics", "synced": True}]


def _usage(cost: float, generations: int) -> dict[str, Any]:
    return {
        "cost_usd": cost,
        "input_tokens": 1200,
        "output_tokens": 3400,
        "generations": generations,
        "cache_read_input_tokens": 2_500_000,
        "cache_creation_input_tokens": 180_000,
        "peak_context_tokens": 140_000,
    }


def _pr(number: int, title: str, usage: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "number": number,
        "title": title,
        "state": "merged",
        "head_branch": f"feat/{number}",
        "created_at": "2026-10-20T12:00:00Z",
        "llm_spend": usage,
    }


class _Response:
    def __init__(self, payload: Any) -> None:
        self.status_code = 200
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self) -> Any:
        return self._payload


class _Recorder:
    def __init__(self, items: list[dict[str, Any]]) -> None:
        self.calls: dict[str, dict[str, Any]] = {}
        self._payloads = {
            "sources": _SOURCES,
            "author_llm_spend": {"items": items, "truncated": False, "limit": 100},
            "llm_spend_coverage": {
                "cost_usd": 40,
                "attributed_cost_usd": 30.0,
                "generations": 900,
                "attributed_generations": 700,
            },
        }

    def __call__(self, url: str, *, token: str, params: dict[str, Any], timeout: float) -> _Response:
        action = url.rstrip("/").rsplit("/", 1)[-1]
        self.calls[action] = params
        return _Response(self._payloads[action])


@pytest.fixture(autouse=True)
def signed_in(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in posthog_auth.KEY_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("POSTHOG_PERSONAL_API_KEY", "phx_test_key_do_not_leak")


def _invoke(argv: list[str], recorder: _Recorder) -> Any:
    with (
        patch.object(ci_insights, "_request", recorder),
        patch.object(ci_insights, "_git", return_value="git@github.com:PostHog/posthog.git"),
        patch.object(agent_usage, "_gh_login", return_value="alice"),
    ):
        return CliRunner().invoke(agent_usage.cmd_agent_usage, argv)


def test_reads_the_callers_spend_and_lists_only_attributed_prs_by_cost() -> None:
    recorder = _Recorder(
        [
            _pr(12, "small change", _usage(2.5, 10)),
            _pr(11, "no agent work", None),
            _pr(10, "big change", _usage(27.5, 90)),
        ]
    )

    result = _invoke(["--days", "14", "--format", "text"], recorder)

    assert result.exit_code == 0, result.output
    assert recorder.calls["author_llm_spend"] == {
        "source_id": "src-good",
        "repo": "PostHog/posthog",
        "author": "alice",
        "date_from": "-14d",
        "limit": 100,
    }
    assert recorder.calls["llm_spend_coverage"]["date_from"] == "-14d"
    lines = result.output.splitlines()
    pr_lines = [line for line in lines if line.rstrip().endswith("change")]
    assert [line.split("  ")[-1] for line in pr_lines] == ["#10 big change", "#12 small change"]
    assert "no agent work" not in result.output
    assert "$30.00 across 2 of 3 pull requests" in result.output
    assert "Repo coverage: 75% of $40.00" in result.output


def test_no_attributed_spend_points_at_the_ingestion_setup() -> None:
    result = _invoke(["--format", "text"], _Recorder([_pr(11, "no agent work", None)]))

    assert result.exit_code == 0, result.output
    assert "/posthog:llma-cc-setup" in result.output
