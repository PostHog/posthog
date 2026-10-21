import json

from django.test import SimpleTestCase

from parameterized import parameterized

from products.tasks.backend.logic.log_slice import (
    LogPart,
    log_entries,
    slice_log_parts_tail,
    slice_log_tail,
    summarize_log_part,
)


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
            (
                "legacy_pi_event",
                json.dumps({"type": "pi_event", "event": {"type": "user_message", "content": "second"}}),
            ),
        ]
    )
    def test_recognizes_every_user_turn_format(self, _name: str, user_line: str) -> None:
        second = [user_line, *_turn("second", 4, 100)[1:]]
        lines = [*_turn("first", 4, 100), *second]

        sliced = slice_log_tail(_log(lines), 1000)

        self.assertEqual(sliced.content.splitlines()[sliced.preamble], user_line)

    def test_cuts_a_turn_past_the_cap_before_a_top_level_tool_call(self) -> None:
        nested = [
            _update(
                "tool_call", toolCallId="child", title="Bash", _meta={"claudeCode": {"parentToolCallId": "parent"}}
            ),
            _update("tool_call_update", toolCallId="child", status="completed", rawOutput="x" * 1000),
        ]
        lines = [*_turn("only", 40, 1000), *(nested * 6)]

        sliced = slice_log_tail(_log(lines), 2000)

        first = json.loads(sliced.content.splitlines()[sliced.preamble])["notification"]["params"]["update"]
        self.assertEqual((first["sessionUpdate"], "_meta" in first), ("tool_call", False))

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
        lines = [*closed, *head, *_turn("first", 4, 100), *_turn("second", 4, 100)]

        sliced = slice_log_tail(_log(lines), 1000)

        preamble = [json.loads(line)["notification"] for line in sliced.content.splitlines()[: sliced.preamble]]
        self.assertEqual(
            [(item["method"], item["params"].get("runId") or item["params"].get("requestId")) for item in preamble],
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
            summary = summarize_log_part(entries)
            return LogPart(entries=lambda: reads.append(index) or entries, summary=lambda: summary)

        sliced = slice_log_parts_tail([part(0), part(1)], 1000)

        self.assertEqual(reads, [1])
        self.assertEqual((sliced.offset, sliced.count), (len(runs[0]) + 11, len(runs[0]) + len(runs[1])))
        preamble = [
            json.loads(line)["notification"]["params"] for line in sliced.content.splitlines()[: sliced.preamble]
        ]
        self.assertEqual(preamble, [{"runId": "newer"}])
