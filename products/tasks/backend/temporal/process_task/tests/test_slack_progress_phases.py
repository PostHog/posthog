from datetime import timedelta
from typing import Any

from parameterized import parameterized

from products.tasks.backend.temporal.process_task.slack_progress_phases import (
    done_plan_title,
    intent_from_narrative,
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


def _codex_mcp(server: str, tool: str, raw_input: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "title": f"{server}/{tool}",
        "kind": "other",
        "_meta": {"posthog": {"toolName": f"mcp__{server}__{tool}"}},
        "rawInput": raw_input or {},
    }


class TestPhaseForToolCall:
    @parameterized.expand(
        [
            (
                "sql_on_events",
                _claude("mcp__posthog__exec", {"command": 'call execute-sql {"query": "SELECT count() FROM events"}'}),
                "posthog_events",
            ),
            (
                "sql_schema_on_a_new_line",
                _claude(
                    "mcp__posthog__exec",
                    {"command": 'call execute-sql {"query": "SELECT name\\nFROM system.information_schema.tables"}'},
                ),
                "posthog_schema",
            ),
            (
                "sql_first_table_wins",
                _claude(
                    "mcp__posthog__exec",
                    {"command": 'call execute-sql {"query": "SELECT 1 FROM persons JOIN events ON 1"}'},
                ),
                "posthog_people",
            ),
            (
                "sql_system_object",
                _claude(
                    "mcp__posthog__exec", {"command": 'call execute-sql {"query": "SELECT * FROM system.insights"}'}
                ),
                "posthog_dashboards",
            ),
            (
                "sql_warehouse_table",
                _claude(
                    "mcp__posthog__exec", {"command": 'call execute-sql {"query": "SELECT * FROM stripe_invoices"}'}
                ),
                "posthog_warehouse",
            ),
            (
                "direct_sql_tool",
                _claude("mcp__posthog__execute-sql", {"query": "SELECT 1 FROM sessions"}),
                "posthog_sessions",
            ),
            ("schema_tool", _claude("mcp__posthog__exec", {"command": "call read-data-schema {}"}), "posthog_schema"),
            (
                "unknown_posthog_tool",
                _claude("mcp__posthog__exec", {"command": "call annotation-list {}"}),
                "posthog_other",
            ),
            (
                "posthog_errors",
                _claude("mcp__posthog__exec", {"command": "call error-tracking-issues-list {}"}),
                "posthog_errors",
            ),
            (
                "posthog_call_flags",
                _claude("mcp__posthog__exec", {"command": "call --json dashboard-get {}"}),
                "posthog_dashboards",
            ),
            (
                "codex_posthog_replays",
                _codex_mcp("posthog", "exec", {"command": "call session-recordings-list {}"}),
                "posthog_replays",
            ),
            ("posthog_direct_tool", _claude("mcp__posthog__feature-flag-get-all", {}), "posthog_flags"),
            # Looking up what the server offers is not work on the user's data.
            ("posthog_search", _claude("mcp__posthog__exec", {"command": "search error issues"}), None),
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

    @parameterized.expand(
        [
            ("shell", _claude("Bash", {}, kind="execute")),
            ("posthog_exec", _claude("mcp__posthog__exec", {})),
            ("direct_sql_tool", _claude("mcp__posthog__execute-sql", {})),
        ]
    )
    def test_call_waits_for_its_command(self, _name: str, update: dict[str, Any]) -> None:
        # Claude streams the call before its input. Classifying it then would file every test run
        # under "Running commands" and every PostHog query on the wrong line.
        assert tool_call_from_acp_update(update) is None

    @parameterized.expand(
        [
            (
                "claude_shell",
                _claude("Bash", {"command": "pytest", "description": "Run the relay tests."}, kind="execute"),
                "Run the relay tests",
            ),
            # Another tool's description argument is content, such as a new dashboard's text.
            (
                "posthog_tool",
                _claude("mcp__posthog__dashboard-create", {"description": "Weekly revenue for the board"}),
                None,
            ),
        ]
    )
    def test_only_the_shell_description_reaches_the_plan(
        self, _name: str, update: dict[str, Any], expected: str | None
    ) -> None:
        tool_call = tool_call_from_acp_update(update)

        assert tool_call is not None
        assert tool_call.description == expected


class TestIntentFromNarrative:
    @parameterized.expand(
        [
            ("let_me", "Let me pull daily active users for last week.", "Pull daily active users for last week"),
            ("last_sentence", "Great, the table exists. Now I'll count DAU per day:", "Count DAU per day"),
            ("markdown", "The **events** table has data.\n\nLet me check `$pageview` counts", "Check $pageview counts"),
            # A question asks the reader and reports nothing about the work.
            ("question", "Should I use UTC for the week?", None),
            ("too_short", "Ok.", None),
        ]
    )
    def test_reads_the_last_sentence_as_an_activity(self, _name: str, text: str, expected: str | None) -> None:
        assert intent_from_narrative(text) == expected


class TestDonePlanTitle:
    @parameterized.expand(
        [
            (timedelta(seconds=48), "Done in 48s"),
            (timedelta(seconds=72), "Done in 1m 12s"),
            (timedelta(minutes=2), "Done in 2m"),
            (timedelta(minutes=63, seconds=5), "Done in 1h 3m"),
        ]
    )
    def test_reads_as_a_short_duration(self, elapsed: timedelta, expected: str) -> None:
        assert done_plan_title(elapsed) == expected
