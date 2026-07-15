import json

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase, override_settings

from parameterized import parameterized

from posthog.models import Organization, Team

from products.tasks.backend.logic.services.run_log_mirror import MAX_BODY_CHARS, mirror_entries
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

    def test_unrecognized_entry_falls_back_to_json_body(self):
        notification = {"method": "session/request_permission", "params": {"tool": "bash"}}
        mock_logger = _mirror([{"notification": notification}])
        self.assertEqual(json.loads(mock_logger.info.call_args.kwargs["body"]), notification)

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

    @parameterized.expand([("empty", []), ("non_dict_entries", ["not-a-dict", 42])])
    def test_no_usable_entries_emits_nothing(self, _name, entries):
        mock_logger = _mirror(entries)
        mock_logger.info.assert_not_called()
        mock_logger.warning.assert_not_called()
        mock_logger.error.assert_not_called()


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
