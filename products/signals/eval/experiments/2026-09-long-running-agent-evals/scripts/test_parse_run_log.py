from unittest import TestCase

from parse_run_log import JsonValue, facts


class TestRunLogFacts(TestCase):
    def test_reads_commands_from_input_or_legacy_titles(self) -> None:
        commit = "0123456789abcdef"
        command = f"git fetch --depth=1 origin {commit} && git checkout {commit} && cat posthog/api/example.py products/example/backend/views.py"
        inputs: tuple[dict[str, JsonValue] | None, ...] = (None, {"command": command})
        for raw_input in inputs:
            with self.subTest(raw_input=raw_input):
                entries: list[dict[str, JsonValue]] = [
                    {
                        "notification": {
                            "method": "session/update",
                            "params": {
                                "update": {
                                    "sessionUpdate": "tool_call",
                                    "toolCallId": "synthetic-call",
                                    "title": "/bin/bash" if raw_input else f"/bin/bash -c '{command}'",
                                    "rawInput": raw_input,
                                }
                            },
                        }
                    },
                    {
                        "notification": {
                            "method": "session/update",
                            "params": {
                                "update": {
                                    "sessionUpdate": "tool_call_update",
                                    "toolCallId": "synthetic-call",
                                    "rawOutput": {"content": [{"text": f"HEAD is now at {commit}"}]},
                                }
                            },
                        }
                    },
                ]
                result = facts(entries, {"posthog/api/example.py"}, commit)
                self.assertTrue(result["pin_ok"])
                self.assertEqual(result["bash_commands"], 1)
                self.assertEqual(result["files_in_page"], ["posthog/api/example.py"])
                self.assertEqual(result["files_outside_page"], ["products/example/backend/views.py"])
                self.assertFalse(facts(entries, set(), "different-commit")["pin_ok"])
