from typing import Any

from parameterized import parameterized

from products.tasks.backend.temporal.process_task.slack_progress_phases import (
    phase_for_tool_call,
    tool_call_from_acp_update,
)


def _claude(tool_name: str, raw_input: dict[str, Any] | None = None, kind: str | None = None) -> dict[str, Any]:
    update: dict[str, Any] = {"_meta": {"claudeCode": {"toolName": tool_name}}, "rawInput": raw_input or {}}
    if kind:
        update["kind"] = kind
    return update


def _codex_command(command: str, kind: str) -> dict[str, Any]:
    return {"title": command, "kind": kind}


def _codex_mcp(server: str, tool: str) -> dict[str, Any]:
    return {"title": f"{server}/{tool}", "kind": "other", "_meta": {"posthog": {"toolName": f"mcp__{server}__{tool}"}}}


class TestPhaseForToolCall:
    @parameterized.expand(
        [
            ("posthog_mcp", _claude("mcp__posthog__exec", {"command": "call execute-sql {}"}), "posthog_data"),
            ("codex_posthog_mcp", _codex_mcp("posthog", "exec"), "posthog_data"),
            ("read", _claude("Read", {"file_path": "/repo/a.py"}, kind="read"), "reading_code"),
            ("grep_command", _claude("Bash", {"command": "grep -rn foo src"}, kind="execute"), "reading_code"),
            ("codex_read_command", _codex_command("cat README.md", "read"), "reading_code"),
            ("edit", _claude("Edit", {"file_path": "/repo/a.py"}, kind="edit"), "making_changes"),
            ("tests", _claude("Bash", {"command": "cd repo && pytest tests/"}, kind="execute"), "running_checks"),
            ("codex_tests", _codex_command("pnpm run typecheck", "execute"), "running_checks"),
            ("pr_command", _claude("Bash", {"command": "gh pr create --draft"}, kind="execute"), "opening_pr"),
            ("signed_commit", _claude("mcp__posthog-code-tools__git_signed_commit", {"message": "x"}), "opening_pr"),
            ("other_command", _claude("Bash", {"command": "python3 script.py"}, kind="execute"), "running_commands"),
            ("web", _claude("WebFetch", {"url": "https://example.com"}, kind="fetch"), "searching_web"),
            ("artifact", _claude("mcp__posthog-code-tools__upload_artifact", {"path": "a.png"}), "preparing_files"),
            ("clone", _claude("mcp__posthog-code-tools__clone_repo", {"repo": "org/repo"}), "getting_code"),
            ("summary", _claude("mcp__posthog__task_summary_update", {"summary": "x"}), None),
            ("codex_summary", _codex_mcp("posthog-code-tools", "task_summary_update"), None),
            ("tool_search", _claude("ToolSearch", {"query": "select:x"}), None),
            ("other_mcp_server", _codex_mcp("slack", "post_message"), None),
        ]
    )
    def test_maps_tool_calls_to_plain_phases(self, _name: str, update: dict[str, Any], expected: str | None) -> None:
        tool_call = tool_call_from_acp_update(update)
        assert tool_call is not None

        phase = phase_for_tool_call(tool_call)

        assert (phase.key if phase else None) == expected

    def test_claude_shell_call_waits_for_its_command(self) -> None:
        # Claude streams the call before its input. Classifying it then would file every
        # test run and pull request under "Running commands".
        assert tool_call_from_acp_update(_claude("Bash", {}, kind="execute")) is None
