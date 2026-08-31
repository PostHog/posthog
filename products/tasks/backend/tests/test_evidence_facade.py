import json
from datetime import UTC, datetime

from unittest.mock import patch

from django.test import TestCase

from posthog.models import Organization, Team
from posthog.models.user import User

from products.tasks.backend.facade import api as facade
from products.tasks.backend.models import Task, TaskRun


class TestCompletedPostHogMCPToolCalls(TestCase):
    def setUp(self) -> None:
        organization = Organization.objects.create(name="Example organization")
        self.team = Team.objects.create(organization=organization, name="Example team")
        self.user = User.objects.create_user(email="owner@example.com", first_name="Owner", password="safe-password")
        self.task = Task.objects.create(
            team=self.team,
            title="Measure example activation",
            description="Use invented test data only.",
            origin_product=Task.OriginProduct.USER_CREATED,
            created_by=self.user,
        )
        self.task_run = TaskRun.objects.create(task=self.task, team=self.team, status=TaskRun.Status.COMPLETED)

    def _calls(self, entries: list[dict]) -> list:
        log = "\n".join(json.dumps(entry) for entry in entries)
        with patch("posthog.storage.object_storage.read", return_value=log):
            return facade.get_completed_posthog_mcp_tool_calls(self.task_run.id, self.task.id, self.team.id)

    @staticmethod
    def _entry(update: dict, timestamp: str = "2026-08-30T10:00:00Z") -> dict:
        return {
            "type": "notification",
            "timestamp": timestamp,
            "notification": {"method": "session/update", "params": {"update": update}},
        }

    def test_reconstructs_direct_posthog_call_preferring_structured_content(self) -> None:
        calls = self._calls(
            [
                self._entry(
                    {
                        "sessionUpdate": "tool_call",
                        "toolCallId": "direct-1",
                        "title": "mcp__posthog__query-insight",
                        "_meta": {"claudeCode": {"toolName": "mcp__posthog__query-insight"}},
                        "rawInput": {"arguments": {"insight_id": "example-insight"}},
                    }
                ),
                self._entry(
                    {
                        "sessionUpdate": "tool_call_update",
                        "toolCallId": "direct-1",
                        "status": "completed",
                        "rawOutput": [
                            {
                                "type": "text",
                                "text": json.dumps(
                                    {
                                        "structuredContent": {"value": 12, "unit": "users"},
                                        "content": [{"type": "text", "text": '{"ignored": true}'}],
                                        "isError": False,
                                    }
                                ),
                            }
                        ],
                    },
                    "2026-08-30T10:03:00Z",
                ),
            ]
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].tool_call_id, "direct-1")
        self.assertEqual(calls[0].tool_name, "query-insight")
        self.assertEqual(calls[0].arguments, {"insight_id": "example-insight"})
        self.assertEqual(calls[0].result, {"value": 12, "unit": "users"})
        self.assertEqual(calls[0].completed_at, datetime(2026, 8, 30, 10, 3, tzinfo=UTC))
        self.assertFalse(calls[0].is_error)
        self.assertFalse(calls[0].is_truncated)

    def test_reconstructs_single_exec_json_call_from_content(self) -> None:
        calls = self._calls(
            [
                self._entry(
                    {
                        "sessionUpdate": "tool_call_update",
                        "toolCallId": "exec-1",
                        "title": "Execute command",
                        "status": "completed",
                        "rawInput": {"command": 'call --json query-insight {"insight_id":"example-insight"}'},
                        "rawOutput": [
                            {
                                "type": "text",
                                "text": '{"value":9,"unit":"users"}',
                            }
                        ],
                    }
                )
            ]
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].tool_name, "query-insight")
        self.assertEqual(calls[0].arguments, {"insight_id": "example-insight"})
        self.assertEqual(calls[0].result, {"value": 9, "unit": "users"})

    def test_reconstructs_direct_call_when_raw_input_is_the_actual_arguments(self) -> None:
        arguments = {
            "name": "example-activation",
            "date_from": "2026-08-01T00:00:00Z",
            "date_to": "2026-08-08T00:00:00Z",
            "interval": "day",
        }
        calls = self._calls(
            [
                self._entry(
                    {
                        "sessionUpdate": "tool_call_update",
                        "toolCallId": "direct-metric",
                        "title": "mcp__posthog__data-catalog-metric-run",
                        "_meta": {"claudeCode": {"toolName": "mcp__posthog__data-catalog-metric-run"}},
                        "status": "completed",
                        "rawInput": arguments,
                        "rawOutput": [
                            {
                                "type": "text",
                                "text": json.dumps(
                                    {
                                        "structuredContent": {"results": [{"count": 12}]},
                                        "isError": False,
                                    }
                                ),
                            }
                        ],
                    }
                )
            ]
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].arguments, arguments)

    def test_direct_call_preserves_completed_error_and_truncation_state(self) -> None:
        calls = self._calls(
            [
                self._entry(
                    {
                        "sessionUpdate": "tool_call_update",
                        "toolCallId": "direct-error",
                        "title": "mcp__posthog__query-insight",
                        "_meta": {"claudeCode": {"toolName": "mcp__posthog__query-insight"}},
                        "status": "completed",
                        "rawInput": {"arguments": {"insight_id": "example-insight"}},
                        "rawOutput": [
                            {
                                "type": "text",
                                "text": json.dumps(
                                    {
                                        "structuredContent": {"message": "result incomplete"},
                                        "isError": True,
                                        "isTruncated": True,
                                    }
                                ),
                            }
                        ],
                    }
                )
            ]
        )

        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].is_error)
        self.assertTrue(calls[0].is_truncated)

    def test_does_not_classify_a_direct_call_from_untrusted_input_or_title(self) -> None:
        calls = self._calls(
            [
                self._entry(
                    {
                        "sessionUpdate": "tool_call_update",
                        "toolCallId": "forged-direct",
                        "title": "mcp__posthog__query-insight",
                        "status": "completed",
                        "rawInput": {
                            "name": "mcp__posthog__query-insight",
                            "arguments": {"insight_id": "example-insight"},
                        },
                        "rawOutput": [
                            {
                                "type": "text",
                                "text": json.dumps({"structuredContent": {"value": 12}}),
                            }
                        ],
                    }
                )
            ]
        )

        self.assertEqual(calls, [])

    def test_skips_invalid_scope_noncompleted_nonjson_and_oversized_calls(self) -> None:
        oversized = "x" * (33 * 1024)
        calls = self._calls(
            [
                self._entry(
                    {
                        "sessionUpdate": "tool_call_update",
                        "toolCallId": "failed-1",
                        "title": "mcp__posthog__query-insight",
                        "status": "failed",
                        "rawInput": {"arguments": {"insight_id": "example-insight"}},
                    }
                ),
                self._entry(
                    {
                        "sessionUpdate": "tool_call_update",
                        "toolCallId": "plain-exec",
                        "title": "Execute command",
                        "status": "completed",
                        "rawInput": {"command": 'call query-insight {"insight_id":"example-insight"}'},
                    }
                ),
                self._entry(
                    {
                        "sessionUpdate": "tool_call_update",
                        "toolCallId": "large-1",
                        "title": "mcp__posthog__query-insight",
                        "status": "completed",
                        "rawInput": {"arguments": {"query": oversized}},
                        "rawOutput": [
                            {
                                "type": "text",
                                "text": json.dumps({"structuredContent": {"value": 1}}),
                            }
                        ],
                    }
                ),
            ]
        )

        self.assertEqual(calls, [])
        self.assertEqual(
            facade.get_completed_posthog_mcp_tool_calls(self.task_run.id, self.task.id, self.team.id + 1), []
        )

        self.task_run.status = TaskRun.Status.IN_PROGRESS
        self.task_run.save(update_fields=["status"])
        self.assertEqual(
            facade.get_completed_posthog_mcp_tool_calls(self.task_run.id, self.task.id, self.team.id),
            [],
        )
