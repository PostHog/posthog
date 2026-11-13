"""Unit tests for the unified ACP log accessor used by sandboxed-eval scorers."""

from __future__ import annotations

import unittest

from products.posthog_ai.backend.exec_commands import INFO_SYNTHETIC_PREFIX
from products.posthog_ai.eval_harness.log_parser import EXEC_TOOL_NAME, SKILL_TOOL_NAME, LogParser, SkillCall, ToolCall
from products.posthog_ai.eval_harness.test.acp_log_lines import (
    agent_text_line,
    end_turn_line,
    join_lines,
    prompt_line,
    tool_call_completed_line,
    tool_call_input_line,
    tool_call_start_line,
)


def _make_tool_log(
    tool_name: str,
    raw_input: dict,
    output: str = "ok",
    status: str = "completed",
    call_id: str = "t1",
) -> str:
    """Build a minimal one-call session: prompt → tool → final text → end_turn."""
    return join_lines(
        [
            prompt_line("2026-04-15T10:00:00.000Z"),
            tool_call_start_line("2026-04-15T10:00:01.000Z", call_id, tool_name),
            tool_call_input_line("2026-04-15T10:00:01.100Z", call_id, raw_input),
            tool_call_completed_line("2026-04-15T10:00:02.000Z", call_id, output, status=status),
            agent_text_line("2026-04-15T10:00:03.000Z", "done"),
            end_turn_line("2026-04-15T10:00:04.000Z"),
        ]
    )


class TestLogParserSkillCalls(unittest.TestCase):
    def test_was_skill_called_returns_true_for_matching_skill(self):
        raw = _make_tool_log(
            SKILL_TOOL_NAME,
            {"skill": "improving-drf-endpoints", "args": ""},
        )
        parser = LogParser(raw, initial_prompt="hi")
        self.assertTrue(parser.was_skill_called("improving-drf-endpoints"))

    def test_was_skill_called_returns_false_for_unmatched_skill(self):
        raw = _make_tool_log(
            SKILL_TOOL_NAME,
            {"skill": "improving-drf-endpoints", "args": ""},
        )
        parser = LogParser(raw, initial_prompt="hi")
        self.assertFalse(parser.was_skill_called("django-migrations"))

    def test_was_skill_called_returns_false_when_no_skill_calls(self):
        raw = _make_tool_log("query-trends", {"foo": 1})
        parser = LogParser(raw, initial_prompt="hi")
        self.assertFalse(parser.was_skill_called("anything"))

    def test_get_skill_calls_returns_chronological_list(self):
        raw = join_lines(
            [
                prompt_line("2026-04-15T10:00:00.000Z"),
                tool_call_start_line("2026-04-15T10:00:01.000Z", "s1", SKILL_TOOL_NAME),
                tool_call_input_line("2026-04-15T10:00:01.100Z", "s1", {"skill": "first", "args": "a"}),
                tool_call_completed_line("2026-04-15T10:00:02.000Z", "s1", "r1"),
                tool_call_start_line("2026-04-15T10:00:03.000Z", "s2", SKILL_TOOL_NAME),
                tool_call_input_line("2026-04-15T10:00:03.100Z", "s2", {"skill": "second"}),
                tool_call_completed_line("2026-04-15T10:00:04.000Z", "s2", "r2"),
                agent_text_line("2026-04-15T10:00:05.000Z", "done"),
                end_turn_line("2026-04-15T10:00:06.000Z"),
            ]
        )

        parser = LogParser(raw, initial_prompt="hi")
        calls = parser.get_skill_calls()

        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0].name, "first")
        self.assertEqual(calls[0].args, "a")
        self.assertEqual(calls[0].output, "r1")
        self.assertFalse(calls[0].is_error)
        self.assertEqual(calls[1].name, "second")
        self.assertIsNone(calls[1].args)
        self.assertLess(calls[0].position, calls[1].position)

    def test_get_skill_calls_filters_by_name(self):
        raw = join_lines(
            [
                prompt_line("2026-04-15T10:00:00.000Z"),
                tool_call_start_line("2026-04-15T10:00:01.000Z", "s1", SKILL_TOOL_NAME),
                tool_call_input_line("2026-04-15T10:00:01.100Z", "s1", {"skill": "first"}),
                tool_call_completed_line("2026-04-15T10:00:02.000Z", "s1", "r1"),
                tool_call_start_line("2026-04-15T10:00:03.000Z", "s2", SKILL_TOOL_NAME),
                tool_call_input_line("2026-04-15T10:00:03.100Z", "s2", {"skill": "second"}),
                tool_call_completed_line("2026-04-15T10:00:04.000Z", "s2", "r2"),
                agent_text_line("2026-04-15T10:00:05.000Z", "done"),
                end_turn_line("2026-04-15T10:00:06.000Z"),
            ]
        )

        parser = LogParser(raw, initial_prompt="hi")
        only_first = parser.get_skill_calls("first")

        self.assertEqual(len(only_first), 1)
        self.assertEqual(only_first[0].name, "first")

    def test_skill_calls_are_excluded_from_get_tool_calls(self):
        raw = _make_tool_log(SKILL_TOOL_NAME, {"skill": "x"})
        parser = LogParser(raw, initial_prompt="hi")

        self.assertEqual(parser.get_tool_calls(), [])
        self.assertEqual(len(parser.get_skill_calls()), 1)


class TestLogParserToolCalls(unittest.TestCase):
    def test_regular_tool_call_returns_normalized_name_and_input(self):
        raw = _make_tool_log("query-trends", {"foo": 1})
        parser = LogParser(raw, initial_prompt="hi")

        calls = parser.get_tool_calls()
        self.assertEqual(len(calls), 1)
        call = calls[0]
        self.assertEqual(call.name, "query-trends")
        self.assertEqual(call.input, {"foo": 1})
        self.assertEqual(call.output, "ok")
        self.assertFalse(call.is_error)
        self.assertFalse(call.is_exec_unwrapped)
        self.assertEqual(call.raw_name, "query-trends")

    def test_get_tool_calls_filters_by_normalized_name(self):
        raw = join_lines(
            [
                prompt_line("2026-04-15T10:00:00.000Z"),
                tool_call_start_line("2026-04-15T10:00:01.000Z", "t1", "query-trends"),
                tool_call_input_line("2026-04-15T10:00:01.100Z", "t1", {"a": 1}),
                tool_call_completed_line("2026-04-15T10:00:02.000Z", "t1", "r1"),
                tool_call_start_line("2026-04-15T10:00:03.000Z", "t2", "query-funnel"),
                tool_call_input_line("2026-04-15T10:00:03.100Z", "t2", {"b": 2}),
                tool_call_completed_line("2026-04-15T10:00:04.000Z", "t2", "r2"),
                agent_text_line("2026-04-15T10:00:05.000Z", "done"),
                end_turn_line("2026-04-15T10:00:06.000Z"),
            ]
        )
        parser = LogParser(raw, initial_prompt="hi")

        trends = parser.get_tool_calls("query-trends")
        funnels = parser.get_tool_calls("query-funnel")

        self.assertEqual(len(trends), 1)
        self.assertEqual(trends[0].input, {"a": 1})
        self.assertEqual(len(funnels), 1)
        self.assertEqual(funnels[0].input, {"b": 2})

    def test_failed_tool_calls_surface_with_is_error_true(self):
        raw = _make_tool_log("query-trends", {"foo": 1}, output="boom", status="failed")
        parser = LogParser(raw, initial_prompt="hi")

        calls = parser.get_tool_calls()
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].is_error)
        self.assertEqual(calls[0].output, "boom")

    def test_unpaired_tool_use_surfaces_with_is_error_true_and_empty_output(self):
        """When tool_call starts but no completion update arrives, the parser
        emits a ``tool_use`` block with no matching ``tool_result``. We surface
        it as ``is_error=True`` so downstream filters can drop it."""
        raw = join_lines(
            [
                prompt_line("2026-04-15T10:00:00.000Z"),
                tool_call_start_line("2026-04-15T10:00:01.000Z", "t1", "query-trends"),
                tool_call_input_line("2026-04-15T10:00:01.100Z", "t1", {"foo": 1}),
                agent_text_line("2026-04-15T10:00:03.000Z", "done"),
                end_turn_line("2026-04-15T10:00:04.000Z"),
            ]
        )
        parser = LogParser(raw, initial_prompt="hi")

        calls = parser.get_tool_calls()
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].is_error)
        self.assertEqual(calls[0].output, "")

    def test_tool_result_just_before_end_turn_is_kept(self):
        raw = join_lines(
            [
                prompt_line("2026-04-15T10:00:00.000Z"),
                tool_call_start_line("2026-04-15T10:00:01.000Z", "t1", "query-trends"),
                tool_call_input_line("2026-04-15T10:00:01.100Z", "t1", {"foo": 1}),
                tool_call_completed_line("2026-04-15T10:00:02.000Z", "t1", "42"),
                end_turn_line("2026-04-15T10:00:03.000Z"),
            ]
        )
        parser = LogParser(raw, initial_prompt="hi")

        calls = parser.get_tool_calls()
        self.assertEqual(len(calls), 1)
        self.assertFalse(calls[0].is_error)
        self.assertEqual(calls[0].output, "42")

    def test_mcp_prefix_is_stripped_in_normalized_name(self):
        raw = _make_tool_log("mcp__posthog__query-trends", {"foo": 1})
        parser = LogParser(raw, initial_prompt="hi")

        call = parser.get_tool_calls()[0]
        self.assertEqual(call.name, "query-trends")
        self.assertEqual(call.raw_name, "mcp__posthog__query-trends")

    def test_exec_call_command_is_unwrapped(self):
        raw = _make_tool_log(
            EXEC_TOOL_NAME,
            {"command": 'call query-retention {"foo": 1}'},
            output="results",
        )
        parser = LogParser(raw, initial_prompt="hi")

        calls = parser.get_tool_calls()
        self.assertEqual(len(calls), 1)
        call = calls[0]
        self.assertEqual(call.name, "query-retention")
        self.assertEqual(call.input, {"foo": 1})
        self.assertTrue(call.is_exec_unwrapped)
        self.assertEqual(call.raw_name, EXEC_TOOL_NAME)
        self.assertEqual(call.output, "results")

    def test_exec_call_flags_are_consumed_before_the_tool_name(self):
        for command in (
            'call --json query-trends {"x": 2}',
            'call --no-skills query-trends {"x": 2}',
            'call --confirm --json query-trends {"x": 2}',
        ):
            with self.subTest(command=command):
                raw = _make_tool_log(EXEC_TOOL_NAME, {"command": command})
                parser = LogParser(raw, initial_prompt="hi")

                call = parser.get_tool_calls()[0]
                self.assertEqual(call.name, "query-trends")
                self.assertEqual(call.input, {"x": 2})
                self.assertTrue(call.is_exec_unwrapped)

    def test_exec_info_command_produces_synthetic_name(self):
        raw = _make_tool_log(
            EXEC_TOOL_NAME,
            {"command": "info query-trends"},
        )
        parser = LogParser(raw, initial_prompt="hi")

        call = parser.get_tool_calls()[0]
        self.assertEqual(call.name, f"{INFO_SYNTHETIC_PREFIX}query-trends")
        self.assertEqual(call.input, {})
        self.assertTrue(call.is_exec_unwrapped)

    def test_exec_unrecognized_command_falls_back_to_raw_exec(self):
        raw = _make_tool_log(
            EXEC_TOOL_NAME,
            {"command": "search foo"},
        )
        parser = LogParser(raw, initial_prompt="hi")

        call = parser.get_tool_calls()[0]
        self.assertEqual(call.name, EXEC_TOOL_NAME)
        self.assertFalse(call.is_exec_unwrapped)
        self.assertEqual(call.input, {"command": "search foo"})

    def test_filter_by_name_matches_exec_unwrapped_inner_tool(self):
        raw = _make_tool_log(
            EXEC_TOOL_NAME,
            {"command": 'call query-retention {"foo": 1}'},
        )
        parser = LogParser(raw, initial_prompt="hi")

        self.assertEqual(len(parser.get_tool_calls("query-retention")), 1)
        self.assertEqual(parser.get_tool_calls("exec"), [])

    def test_position_is_chronological(self):
        raw = join_lines(
            [
                prompt_line("2026-04-15T10:00:00.000Z"),
                tool_call_start_line("2026-04-15T10:00:01.000Z", "t1", "first"),
                tool_call_input_line("2026-04-15T10:00:01.100Z", "t1", {}),
                tool_call_completed_line("2026-04-15T10:00:02.000Z", "t1", "r1"),
                tool_call_start_line("2026-04-15T10:00:03.000Z", "t2", "second"),
                tool_call_input_line("2026-04-15T10:00:03.100Z", "t2", {}),
                tool_call_completed_line("2026-04-15T10:00:04.000Z", "t2", "r2"),
                agent_text_line("2026-04-15T10:00:05.000Z", "done"),
                end_turn_line("2026-04-15T10:00:06.000Z"),
            ]
        )
        parser = LogParser(raw, initial_prompt="hi")

        calls = parser.get_tool_calls()
        self.assertEqual([c.name for c in calls], ["first", "second"])
        self.assertLess(calls[0].position, calls[1].position)


class TestLogParserMessages(unittest.TestCase):
    def test_get_final_agent_message_returns_last_assistant_text(self):
        raw = join_lines(
            [
                prompt_line("2026-04-15T10:00:00.000Z"),
                agent_text_line("2026-04-15T10:00:01.000Z", "first reply"),
                tool_call_start_line("2026-04-15T10:00:02.000Z", "t1", "search"),
                tool_call_input_line("2026-04-15T10:00:02.100Z", "t1", {}),
                tool_call_completed_line("2026-04-15T10:00:03.000Z", "t1", "r"),
                agent_text_line("2026-04-15T10:00:04.000Z", "final reply"),
                end_turn_line("2026-04-15T10:00:05.000Z"),
            ]
        )
        parser = LogParser(raw, initial_prompt="hi")
        self.assertEqual(parser.get_final_agent_message(), "final reply")

    def test_get_final_agent_message_returns_none_when_run_ends_on_tool_use(self):
        raw = join_lines(
            [
                prompt_line("2026-04-15T10:00:00.000Z"),
                tool_call_start_line("2026-04-15T10:00:01.000Z", "t1", "search"),
                tool_call_input_line("2026-04-15T10:00:01.100Z", "t1", {}),
                tool_call_completed_line("2026-04-15T10:00:02.000Z", "t1", "r"),
                end_turn_line("2026-04-15T10:00:03.000Z"),
            ]
        )
        parser = LogParser(raw, initial_prompt="hi")
        self.assertIsNone(parser.get_final_agent_message())

    def test_get_user_prompt_returns_initial_prompt_when_seeded(self):
        raw = join_lines(
            [
                prompt_line("2026-04-15T10:00:00.000Z"),
                agent_text_line("2026-04-15T10:00:01.000Z", "ok"),
                end_turn_line("2026-04-15T10:00:02.000Z"),
            ]
        )
        parser = LogParser(raw, initial_prompt="seeded prompt")
        self.assertEqual(parser.get_user_prompt(), "seeded prompt")

    def test_get_user_prompt_falls_back_when_no_initial_prompt(self):
        raw = join_lines(
            [
                agent_text_line("2026-04-15T10:00:01.000Z", "ok"),
                end_turn_line("2026-04-15T10:00:02.000Z"),
            ]
        )
        parser = LogParser(raw)
        self.assertEqual(parser.get_user_prompt(), "")


class TestLogParserModels(unittest.TestCase):
    def test_tool_call_is_frozen(self):
        call = ToolCall(
            name="x",
            input={},
            output="",
            is_error=False,
            call_id="c",
            position=0,
            sequence=0,
            raw_name="x",
            is_exec_unwrapped=False,
        )
        with self.assertRaises(Exception):
            call.name = "y"  # type: ignore[misc]  # ty: ignore[invalid-assignment]

    def test_skill_call_is_frozen(self):
        call = SkillCall(name="x", call_id="c", output="", is_error=False, position=0)
        with self.assertRaises(Exception):
            call.name = "y"  # type: ignore[misc]  # ty: ignore[invalid-assignment]
