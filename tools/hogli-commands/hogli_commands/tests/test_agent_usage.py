from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hogli_commands.agent_usage import PullRequest, group_by_pull_request, project_dirs, read_transcripts


def _assistant(message_id: str, session: str, branch: str, output_tokens: int) -> dict[str, Any]:
    return {
        "type": "assistant",
        "sessionId": session,
        "gitBranch": branch,
        "timestamp": "2026-10-20T12:00:00.000Z",
        "message": {
            "id": message_id,
            "model": "claude-opus-5-5",
            "usage": {
                "input_tokens": 10,
                "cache_creation_input_tokens": 300,
                "cache_creation": {"ephemeral_1h_input_tokens": 200, "ephemeral_5m_input_tokens": 100},
                "cache_read_input_tokens": 1000,
                "output_tokens": output_tokens,
            },
        },
    }


def test_counts_each_response_once_and_attributes_scratch_branch_turns_to_the_session_pr(tmp_path: Path) -> None:
    transcript = tmp_path / "session.jsonl"
    records = [
        _assistant("msg_1", "s1", "worktree-scratch", 5),
        _assistant("msg_1", "s1", "worktree-scratch", 5),
        _assistant("msg_2", "s1", "feat/thing", 7),
        _assistant("msg_3", "s2", "master", 1),
        {"type": "pr-link", "sessionId": "s1", "prNumber": 42},
    ]
    transcript.write_text("\n".join(json.dumps(record) for record in records) + "\nnot json\n")

    transcripts = read_transcripts([transcript], since=datetime(2026, 10, 1, tzinfo=UTC))
    groups = group_by_pull_request(transcripts, [PullRequest(number=42, title="feat: thing", branch="feat/thing")])

    by_label = {group.label: group for group in groups}
    assert set(by_label) == {"#42 feat: thing", "master"}
    pr_group = by_label["#42 feat: thing"]
    assert (pr_group.requests, pr_group.output_tokens, pr_group.cache_write_tokens) == (2, 12, 600)
    assert pr_group.weighted_tokens == 2 * (10 + 1.25 * 100 + 2.0 * 200 + 0.1 * 1000) + 5.0 * 12
    assert pr_group.peak_context_tokens == 1310


def test_project_dirs_include_worktrees_but_not_sibling_clones(tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    for name in (
        "-src-posthog",
        "-src-posthog--claude-worktrees-happy-goblet",
        "-src-posthog-private",
        "-src-posthog-private--claude-worktrees-other",
    ):
        (projects / name).mkdir(parents=True)

    found = project_dirs(projects, [Path("/src/posthog")])

    assert [directory.name for directory in found] == ["-src-posthog", "-src-posthog--claude-worktrees-happy-goblet"]
