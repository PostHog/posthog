from __future__ import annotations

import json

from unittest import TestCase

from pydantic import JsonValue

from .faults import Fault
from .replay import Replay, ResponseStep


class TestReplay(TestCase):
    def test_codex_tool_calls_require_the_discovered_namespace(self) -> None:
        step = ResponseStep.model_validate(
            {
                "provider": "codex",
                "model": "synthetic-model",
                "fixture": "insight-update",
                "user_message": "Rename synthetic insight",
                "tool_result": {"call_id": "search_synthetic", "contains": "mcp__posthog"},
                "substitutions": {
                    "model": "synthetic-model",
                    "message_id": "msg_synthetic",
                    "tool_call_id": "call_synthetic",
                    "tool_name": "exec",
                    "tool_namespace": "mcp__posthog",
                    "arguments": "{}",
                },
            }
        )
        discovered: dict[str, JsonValue] = {"type": "namespace", "name": "mcp__posthog", "tools": []}
        body: dict[str, JsonValue] = {
            "model": step.model,
            "stream": True,
            "tools": [{"type": "tool_search"}],
            "input": [
                {"role": "user", "content": step.user_message},
                {"type": "tool_search_output", "call_id": "search_synthetic", "tools": [discovered]},
            ],
        }
        with self.assertRaisesRegex(ValueError, "not offered"):
            Replay([step]).respond("codex", body)
        discovered["tools"] = [{"type": "function", "name": "exec"}]
        replay = Replay([step])
        self.assertIn(b'"namespace": "mcp__posthog"', replay.respond("codex", body))
        replay.verify()

    def test_mismatches_never_advance_or_pass_verification(self) -> None:
        step = ResponseStep(
            provider="claude",
            model="synthetic-model",
            fixture="text",
            user_message="first turn",
            substitutions={
                "message_id": "msg_synthetic",
                "model": "synthetic-model",
                "text": "Synthetic response",
            },
        )
        request: dict[str, JsonValue] = {
            "model": step.model,
            "stream": True,
            "messages": [{"role": "user", "content": "first turn"}],
        }
        mismatches: tuple[tuple[str, dict[str, JsonValue]], ...] = (
            ("codex", {}),
            ("claude", {"model": "wrong"}),
            ("claude", {"stream": False}),
            ("claude", {"messages": [{"role": "user", "content": "wrong turn"}]}),
        )
        for provider, changed in mismatches:
            with self.subTest(provider=provider, changed=changed):
                replay = Replay([step])
                with self.assertRaises(ValueError):
                    replay.respond(provider, {**request, **changed})
                self.assertEqual(replay.cursor, 0)
                with self.assertRaises(AssertionError):
                    replay.verify()

    def test_real_tool_result_required_for_both_provider_encodings(self) -> None:
        for provider in ("claude", "codex"):
            with self.subTest(provider=provider):
                step = ResponseStep.model_validate(
                    {
                        "provider": provider,
                        "model": "synthetic-model",
                        "fixture": "text",
                        "user_message": "rename insight",
                        "tool_result": {"call_id": "call_synthetic", "contains": "Synthetic renamed insight"},
                        "substitutions": {
                            "model": "synthetic-model",
                            "message_id": "msg_synthetic",
                            "text": "Renamed.",
                        },
                    }
                )
                user: dict[str, JsonValue] = {"role": "user", "content": "rename insight"}
                result: dict[str, JsonValue] = (
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "call_synthetic",
                                "content": "Synthetic renamed insight",
                            }
                        ],
                    }
                    if provider == "claude"
                    else {
                        "type": "function_call_output",
                        "call_id": "call_synthetic",
                        "output": "Synthetic renamed insight",
                    }
                )
                field = "messages" if provider == "claude" else "input"
                body: dict[str, JsonValue] = {"model": step.model, "stream": True, field: [user]}
                with self.assertRaises(ValueError):
                    Replay([step]).respond(provider, body)
                replay = Replay([step])
                with self.assertRaises(AssertionError):
                    replay.verify()
                frames = replay.respond(provider, {**body, field: [user, result]}).decode()
                events = [
                    json.loads(line.removeprefix("data: ")) for line in frames.splitlines() if line.startswith("data: ")
                ]
                self.assertGreater(len(events), 1)
                self.assertIn("Renamed.", frames)
                replay.verify()
                with self.assertRaises(ValueError):
                    replay.respond(provider, body)


class TestFaultLifecycle(TestCase):
    def test_reset_releases_waiters_but_cannot_erase_an_unexercised_arm(self) -> None:
        fault = Fault("registration", [])
        fault.arm("owned-run")
        self.assertFalse(fault.reach("other-run"))
        fault.reset()
        fault.wait_for_release()
        fault.arm("owned-run")
        self.assertTrue(fault.reach("owned-run"))
        fault.wait_for_release(1)
        fault.wait_until_reached()
        fault.release()
        with self.assertRaises(AssertionError):
            fault.verify()

    def test_approval_latches_one_request_until_release(self) -> None:
        fault = Fault("approval", [])
        fault.arm()
        self.assertTrue(fault.reach("owned-request"))
        self.assertTrue(fault.reach("owned-request"))
        self.assertFalse(fault.reach("new-request"))
        fault.release()
        self.assertFalse(fault.reach("owned-request"))
        fault.verify()
