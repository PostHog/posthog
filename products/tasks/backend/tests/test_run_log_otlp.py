import json
import uuid

from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings

from parameterized import parameterized

from posthog.models import Organization, Team

from products.tasks.backend.logic.services.run_log_otlp import MAX_BODY_CHARS, build_otlp_payload
from products.tasks.backend.models import Task, TaskRun

RUN_ID = "0b166f65-9e52-4d1b-b3c4-1a9e3f6d3c21"
TASK_ID = "7d0e9a34-2f1c-4b8a-9c3d-5e6f7a8b9c0d"


def _build(entries: list[dict]) -> dict | None:
    return build_otlp_payload(entries, team_id=2, task_id=TASK_ID, run_id=RUN_ID, origin_product="signals_scout")


def _session_update_entry(session_update: str, **update_fields) -> dict:
    return {
        "type": "notification",
        "timestamp": "2026-07-15T10:00:00+00:00",
        "notification": {
            "method": "session/update",
            "params": {"update": {"sessionUpdate": session_update, **update_fields}},
        },
    }


class TestBuildOtlpPayload(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "agent_message",
                _session_update_entry("agent_message", content={"type": "text", "text": "hello"}),
                "info",
                "[agent_message] hello",
            ),
            (
                "agent_thought_is_debug",
                _session_update_entry("agent_thought_chunk", content={"type": "text", "text": "thinking"}),
                "debug",
                "[agent_thought_chunk] thinking",
            ),
            (
                "tool_call_without_content",
                _session_update_entry("tool_call", title="grep", status="in_progress"),
                "info",
                "[tool_call] grep (in_progress)",
            ),
            (
                "posthog_error",
                {"notification": {"method": "_posthog/error", "params": {"message": "boom"}}},
                "error",
                "boom",
            ),
            (
                "console_level_passthrough",
                {"notification": {"method": "_posthog/console", "params": {"level": "warn", "message": "careful"}}},
                "warn",
                "careful",
            ),
            (
                "sandbox_output",
                {
                    "notification": {
                        "method": "_posthog/sandbox_output",
                        "params": {"stdout": "out", "stderr": "err", "exitCode": 1},
                    }
                },
                "info",
                "[sandbox_output exit=1] out\nstderr: err",
            ),
            (
                "turn_end_result",
                {"notification": {"result": {"stopReason": "end_turn"}}},
                "info",
                "[turn_end] end_turn",
            ),
        ]
    )
    def test_severity_and_body_mapping(self, _name, entry, expected_severity, expected_body):
        payload = _build([entry])
        assert payload is not None
        record = payload["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]
        self.assertEqual(record["severityText"], expected_severity)
        self.assertEqual(record["body"]["stringValue"], expected_body)

    def test_unrecognized_entry_falls_back_to_json_body(self):
        notification = {"method": "session/request_permission", "params": {"tool": "bash"}}
        payload = _build([{"notification": notification}])
        assert payload is not None
        record = payload["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]
        self.assertEqual(json.loads(record["body"]["stringValue"]), notification)

    def test_payload_structure_carries_run_identity(self):
        payload = _build([_session_update_entry("agent_message", content={"type": "text", "text": "hi"})])
        assert payload is not None
        resource_attrs = {
            attr["key"]: attr["value"]["stringValue"] for attr in payload["resourceLogs"][0]["resource"]["attributes"]
        }
        self.assertEqual(
            resource_attrs,
            {"service.name": "signals_scout", "team_id": "2", "task_id": TASK_ID, "task_run_id": RUN_ID},
        )
        record = payload["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]
        self.assertEqual(record["traceId"], uuid.UUID(RUN_ID).hex)
        self.assertEqual(record["timeUnixNano"], str(1784109600 * 1_000_000_000))
        record_attrs = {attr["key"]: attr["value"]["stringValue"] for attr in record["attributes"]}
        self.assertEqual(record_attrs["acp.method"], "session/update")
        self.assertEqual(record_attrs["acp.session_update"], "agent_message")

    def test_oversized_body_is_truncated(self):
        entry = _session_update_entry("agent_message", content={"type": "text", "text": "x" * (MAX_BODY_CHARS * 2)})
        payload = _build([entry])
        assert payload is not None
        record = payload["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]
        self.assertEqual(len(record["body"]["stringValue"]), MAX_BODY_CHARS)

    @parameterized.expand([("empty", []), ("non_dict_entries", ["not-a-dict", 42])])
    def test_no_usable_entries_returns_none(self, _name, entries):
        self.assertIsNone(_build(entries))


@override_settings(
    TASK_RUN_LOGS_OTLP_ENDPOINT="https://us.i.posthog.com/i/v1/logs",
    TASK_RUN_LOGS_OTLP_TOKEN="phc_test",
    TASK_RUN_LOGS_OTLP_ORIGIN_PRODUCTS=["signals_scout"],
)
class TestAppendLogForwarding(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(name="Test Org")
        cls.team = Team.objects.create(organization=cls.organization, name="Test Team")

    def _create_run(self, origin_product: str) -> TaskRun:
        task = Task.objects.create(
            team=self.team,
            title="Test Task",
            description="Test",
            origin_product=origin_product,
        )
        return TaskRun.objects.create(team=self.team, task=task)

    @parameterized.expand(
        [
            (Task.OriginProduct.SIGNALS_SCOUT, True),
            (Task.OriginProduct.USER_CREATED, False),
        ]
    )
    @patch("products.tasks.backend.tasks.forward_task_run_logs_to_posthog_logs.delay")
    @patch("products.tasks.backend.models.object_storage")
    def test_forwards_only_allowlisted_origin_products(
        self, origin_product, expect_forwarded, mock_storage, mock_delay
    ):
        mock_storage.read.return_value = None
        run = self._create_run(origin_product)
        message = _session_update_entry("agent_message", content={"type": "text", "text": "hi"})
        chunk = _session_update_entry("agent_message_chunk", content={"type": "text", "text": "h"})

        run.append_log([message, chunk])

        mock_storage.write.assert_called_once()
        if expect_forwarded:
            mock_delay.assert_called_once_with(
                entries=[message],
                team_id=self.team.id,
                task_id=str(run.task_id),
                run_id=str(run.id),
                origin_product=origin_product,
            )
        else:
            mock_delay.assert_not_called()

    @override_settings(TASK_RUN_LOGS_OTLP_ENDPOINT=None, TASK_RUN_LOGS_OTLP_TOKEN=None)
    @patch("products.tasks.backend.tasks.forward_task_run_logs_to_posthog_logs.delay")
    @patch("products.tasks.backend.models.object_storage")
    def test_no_forwarding_when_unconfigured(self, mock_storage, mock_delay):
        mock_storage.read.return_value = None
        run = self._create_run(Task.OriginProduct.SIGNALS_SCOUT)

        run.append_log([_session_update_entry("agent_message", content={"type": "text", "text": "hi"})])

        mock_storage.write.assert_called_once()
        mock_delay.assert_not_called()

    @patch(
        "products.tasks.backend.tasks.forward_task_run_logs_to_posthog_logs.delay", side_effect=RuntimeError("kaboom")
    )
    @patch("products.tasks.backend.models.object_storage")
    def test_dispatch_failure_does_not_break_log_write(self, mock_storage, mock_delay):
        mock_storage.read.return_value = None
        run = self._create_run(Task.OriginProduct.SIGNALS_SCOUT)

        run.append_log([_session_update_entry("agent_message", content={"type": "text", "text": "hi"})])

        mock_storage.write.assert_called_once()
        mock_delay.assert_called_once()
