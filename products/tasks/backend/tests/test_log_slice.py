import os
import json
from pathlib import Path

from django.test import SimpleTestCase

from parameterized import parameterized

from products.tasks.backend.logic.log_slice import (
    LogPart,
    log_entries,
    log_part,
    slice_log_from,
    slice_log_parts_tail,
    slice_log_tail,
    summarize_log_part,
    summary_from_json,
    summary_to_json,
)

# The client tests replay these pages, so they run against what this slicer returns.
LOG_PAGE_FIXTURES = Path(__file__).parent / "fixtures" / "log_pages.json"


def _line(method: str, params: dict | None = None) -> str:
    return json.dumps({"type": "notification", "notification": {"method": method, "params": params or {}}})


def _update(session_update: str, **fields: object) -> str:
    return _line("session/update", {"update": {"sessionUpdate": session_update, **fields}})


def _user(text: str) -> str:
    return _update("user_message_chunk", content={"type": "text", "text": text})


def _tool(call_id: str, output_bytes: int) -> list[str]:
    return [
        _update("tool_call", toolCallId=call_id, title="Bash"),
        _update("tool_call_update", toolCallId=call_id, status="completed", rawOutput="x" * output_bytes),
    ]


def _log(lines: list[str]) -> str:
    return "".join(f"{line}\n" for line in lines)


def _turn(text: str, tools: int, output_bytes: int) -> list[str]:
    lines = [_user(text)]
    for index in range(tools):
        lines += _tool(f"{text}-{index}", output_bytes)
    return [*lines, _update("agent_message", content={"type": "text", "text": f"{text} done"})]


class TestSliceLogTail(SimpleTestCase):
    @parameterized.expand(
        [
            ("latest_turn_that_meets_the_budget", 1000, None, 10, "second"),
            ("whole_log_when_the_budget_covers_it", 10**9, None, 0, "first"),
            ("window_ends_before_the_given_index", 1000, 10, 0, "first"),
        ]
    )
    def test_cuts_at_a_user_turn(
        self, _name: str, tail_bytes: int, before: int | None, offset: int, first_text: str
    ) -> None:
        lines = [*_turn("first", 4, 100), *_turn("second", 4, 100)]

        sliced = slice_log_tail(_log(lines), tail_bytes, before)

        self.assertEqual((sliced.offset, sliced.count, sliced.turns_before), (offset, len(lines), 1 if offset else 0))
        entries = [json.loads(line) for line in sliced.content.splitlines()][sliced.preamble :]
        self.assertEqual(entries[0]["notification"]["params"]["update"]["content"]["text"], first_text)
        self.assertEqual(len(entries), (before if before is not None else len(lines)) - offset)

    @parameterized.expand(
        [
            ("acp_whole_message", _update("user_message", content={"type": "text", "text": "second"})),
            ("posthog_notification", _line("_posthog/user_message", {"content": "second"})),
        ]
    )
    def test_recognizes_every_user_turn_format(self, _name: str, user_line: str) -> None:
        second = [user_line, *_turn("second", 4, 100)[1:]]
        lines = [*_turn("first", 4, 100), *second]

        sliced = slice_log_tail(_log(lines), 1000)

        self.assertEqual(sliced.content.splitlines()[sliced.preamble], user_line)

    @parameterized.expand(
        [
            (
                "nested_subagent_calls",
                [
                    _update("tool_call", toolCallId="parent", title="Task"),
                    *[
                        _update(
                            kind,
                            toolCallId=f"child-{index}",
                            title="Bash",
                            rawOutput="x" * 1000,
                            _meta={"claudeCode": {"parentToolCallId": "parent"}},
                        )
                        for index in range(12)
                        for kind in ("tool_call", "tool_call_update")
                    ],
                ],
            ),
            (
                "parallel_calls",
                [
                    _update(kind, toolCallId=f"{name}-{index}", title="Bash", rawOutput="x" * 1000)
                    for index in range(12)
                    for kind, name in (
                        ("tool_call", "a"),
                        ("tool_call", "b"),
                        ("tool_call_update", "a"),
                        ("tool_call_update", "b"),
                    )
                ],
            ),
        ]
    )
    def test_cut_leaves_no_tool_frame_without_its_call(self, _name: str, tool_lines: list[str]) -> None:
        lines = [_user("only"), *tool_lines]

        sliced = slice_log_tail(_log(lines), 2000)

        window = [json.loads(line)["notification"]["params"]["update"] for line in sliced.content.splitlines()]
        called = {update["toolCallId"] for update in window if update["sessionUpdate"] == "tool_call"}
        referenced = {update["toolCallId"] for update in window} | {
            update["_meta"]["claudeCode"]["parentToolCallId"] for update in window if "_meta" in update
        }
        self.assertGreater(sliced.offset, 0)
        self.assertEqual(referenced - called, set())

    @parameterized.expand(
        [
            ("echo_after_its_prompt", []),
            ("echo_a_turn_later", [_update("agent_message", content={"type": "text", "text": "first done"})]),
        ]
    )
    def test_cut_keeps_both_forms_of_a_message_on_one_side(self, _name: str, between: list[str]) -> None:
        queued = [_line("_posthog/user_message", {"content": "second"}), *between, _line("session/prompt")]
        # An older send of the same text whose echo never came must not hold the cut back to it.
        unanswered = [_line("_posthog/user_message", {"content": "second"}), *_turn("old", 4, 100)[1:]]
        lines = [*unanswered, *_turn("first", 4, 100), *queued, _user("second"), *_turn("second", 4, 100)[1:]]

        sliced = slice_log_tail(_log(lines), 1000)

        window = sliced.content.splitlines()[sliced.preamble :]
        self.assertEqual(sliced.offset, len(lines) - len(window))
        self.assertIn(queued[0], window)
        self.assertIn(_user("second"), window)
        self.assertGreater(sliced.offset, len(unanswered))

    def test_summary_cache_value_round_trips_as_json(self) -> None:
        context = "<posthog_untrusted_context>\n- insight abc\n</posthog_untrusted_context>\nwhy"
        lines = [
            _line("_posthog/run_started", {"runId": "r"}),
            _line("_posthog/permission_request", {"requestId": "open"}),
            _line("_posthog/permission_resolved", {"requestId": "done"}),
            _line("_posthog/user_message", {"content": context}),
            *_turn("first", 2, 10),
        ]
        summary = summarize_log_part(lines)

        self.assertEqual(summary_from_json(summary_to_json(summary)), summary)
        self.assertIsNone(summary_from_json('{"count": "x"}'))

    def test_counts_turns_before_the_cut_the_way_the_thread_does(self) -> None:
        hidden = _update("user_message_chunk", content={"type": "text", "text": "x", "_meta": {"ui": {"hidden": True}}})
        lines = [
            _line("_posthog/user_message", {"content": "echoed"}),
            _line("session/prompt"),
            _user("echoed"),
            _update("agent_message", content={"type": "text", "text": "a"}),
            hidden,
            _update("agent_message", content={"type": "text", "text": "b"}),
            _user("one"),
            _user("two"),
            _update("agent_message", content={"type": "text", "text": "c"}),
            *_turn("latest", 0, 0),
        ]

        sliced = slice_log_tail(_log(lines), 1)

        self.assertEqual((sliced.offset, sliced.turns_before), (9, 3))

    def test_reads_a_log_with_a_method_that_is_not_a_string(self) -> None:
        malformed = json.dumps({"type": "notification", "notification": {"method": ["_posthog/usage_update"]}})
        lines = [*_turn("first", 4, 100), malformed, *_turn("second", 4, 100)]

        sliced = slice_log_tail(_log(lines), 1000)

        self.assertEqual(sliced.offset, 11)

    @parameterized.expand(
        [
            ("every_entry_from_the_start", 10, 10**9, 10**9, 10, 0),
            ("latest_turns_when_too_large", 2, 1000, 500, 10, 0),
            ("from_the_start_when_the_latest_turns_begin_earlier", 18, 10**9, 10, 18, 0),
        ]
    )
    def test_reads_from_a_start_index(
        self, _name: str, start: int, tail_bytes: int, max_bytes: int, offset: int, preamble: int
    ) -> None:
        lines = [*_turn("first", 4, 100), *_turn("second", 4, 100)]

        sliced = slice_log_from(_log(lines), start, tail_bytes, max_bytes)

        self.assertEqual((sliced.offset, sliced.preamble, sliced.count), (offset, preamble, len(lines)))
        self.assertEqual(sliced.content.splitlines()[sliced.preamble :], lines[offset:])

    def test_cuts_a_turn_past_the_cap_before_a_tool_call(self) -> None:
        lines = _turn("only", 40, 1000)

        sliced = slice_log_tail(_log(lines), 2000)

        first = json.loads(sliced.content.splitlines()[sliced.preamble])
        self.assertGreater(sliced.offset, 0)
        self.assertEqual(first["notification"]["params"]["update"]["sessionUpdate"], "tool_call")
        self.assertLess(len(sliced.content), 2000 * 5)

    def test_preamble_keeps_the_state_that_still_holds_at_the_cut(self) -> None:
        head = [
            _line("_posthog/run_started", {"runId": "old"}),
            _line("session/new", {"_meta": {"permissionMode": "bypassPermissions"}}),
            _line("_posthog/run_started", {"runId": "current"}),
            _line("_posthog/usage_update", {"used": {"inputTokens": 5}, "cost": 0.1}),
            _line("_posthog/usage_update", {"breakdown": {"tools": 3}}),
            _line("_posthog/permission_request", {"requestId": "open"}),
            _line("_posthog/permission_request", {"requestId": "answered"}),
            _line("_posthog/permission_resolved", {"requestId": "answered"}),
        ]
        closed = [_line("_posthog/permission_request", {"requestId": "closed"}), _line("_posthog/turn_complete")]
        context = "<posthog_untrusted_context>\n- insight abc\n</posthog_untrusted_context>\nwhy"
        with_context = [_line("_posthog/user_message", {"content": context})]
        lines = [*closed, *head, *with_context, *_turn("first", 4, 100), *_turn("second", 4, 100)]

        sliced = slice_log_tail(_log(lines), 1000)

        preamble = [json.loads(line)["notification"] for line in sliced.content.splitlines()[: sliced.preamble]]
        self.assertEqual(preamble[0], {"method": "_posthog/context_history", "params": {"messages": [context]}})
        self.assertEqual(
            [(item["method"], item["params"].get("runId") or item["params"].get("requestId")) for item in preamble[1:]],
            [
                ("session/new", None),
                ("_posthog/run_started", "current"),
                ("_posthog/usage_update", None),
                ("_posthog/usage_update", None),
                ("_posthog/permission_request", "open"),
            ],
        )

    def test_reads_only_the_runs_the_window_overlaps(self) -> None:
        runs = [
            [_line("_posthog/run_started", {"runId": "older"}), *_turn("older", 4, 100)],
            [_line("_posthog/run_started", {"runId": "newer"}), *_turn("first", 4, 100), *_turn("second", 4, 100)],
        ]
        reads: list[int] = []

        def part(index: int) -> LogPart:
            entries = log_entries("".join(f"{line}\n" for line in runs[index]))

            def read() -> list[str]:
                reads.append(index)
                return entries

            return LogPart(summary=summarize_log_part(entries), entries=read)

        sliced = slice_log_parts_tail([part(0), part(1)], 1000)

        self.assertEqual(reads, [1])
        self.assertEqual((sliced.offset, sliced.count), (len(runs[0]) + 11, len(runs[0]) + len(runs[1])))
        preamble = [
            json.loads(line)["notification"]["params"] for line in sliced.content.splitlines()[: sliced.preamble]
        ]
        self.assertEqual(preamble, [{"runId": "newer"}])


def _pages(case: dict) -> list[dict]:
    parts = [log_part([json.dumps(entry) for entry in part]) for part in case["parts"]]
    pages: list[dict] = []
    before: int | None = None
    while before != 0:
        sliced = slice_log_parts_tail(parts, case["tail_bytes"], before)
        pages.append(
            {
                "offset": sliced.offset,
                "count": sliced.count,
                "preamble": sliced.preamble,
                "turns_before": sliced.turns_before,
                "entries": [json.loads(line) for line in sliced.content.splitlines()],
            }
        )
        before = sliced.offset
    return pages


class TestLogPageFixtures(SimpleTestCase):
    def test_fixture_pages_are_what_the_slicer_returns(self) -> None:
        fixture = json.loads(LOG_PAGE_FIXTURES.read_text())
        pages = {case["name"]: _pages(case) for case in fixture["cases"]}
        if os.environ.get("UPDATE_LOG_PAGE_FIXTURES"):
            for case in fixture["cases"]:
                case["pages"] = pages[case["name"]]
            LOG_PAGE_FIXTURES.write_text(json.dumps(fixture, indent=1) + "\n")

        self.assertEqual(
            {case["name"]: case.get("pages") for case in fixture["cases"]},
            pages,
            "Run this test with UPDATE_LOG_PAGE_FIXTURES=1 to write the pages again.",
        )
