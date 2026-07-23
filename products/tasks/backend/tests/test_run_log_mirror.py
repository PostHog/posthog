import json

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase, override_settings

from parameterized import parameterized

from posthog.models import Organization, Team

from products.tasks.backend.logic.services.run_log_mirror import (
    MAX_BODY_CHARS,
    MAX_ENTRIES_PER_CALL,
    MAX_IDENTIFIER_CHARS,
    mirror_entries,
)
from products.tasks.backend.models import Task, TaskRun

RUN_ID = "0b166f65-9e52-4d1b-b3c4-1a9e3f6d3c21"
TASK_ID = "7d0e9a34-2f1c-4b8a-9c3d-5e6f7a8b9c0d"


def _mirror(entries: list[dict]) -> MagicMock:
    with patch("products.tasks.backend.logic.services.run_log_mirror.logger") as mock_logger:
        mirror_entries(entries, team_id=2, task_id=TASK_ID, run_id=RUN_ID, origin_product="signals_scout")
    return mock_logger


def _session_update_entry(session_update: str, **update_fields) -> dict:
    return {
        "type": "notification",
        "timestamp": "2026-07-15T10:00:00+00:00",
        "notification": {
            "method": "session/update",
            "params": {"update": {"sessionUpdate": session_update, **update_fields}},
        },
    }


class TestMirrorEntries(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "agent_message",
                _session_update_entry("agent_message", content={"type": "text", "text": "hello"}),
                "info",
                "[agent_message] hello",
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
                "warning",
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
    def test_severity_and_body_mapping(self, _name, entry, expected_log_method, expected_body):
        mock_logger = _mirror([entry])
        log_call = getattr(mock_logger, expected_log_method)
        log_call.assert_called_once()
        self.assertEqual(log_call.call_args.kwargs["body"], expected_body)

    @parameterized.expand(
        [
            (
                "protocol_request",
                {
                    "method": "session/new",
                    "params": {
                        "mcpServers": [
                            {
                                "headers": [
                                    {"name": "Authorization", "value": "Bearer protocol-secret"},
                                ]
                            }
                        ]
                    },
                },
                "[session/new]",
            ),
            (
                "metadata_session_update",
                _session_update_entry(
                    "available_commands_update",
                    availableCommands=[{"name": "example", "description": "metadata-secret"}],
                )["notification"],
                "[available_commands_update]",
            ),
        ]
    )
    def test_protocol_metadata_omits_payload(self, _name, notification, expected_body):
        mock_logger = _mirror([{"notification": notification}])
        body = mock_logger.info.call_args.kwargs["body"]
        self.assertEqual(body, expected_body)
        self.assertNotIn("secret", body)

    def test_emitted_fields_carry_run_identity(self):
        mock_logger = _mirror([_session_update_entry("agent_message", content={"type": "text", "text": "hi"})])
        self.assertEqual(mock_logger.info.call_args.args, ("task_run_log",))
        fields = mock_logger.info.call_args.kwargs
        self.assertEqual(fields["request_id"], RUN_ID)
        self.assertEqual(fields["task_run_id"], RUN_ID)
        self.assertEqual(fields["task_id"], TASK_ID)
        self.assertEqual(fields["team_id"], 2)
        self.assertEqual(fields["origin_product"], "signals_scout")
        self.assertEqual(fields["acp_method"], "session/update")
        self.assertEqual(fields["acp_session_update"], "agent_message")
        self.assertEqual(fields["entry_timestamp"], "2026-07-15T10:00:00+00:00")

    def test_oversized_body_is_truncated(self):
        entry = _session_update_entry("agent_message", content={"type": "text", "text": "x" * (MAX_BODY_CHARS * 2)})
        mock_logger = _mirror([entry])
        self.assertEqual(len(mock_logger.info.call_args.kwargs["body"]), MAX_BODY_CHARS)

    def test_oversized_identifier_fields_are_capped(self):
        entry = {"timestamp": "9" * 100_000, "notification": {"method": "m" * 100_000}}
        mock_logger = _mirror([entry])
        fields = mock_logger.info.call_args.kwargs
        self.assertEqual(len(fields["acp_method"]), MAX_IDENTIFIER_CHARS)
        self.assertEqual(len(fields["entry_timestamp"]), MAX_IDENTIFIER_CHARS)

    def test_deeply_nested_content_returns_type_only_body(self):
        content: list = ["bottom"]
        for _ in range(2_000):
            content = [content]
        mock_logger = _mirror([_session_update_entry("agent_message", content=content)])
        self.assertEqual(mock_logger.info.call_args.kwargs["body"], "[agent_message]")

    def test_oversized_batch_is_capped(self):
        entries = [
            _session_update_entry("agent_message", content={"type": "text", "text": f"line {i}"})
            for i in range(MAX_ENTRIES_PER_CALL + 50)
        ]
        mock_logger = _mirror(entries)
        self.assertEqual(mock_logger.info.call_count, MAX_ENTRIES_PER_CALL)
        mock_logger.warning.assert_called_once()
        self.assertEqual(mock_logger.warning.call_args.kwargs["dropped"], 50)

    @parameterized.expand([("empty", []), ("non_dict_entries", ["not-a-dict", 42])])
    def test_no_usable_entries_emits_nothing(self, _name, entries):
        mock_logger = _mirror(entries)
        mock_logger.info.assert_not_called()
        mock_logger.warning.assert_not_called()
        mock_logger.error.assert_not_called()


class TestMirrorOtlpDelivery(SimpleTestCase):
    @override_settings(
        TASK_RUN_LOGS_MIRROR_OTLP_URL="https://us.i.posthog.com/i/v1/logs",
        TASK_RUN_LOGS_MIRROR_OTLP_TOKEN="phc_internal",
    )
    def test_posts_one_otlp_batch_with_severity_trace_and_attributes(self):
        entries = [
            _session_update_entry("agent_message", content={"type": "text", "text": "hello"}),
            {"notification": {"method": "_posthog/error", "params": {"message": "boom"}}},
        ]
        with patch("products.tasks.backend.logic.services.run_log_mirror.internal_requests") as mock_requests:
            _mirror(entries)

        mock_requests.post.assert_called_once()
        args, kwargs = mock_requests.post.call_args
        assert args[0] == "https://us.i.posthog.com/i/v1/logs"
        # The configured internal-project token routes the records — never a key
        # derived from the run's (customer) team.
        assert kwargs["headers"] == {"Authorization": "Bearer phc_internal"}
        records = kwargs["json"]["resourceLogs"][0]["scopeLogs"][0]["logRecords"]
        assert [r["severityText"] for r in records] == ["INFO", "ERROR"]
        assert records[0]["body"]["stringValue"] == "[agent_message] hello"
        assert records[1]["body"]["stringValue"] == "boom"
        # The run uuid (dashes stripped) is the trace id, grouping the run.
        assert records[0]["traceId"] == RUN_ID.replace("-", "")
        attributes = {a["key"]: a["value"] for a in records[0]["attributes"]}
        assert attributes["event"] == {"stringValue": "task_run_log"}
        assert attributes["task_run_id"] == {"stringValue": RUN_ID}
        # OTLP JSON encodes 64-bit ints as strings.
        assert attributes["team_id"] == {"intValue": "2"}

    @override_settings(
        TASK_RUN_LOGS_MIRROR_OTLP_URL="https://us.i.posthog.com/i/v1/logs",
        TASK_RUN_LOGS_MIRROR_OTLP_TOKEN="phc_internal",
    )
    def test_protocol_payloads_never_reach_the_otlp_payload(self):
        entry = {
            "notification": {
                "method": "session/new",
                "params": {"mcpServers": [{"headers": [{"name": "Authorization", "value": "Bearer protocol-secret"}]}]},
            }
        }
        with patch("products.tasks.backend.logic.services.run_log_mirror.internal_requests") as mock_requests:
            _mirror([entry])

        payload = mock_requests.post.call_args.kwargs["json"]
        self.assertNotIn("protocol-secret", json.dumps(payload))
        records = payload["resourceLogs"][0]["scopeLogs"][0]["logRecords"]
        # The attribute set is closed: run identity plus entry type, never raw params.
        self.assertEqual(
            {a["key"] for a in records[0]["attributes"]},
            {"event", "request_id", "task_run_id", "task_id", "team_id", "origin_product", "acp_method"},
        )

    @parameterized.expand(
        [
            ("both_unset", None, None),
            ("url_only", "https://us.i.posthog.com/i/v1/logs", None),
            ("token_only", None, "phc_internal"),
        ]
    )
    def test_no_http_delivery_unless_fully_configured(self, _name, url, token):
        entry = _session_update_entry("agent_message", content={"type": "text", "text": "hello"})
        with override_settings(TASK_RUN_LOGS_MIRROR_OTLP_URL=url, TASK_RUN_LOGS_MIRROR_OTLP_TOKEN=token):
            with patch("products.tasks.backend.logic.services.run_log_mirror.internal_requests") as mock_requests:
                _mirror([entry])

        mock_requests.post.assert_not_called()


@override_settings(TASK_RUN_LOGS_MIRROR_ORIGIN_PRODUCTS=["signals_scout"])
class TestAppendLogMirroring(TestCase):
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
    @patch("products.tasks.backend.logic.services.run_log_mirror.logger")
    @patch("products.tasks.backend.models.object_storage")
    def test_mirrors_only_allowlisted_origin_products(self, origin_product, expect_mirrored, mock_storage, mock_logger):
        mock_storage.read.return_value = None
        run = self._create_run(origin_product)
        message = _session_update_entry("agent_message", content={"type": "text", "text": "hi"})
        chunk = _session_update_entry("agent_message_chunk", content={"type": "text", "text": "h"})

        run.append_log([message, chunk])

        mock_storage.write.assert_called_once()
        if expect_mirrored:
            # The chunk entry is dropped before persistence, so exactly one line is mirrored.
            mock_logger.info.assert_called_once()
            self.assertEqual(mock_logger.info.call_args.kwargs["task_run_id"], str(run.id))
            self.assertEqual(mock_logger.info.call_args.kwargs["origin_product"], origin_product)
        else:
            mock_logger.info.assert_not_called()

    @override_settings(TASK_RUN_LOGS_MIRROR_ORIGIN_PRODUCTS=[])
    @patch("products.tasks.backend.logic.services.run_log_mirror.logger")
    @patch("products.tasks.backend.models.object_storage")
    def test_no_mirroring_when_disabled(self, mock_storage, mock_logger):
        mock_storage.read.return_value = None
        run = self._create_run(Task.OriginProduct.SIGNALS_SCOUT)

        run.append_log([_session_update_entry("agent_message", content={"type": "text", "text": "hi"})])

        mock_storage.write.assert_called_once()
        mock_logger.info.assert_not_called()

    @patch(
        "products.tasks.backend.logic.services.run_log_mirror.mirror_entries",
        side_effect=RuntimeError("kaboom"),
    )
    @patch("products.tasks.backend.models.object_storage")
    def test_mirror_failure_does_not_break_log_write(self, mock_storage, mock_mirror):
        mock_storage.read.return_value = None
        run = self._create_run(Task.OriginProduct.SIGNALS_SCOUT)

        run.append_log([_session_update_entry("agent_message", content={"type": "text", "text": "hi"})])

        mock_storage.write.assert_called_once()
        mock_mirror.assert_called_once()
